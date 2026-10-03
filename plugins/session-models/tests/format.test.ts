import { expect, test } from 'claude-code/testing'

import { biggestContext, crowdAlarm, family, formatModels, liveAgents, setting, tokens } from '../hooks/register'

const LIMITS = { liveAgents: 6, context: 300_000 }
const MIN = 60_000
const opus = 'claude-opus-5-5'
const sonnet = 'claude-sonnet-5-5'

test('names model families', async () => {
  expect(family(opus)).toBe('Opus')
  expect(family('claude-haiku-4-5-20251001')).toBe('Haiku')
  expect(family('claude-sonnet-5-5[1m]')).toBe('Sonnet')
})

test('formats token counts', async () => {
  expect(tokens(955_492)).toBe('955K')
  expect(tokens(1_200_000)).toBe('1.2M')
})

test('shows the model alone until an agent beyond the main thread runs', async () => {
  expect(formatModels(opus, {}, new Set(), LIMITS)).toBe('model: Opus')
  expect(formatModels(opus, { main: { models: [opus], context: 50_000 } }, new Set(), LIMITS)).toBe('model: Opus')
})

test('counts agents per model, with the live ones called out', async () => {
  const agents = {
    main: { models: [opus], context: 50_000 },
    a1: { models: [sonnet], context: 20_000 },
    a2: { models: [sonnet], context: 20_000 },
    a3: { models: [opus], context: 20_000 },
    t1: { models: [opus, 'claude-haiku-4-5-20251001'], context: 20_000 },
  }
  const line = formatModels(opus, agents, new Set(['a1']), LIMITS)
  expect(line).toBe('model: Opus · agents: Opus (3, 1 live), Sonnet (2, 1 live), Haiku (1)')
})

test('says live even when every agent of a model is live', async () => {
  const agents = { main: { models: [opus], context: 1 }, a1: { models: [opus], context: 1 } }
  expect(formatModels(opus, agents, new Set(['a1']), LIMITS)).toBe('model: Opus · agents: Opus (2, 2 live)')
})

test('treats finished agents as not live, and main as always live', async () => {
  const agents = { main: { models: [opus], context: 1 }, a1: { models: [opus], context: 1 } }
  expect(liveAgents(agents, new Set())).toEqual(['main'])
})

test('warns about a crowd of live agents and the biggest live context', async () => {
  // the shape of a runaway session: a dozen background Opus agents near a million tokens each
  const agents: Record<string, { models: string[]; context: number }> = { main: { models: [opus], context: 80_000 } }
  const running = new Set<string>()
  for (let i = 0; i < 12; i++) {
    agents[`a${i}`] = { models: [opus], context: 800_000 + i * 10_000 }
    running.add(`a${i}`)
  }
  agents.done = { models: [opus], context: 990_000 }
  expect(biggestContext(agents, liveAgents(agents, running), LIMITS.context)).toEqual({ id: 'a11', context: 910_000 })
  expect(formatModels(opus, agents, running, LIMITS)).toBe(
    'model: Opus · agents: Opus (14, 13 live) · ⚠ 13 live · ⚠ ctx 910K',
  )
})

test('toasts a crowd once, not on every wobble around the threshold', async () => {
  let crowd = { isArmed: true, lastToastAt: -Infinity }
  const step = (live: number, at: number) => {
    const alarm = crowdAlarm(crowd, live, at, 6)
    crowd = alarm.crowd
    return alarm.toast
  }
  expect(step(6, 0)).toBe(true)
  // agents finish and start around the threshold: no repeat
  expect(step(5, MIN)).toBe(false)
  expect(step(6, 2 * MIN)).toBe(false)
  // it re-arms only once the count falls well below, and stays quiet for ten minutes
  expect(step(3, 3 * MIN)).toBe(false)
  expect(step(7, 4 * MIN)).toBe(false)
  expect(step(3, 5 * MIN)).toBe(false)
  expect(step(7, 11 * MIN)).toBe(true)
})

test('holds settings within bounds', async () => {
  expect(setting(undefined, 6, 2, 100)).toBe(6)
  expect(setting(0, 6, 2, 100)).toBe(2)
  expect(setting('lots', 6, 2, 100)).toBe(6)
})
