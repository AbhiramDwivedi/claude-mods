import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On, RenderPropsOf } from 'claude-code'

const NOW = Date.parse('2026-10-03T12:00:00Z')
const HOUR = 3_600_000
const at = (ms: number) => new Date(ms).toISOString()

const BAND: RenderPropsOf['AbovePrompt'] = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 10,
  bodyColumns: 120,
  scroll: { offset: 0, bodyRows: 10 },
  view: {},
}

// the world beneath the plugin: a clock, the surfaces, a status line and toasts kept in memory,
// and a band line of its own beneath, as another plugin's would be
function world(on: On, surfaces: readonly ('terminal' | 'desktop' | 'vscode' | 'mobile')[]) {
  const seen = { status: undefined as string | undefined, toasts: [] as string[], clock: mock.clock(on, { now: NOW }) }
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.status', (_$, e) => {
    seen.status = e.text
    return { value: undefined }
  })
  on('ui.toast', (_$, e) => {
    seen.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.invalidate', () => ({ value: undefined }))
  on('session.measure', () => ({ changed: ['rateLimits'] }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>beneath</Text>
  })
  return seen
}

const MEASURE = {
  rateLimits: [
    { kind: 'five_hour', percentUsed: 24, resetsAt: at(NOW + 2 * HOUR) },
    // 60% three days into the week: on pace to run out before the reset
    { kind: 'seven_day', percentUsed: 60, resetsAt: at(NOW + 72 * HOUR) },
  ],
  context: { window: 200_000, tokens: 68_000, percent: 34 },
  cost: { usd: 1.23 },
  changed: ['rateLimits', 'context', 'cost'] as ('rateLimits' | 'context' | 'cost')[],
}

test('draws the line dim in the band, the run-out warning alone in the warning color', async ($, on) => {
  const seen = world(on, ['terminal', 'desktop'])
  await $.session.measure(MEASURE)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'usage-limits', surface, component: 'AbovePrompt', props: BAND })
    const texts = await ui.findAll({ type: 'Text' })
    const warnings = texts.filter(t => t.props.color === 'warning')
    expect(warnings.map(t => t.text)).toEqual(['⚠ 7d 60% +15%/d out in 2d16h'])
    expect(warnings[0]!.props.dimColor).toBeUndefined()
    const dim = texts.filter(t => t.props.dimColor === true).map(t => t.text)
    expect(dim).toEqual(['5h 24% (resets 2h0m) · ', ' · ctx 34% · $1.23'])
    // what was drawn beneath stays, above this plugin's line
    expect(texts[0]!.text).toBe('beneath')
    await ui.unmount()
  }
  // the band carries the line, so no status pins it in yellow
  expect(seen.status).toBeUndefined()
})

test("keeps another plugin's band line beside its own", {
  plugins: [
    {
      name: 'other-band',
      register(on) {
        on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
          const { Box, Text } = $.ui.resolve(e)
          return (
            <Box flexDirection="column">
              {await next(e)}
              <Text>other line</Text>
            </Box>
          )
        })
      },
    },
  ],
}, async ($, on) => {
  world(on, ['terminal'])
  await $.session.measure(MEASURE)
  const ui = await $.ui.mount({ plugin: 'usage-limits', surface: 'terminal', component: 'AbovePrompt', props: BAND })
  expect(await ui.find({ type: 'Text', text: 'other line' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /ctx 34%/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'beneath' })).toBeDefined()
})

test('yields the band to a survey', async ($, on) => {
  world(on, ['terminal'])
  await $.session.measure(MEASURE)
  const ui = await $.ui.mount({
    plugin: 'usage-limits',
    surface: 'terminal',
    component: 'AbovePrompt',
    props: { ...BAND, hasSurvey: true },
  })
  expect(await ui.find({ type: 'Text', text: /ctx/ })).toBeUndefined()
})

test('falls back to the status line only where no surface has a band', async ($, on) => {
  const seen = world(on, ['vscode'])
  await $.session.measure(MEASURE)
  expect(seen.status).toBe('5h 24% (resets 2h0m) · ⚠ 7d 60% +15%/d out in 2d16h · ctx 34% · $1.23')
})

test('keeps the terminal quiet when an IDE is attached beside it', async ($, on) => {
  const seen = world(on, ['terminal', 'vscode'])
  await $.session.measure(MEASURE)
  expect(seen.status).toBeUndefined()
})

// one model request of an agent (main when `agentId` is absent), answered beneath the plugin
// with `fresh` tokens written to the cache and `read` served from it
async function step($: Engine, agentId: string | undefined) {
  const stream = $.turn.step({
    turnId: 't1',
    index: 0,
    model: 'claude-opus-5-5',
    messageCount: 3,
    ...(agentId === undefined ? {} : { agentId }),
  })
  for await (const _ of stream) {
    // drained: the result settles once the stream is read to its end
  }
  return stream.result
}

test('counts cache drops per agent and shows them dim at the end of the line', async ($, on) => {
  const { clock } = world(on, ['terminal'])
  let answer = { fresh: 0, read: 0 }
  on('turn.step', async function* (_$, e) {
    return {
      turnId: e.turnId,
      index: e.index,
      answer: '',
      toolUses: [],
      stopReason: 'end_turn' as const,
      usage: {
        model: e.model,
        input_tokens: 2_000,
        output_tokens: 100,
        cache_creation_input_tokens: answer.fresh,
        cache_read_input_tokens: answer.read,
      },
    }
  })
  const send = (agentId: string | undefined, fresh: number, read: number) => {
    answer = { fresh, read }
    return step($, agentId)
  }
  await $.session.measure(MEASURE)
  // main and a subagent each start: first requests never count
  await send(undefined, 300_000, 0)
  await send('a1', 400_000, 0)
  await clock.advance(2 * 60_000)
  // main again two minutes on, served from the cache
  await send(undefined, 5_000, 300_000)
  await clock.advance(5 * 60_000)
  // the subagent comes back seven minutes on and rebuilds its whole context: a drop
  await send('a1', 410_000, 0)
  // main, five minutes after its last, also rebuilt: a second drop
  await send(undefined, 306_000, 0)
  const ui = await $.ui.mount({ plugin: 'usage-limits', surface: 'terminal', component: 'AbovePrompt', props: BAND })
  const dim = (await ui.findAll({ type: 'Text' })).filter(t => t.props.dimColor === true).map(t => t.text)
  expect(dim[dim.length - 1]).toBe(' · ctx 34% · $1.23 · cache drops 2 (716K)')
})
