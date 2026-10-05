import type { AgentInfo, On, ToolCallResult, TurnUsage } from 'claude-code'
import type { Engine, MockClock } from 'claude-code/testing'
import { expect, mock, test } from 'claude-code/testing'

import { CONTRACT, cacheDrop, cacheNote, DROP, MARK, withContract } from '../hooks/register'

const MIN = 60_000
const MODEL = 'claude-sonnet-4-6'
const AGENT: AgentInfo = { id: 'a1b2c3d4e5f6', description: 'Builder A: parser', type: 'general-purpose', status: 'running' }

// a request that read its context from the cache, and one that wrote all of it again
function warm(context: number): TurnUsage {
  return { model: MODEL, input_tokens: 2, output_tokens: 300, cache_read_input_tokens: context - 2_002, cache_creation_input_tokens: 2_000 }
}
function cold(context: number, model = MODEL): TurnUsage {
  return { model, input_tokens: 2, output_tokens: 300, cache_read_input_tokens: 10_000, cache_creation_input_tokens: context - 10_002 }
}

type World = {
  clock: MockClock
  toasts: string[]
  // one model request of the agent, answered with this usage, after `pauseMs` of quiet
  // `finishes`: the response ends the agent's run instead of calling a tool; `turnId`: the run the request is in
  step: (usage: TurnUsage, options?: { pauseMs?: number; agentId?: string; turnId?: string; finishes?: boolean }) => Promise<void>
  // one tool call of the agent: the notes the model reads after its result
  call: (agentId?: string) => Promise<readonly string[]>
}

