import { expect, test } from 'claude-code/testing'

import {
  agentLabel,
  CONTRACT,
  fresh,
  limitsFrom,
  MARK,
  nudgeNote,
  planningRules,
  refusal,
  setting,
  tokens,
  verdict,
  WIND_DOWN_CALLS,
  windDownNote,
  withContract,
} from '../hooks/register'

const LIMITS = { nudge: 300_000, stop: 450_000 }

test('uses the defaults, and keeps the stop limit above the nudge', async () => {
  expect(limitsFrom({})).toEqual(LIMITS)
  expect(limitsFrom({ nudgeAtK: 200, stopAtK: 250 })).toEqual({ nudge: 200_000, stop: 250_000 })
  // a stop at or below the nudge would refuse an agent before it could checkpoint
  expect(limitsFrom({ nudgeAtK: 300, stopAtK: 100 })).toEqual({ nudge: 300_000, stop: 350_000 })
  expect(limitsFrom({ nudgeAtK: 'lots' })).toEqual(LIMITS)
  expect(setting(0, 300, 50, 10_000)).toBe(50)
})

test('lets a small agent run', async () => {
  expect(verdict({ ...fresh(), context: 47_000 }, LIMITS)).toEqual({ kind: 'run' })
  expect(verdict({ ...fresh(), context: 299_999 }, LIMITS)).toEqual({ kind: 'run' })
})

test('asks an agent to checkpoint once, when it first passes the nudge limit', async () => {
  const budget = { ...fresh(), context: 300_000 }
  expect(verdict(budget, LIMITS)).toEqual({ kind: 'nudge' })
  budget.isNudged = true
  expect(verdict({ ...budget, context: 380_000 }, LIMITS)).toEqual({ kind: 'run' })
})

test('gives an agent past the stop limit a few calls to checkpoint, then refuses', async () => {
  // an agent that jumped straight past both limits in one read is wound down, not nudged
  const budget = { ...fresh(), context: 470_000 }
  const seen: string[] = []
  for (let i = 0; i < WIND_DOWN_CALLS + 2; i++) {
    const decided = verdict(budget, LIMITS)
    seen.push(decided.kind === 'wind-down' ? `left ${decided.left}` : decided.kind)
    if (decided.kind === 'wind-down') budget.windDownCalls += 1
  }
  expect(seen).toEqual(['left 7', 'left 6', 'left 5', 'left 4', 'left 3', 'left 2', 'left 1', 'left 0', 'refuse', 'refuse'])
})

test('formats token counts', async () => {
  expect(tokens(455_000)).toBe('455K')
  expect(tokens(1_200_000)).toBe('1.2M')
})

test('marks every note and asks for a CHECKPOINT report', async () => {
  for (const text of [CONTRACT, nudgeNote(310_000, LIMITS), windDownNote(460_000, 3, LIMITS), refusal(500_000, LIMITS)]) {
    expect(text.startsWith(MARK)).toBe(true)
    expect(text.includes('CHECKPOINT:')).toBe(true)
  }
})

test('adds the contract to a brief once, even when the brief quotes a note', async () => {
  const brief = 'Continue from docs/handoff/a.md.'
  expect(withContract(brief)).toBe(`${brief}\n\n${CONTRACT}`)
  // a successor's brief copied from its predecessor's already carries it
  expect(withContract(withContract(brief))).toBe(withContract(brief))
  // quoting a note is not carrying the contract
  const quoting = `The last agent was told: "${nudgeNote(310_000, LIMITS)}"`
  expect(withContract(quoting)).toBe(`${quoting}\n\n${CONTRACT}`)
})

test('tells the agent how many calls it has left, and when it has none', async () => {
  expect(windDownNote(460_000, 3, LIMITS)).toContain('You have 3 tool calls left')
  expect(windDownNote(460_000, 0, LIMITS)).toContain('That was your last tool call.')
  expect(nudgeNote(310_000, LIMITS)).toContain('At 450K your tools start being refused.')
})

test('states the configured limits in the planning rules', async () => {
  const rules = planningRules({ nudge: 200_000, stop: 280_000 })
  expect(rules).toContain('well under 200K tokens')
  expect(rules).toContain('at 280K it starts refusing')
  expect(rules).toContain('subagent-limits:split-work')
})

test('names an agent by its task, or by its id when it has none', async () => {
  expect(agentLabel('ae9ca49e548d4f774', 'Builder A: evidence checks')).toBe('Builder A: evidence checks')
  expect(agentLabel('ae9ca49e548d4f774', undefined)).toBe('Agent ae9ca49e')
  expect(agentLabel('ae9ca49e548d4f774', '')).toBe('Agent ae9ca49e')
})