// the engine beneath the plugin: a mocked clock, a model that answers with the usage given, tools that answer "ok"
function world($: Engine, on: On): World {
  const clock = mock.clock(on, { now: 1_000_000 })
  const toasts: string[] = []
  let usage: TurnUsage = warm(50_000)
  let index = 0
  let messages = 0
  let finishes = false
  on('ui.toast', async (_, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('agent.list', async () => ({ value: [AGENT] }))
  on('turn.step', async function* (_, e) {
    const toolUses = finishes ? [] : [{ name: 'Bash', input: { command: 'make test' } }]
    return { turnId: e.turnId, index: e.index, answer: '', toolUses, stopReason: finishes ? ('end_turn' as const) : ('tool_use' as const), usage }
  })
  on('tool.call', async () => ({ result: 'ok' }))
  return {
    clock,
    toasts,
    async step(next, options = {}) {
      await clock.advance(options.pauseMs ?? 5_000)
      usage = next
      messages += 2
      finishes = options.finishes ?? false
      const stream = $.turn.step({ turnId: options.turnId ?? 't1', index: index++, model: MODEL, messageCount: messages, agentId: options.agentId ?? AGENT.id })
      for await (const _ of stream);
      await stream.result
    },
    async call(agentId = AGENT.id) {
      const result: ToolCallResult = await $.tool.call({ tool: 'Bash', command: 'true', agentId } as never)
      return result.context ?? []
    },
  }
}

const cacheNotes = (notes: readonly string[]) => notes.filter(n => n.includes('prompt cache expired'))

test('states the cache advice in the contract, once', async () => {
  expect(CONTRACT).toContain("don't wait in sleep loops")
  const brief = withContract(withContract('Fix the parser.'))
  expect(brief.split('prompt cache expire').length - 1).toBe(1)
})

test('sees a drop only after a long pause that rebuilt most of a large context', async () => {
  const last = { turnId: 't1', endedAt: 0, model: MODEL, messageCount: 10, calledTools: true }
  const pause = 7 * MIN
  const now = { turnId: 't1', startedAt: pause, messageCount: 12 }
  expect(cacheDrop(last, now, cold(240_000))).toEqual({ rebuilt: 229_998, pauseMs: pause })
  // first request, small context, short pause, mostly cached, another model, a compaction
  expect(cacheDrop(undefined, now, cold(240_000))).toBeUndefined()
  expect(cacheDrop(last, now, cold(DROP.minContext - 1))).toBeUndefined()
  expect(cacheDrop(last, { ...now, startedAt: 4 * MIN }, cold(240_000))).toBeUndefined()
  expect(cacheDrop(last, now, warm(240_000))).toBeUndefined()
  expect(cacheDrop(last, now, cold(240_000, 'claude-opus-4-1'))).toBeUndefined()
  expect(cacheDrop(last, { ...now, messageCount: 4 }, cold(240_000))).toBeUndefined()
  // an agent resumed after it finished: it was not waiting on its own tool call
  expect(cacheDrop({ ...last, calledTools: false }, now, cold(240_000))).toBeUndefined()
  expect(cacheDrop(last, { ...now, turnId: 't2' }, cold(240_000))).toBeUndefined()
})

test('tells the agent the measured size and pause on its next tool call, once', async ($, on) => {
  const w = world($, on)
  await w.step(warm(60_000))
  await w.step(warm(230_000))
  await w.step(cold(240_000), { pauseMs: 7 * MIN })
  const notes = cacheNotes(await w.call())
  expect(notes).toEqual([
    `${MARK} Your last request rebuilt 230K tokens of context because the prompt cache expired during a 7-minute pause. If you need to wait on a long job again, check on it before it runs that long, or run something shorter.`,
  ])
  expect(notes[0]).toBe(cacheNote({ rebuilt: 229_998, pauseMs: 7 * MIN }))
  expect(w.toasts).toEqual(['Builder A: parser rebuilt 230K of context: its prompt cache expired during a 7-minute pause'])
  // the next call carries nothing, and a second drop brings no second note or toast
  expect(cacheNotes(await w.call())).toEqual([])
  await w.step(cold(260_000), { pauseMs: 12 * MIN })
  expect(cacheNotes(await w.call())).toEqual([])
  expect(w.toasts.length).toBe(1)
})

test('says nothing for a small context, a short pause, or a first request', async ($, on) => {
  const w = world($, on)
  // the agent's first request writes its whole context to the cache, however long it waited to start
  await w.step(cold(150_000), { pauseMs: 20 * MIN })
  expect(cacheNotes(await w.call())).toEqual([])
  await w.step(cold(150_000), { pauseMs: 3 * MIN })
  expect(cacheNotes(await w.call())).toEqual([])
  await w.step(cold(80_000), { pauseMs: 20 * MIN })
  expect(cacheNotes(await w.call())).toEqual([])
  expect(w.toasts).toEqual([])
})

test('says nothing to an agent resumed after it finished', async ($, on) => {
  const w = world($, on)
  await w.step(warm(200_000))
  await w.step(warm(210_000), { finishes: true })
  // resumed half an hour later, in a new run: the pause was not its own wait
  await w.step(cold(220_000), { pauseMs: 30 * MIN, turnId: 't2' })
  expect(cacheNotes(await w.call())).toEqual([])
  expect(w.toasts).toEqual([])
})

test('leaves forks alone', async ($, on) => {
  const w = world($, on)
  on('agent.spawn', async () => ({ model: MODEL, agentId: 'fork1' }))
  await $.agent.spawn({
    tool_use_id: 'tu1',
    prompt: 'look',
    description: 'fork',
    subagentType: 'fork',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: MODEL,
    background: false,
    fork: true,
  } as never)
  await w.step(warm(200_000), { agentId: 'fork1' })
  await w.step(cold(240_000), { agentId: 'fork1', pauseMs: 10 * MIN })
  expect(cacheNotes(await w.call('fork1'))).toEqual([])
  expect(w.toasts).toEqual([])
})

test('keeps the toast when the agent notes are off', { options: { cacheNotes: false } }, async ($, on) => {
  const w = world($, on)
  await w.step(warm(230_000))
  await w.step(cold(240_000), { pauseMs: 9 * MIN })
  expect(cacheNotes(await w.call())).toEqual([])
  expect(w.toasts).toEqual(['Builder A: parser rebuilt 230K of context: its prompt cache expired during a 9-minute pause'])
})
