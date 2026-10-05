import { expect, test } from 'claude-code/testing'

import {
  burnRate,
  cacheDrop,
  duration,
  formatLimit,
  formatUsage,
  needsStatus,
  pace,
  record,
  runs,
  runsOutIn,
  setting,
} from '../hooks/register'

const NOW = Date.parse('2026-10-03T12:00:00Z')
const MIN = 60_000
const HOUR = 60 * MIN
const at = (ms: number) => new Date(ms).toISOString()

test('formats both windows with reset countdowns, context and cost', async () => {
  const line = formatUsage(
    {
      rateLimits: [
        { kind: 'five_hour', percentUsed: 23.5, resetsAt: '2026-10-03T14:14:00Z' },
        { kind: 'seven_day', percentUsed: 41, resetsAt: '2026-10-06T16:00:00Z' },
      ],
      context: { window: 200000, tokens: 68000, percent: 34 },
      cost: { usd: 1.234 },
    },
    NOW,
  )
  expect(line).toBe('5h 24% (resets 2h14m) · 7d 41% (resets 3d4h) · ctx 34% · $1.23')
})

test('says when no limit reading has arrived yet', async () => {
  expect(formatUsage({ rateLimits: [], context: { window: 200000 } }, NOW)).toBe('limits: no reading yet')
})

test('needs five minutes of history before giving a rate', async () => {
  expect(burnRate([{ t: NOW - 2 * MIN, p: 10 }, { t: NOW, p: 12 }])).toBeUndefined()
  expect(burnRate([{ t: NOW - 30 * MIN, p: 10 }, { t: NOW, p: 25 }])).toBe(30)
})

test('flags a 5h window that will run out before it resets', async () => {
  // 40% used at +30%/h runs out in 2h, but the window only resets in 4h
  const limit = { kind: 'five_hour', percentUsed: 40, resetsAt: at(NOW + 4 * HOUR) }
  expect(runsOutIn(limit, 30, NOW)).toBe(2 * HOUR)
  expect(formatLimit(limit, NOW, 30)).toBe('⚠ 5h 40% +30%/h out in 2h0m')
})

test('stays calm when the pace finishes after the reset', async () => {
  const limit = { kind: 'five_hour', percentUsed: 40, resetsAt: at(NOW + HOUR) }
  expect(runsOutIn(limit, 30, NOW)).toBeUndefined()
  expect(formatLimit(limit, NOW, 30)).toBe('5h 40% +30%/h (resets 1h0m)')
})

test('never warns on a rate too small to show', async () => {
  const limit = { kind: 'five_hour', percentUsed: 99, resetsAt: at(NOW + 4 * HOUR) }
  expect(runsOutIn(limit, 0.5, NOW)).toBeUndefined()
})

test('judges the weekly window by its own average, not a busy half hour', async () => {
  // 60% used three days in (96h into the week, 72h left): 0.625 points an hour, 15%/d
  const limit = { kind: 'seven_day', percentUsed: 60, resetsAt: at(NOW + 72 * HOUR) }
  const busy = [{ t: NOW - 30 * MIN, p: 59.4 }, { t: NOW, p: 60 }]
  const rate = pace(limit, busy, NOW)
  expect(Math.round(rate! * 1000)).toBe(625)
  // at that average the last 40% takes 64h, before the 72h reset: a real warning
  expect(formatLimit(limit, NOW, rate)).toBe('⚠ 7d 60% +15%/d out in 2d16h')
  // half as much used by the same point is no warning at all
  const easy = { ...limit, percentUsed: 30 }
  expect(formatLimit(easy, NOW, pace(easy, busy, NOW))).toBe('7d 30% +8%/d (resets 3d0h)')
})

test('waits six hours into the week before giving a weekly pace', async () => {
  const limit = { kind: 'seven_day', percentUsed: 5, resetsAt: at(NOW + 7 * 24 * HOUR - 2 * HOUR) }
  expect(pace(limit, [], NOW)).toBeUndefined()
})

test('starts the history afresh when the window resets, not when a reading dips', async () => {
  const resetsAt = at(NOW + 3 * HOUR)
  let h = record(undefined, { kind: 'five_hour', percentUsed: 41, resetsAt }, NOW - 10 * MIN, 30 * MIN)
  // a stale reading arriving late keeps the history
  h = record(h, { kind: 'five_hour', percentUsed: 40, resetsAt }, NOW - 9 * MIN, 30 * MIN)
  expect(h.samples.length).toBe(2)
  // the same window reported with a slightly different reset time keeps it too
  h = record(h, { kind: 'five_hour', percentUsed: 45, resetsAt: at(NOW + 3 * HOUR + MIN) }, NOW, 30 * MIN)
  expect(h.samples.length).toBe(3)
  // a new window does not
  h = record(h, { kind: 'five_hour', percentUsed: 2, resetsAt: at(NOW + 5 * HOUR) }, NOW, 30 * MIN)
  expect(h.samples).toEqual([{ t: NOW, p: 2 }])
})

test('shows a window whose reset time has passed as reset', async () => {
  const limit = { kind: 'five_hour', percentUsed: 95, resetsAt: at(NOW - MIN) }
  expect(formatLimit(limit, NOW, 30)).toBe('5h reset')
})

test('holds settings within bounds', async () => {
  expect(setting(undefined, 30, 10, 300)).toBe(30)
  expect(setting(2, 30, 10, 300)).toBe(10)
  expect(setting('abc', 30, 10, 300)).toBe(30)
})

test('formats durations', async () => {
  expect(duration(12 * MIN)).toBe('12m')
  expect(duration(134 * MIN)).toBe('2h14m')
})

// a request's usage: `fresh` tokens written to the cache, `read` served from it, 2K uncached
const usage = (fresh: number, read: number) => ({
  input_tokens: 2_000,
  output_tokens: 500,
  cache_creation_input_tokens: fresh,
  cache_read_input_tokens: read,
})

test("never counts an agent's first request as a cache drop", async () => {
  expect(cacheDrop(undefined, NOW, usage(400_000, 0))).toBeUndefined()
})

test('ignores a rebuilt context under 100K', async () => {
  expect(cacheDrop(NOW - 10 * MIN, NOW, usage(90_000, 0))).toBeUndefined()
})

test('ignores a rebuild that comes soon after the previous request', async () => {
  // four minutes is inside the cache's lifetime: a big write then is new content, not a lapse
  expect(cacheDrop(NOW - 4 * MIN, NOW, usage(400_000, 0))).toBeUndefined()
})

test('ignores a request that mostly read its context from the cache', async () => {
  expect(cacheDrop(NOW - 10 * MIN, NOW, usage(100_000, 300_000))).toBeUndefined()
})

test('counts a big rebuild after a long wait as a cache drop, with the tokens rebuilt', async () => {
  // 380K of a 400K context written afresh six minutes after the previous request
  expect(cacheDrop(NOW - 6 * MIN, NOW, usage(380_000, 18_000))).toBe(380_000)
  // exactly half the context written counts too
  expect(cacheDrop(NOW - 6 * MIN, NOW, usage(100_000, 98_000))).toBe(100_000)
})

test('appends the cache drops to the line only once there are some', async () => {
  const measured = { rateLimits: [], context: { window: 200000, percent: 34 }, cost: { usd: 1.234 } }
  expect(formatUsage(measured, NOW, new Map(), { count: 0, tokens: 0 })).toBe('limits: no reading yet · ctx 34% · $1.23')
  expect(formatUsage(measured, NOW, new Map(), { count: 3, tokens: 1_900_000 })).toBe(
    'limits: no reading yet · ctx 34% · $1.23 · cache drops 3 (1.9M)',
  )
})

test('splits the line into dim runs and warning runs', async () => {
  expect(runs(['5h 40%', '⚠ 7d 60% out in 2d', 'ctx 3%', '$1.00'])).toEqual([
    { text: '5h 40% · ', isWarning: false },
    { text: '⚠ 7d 60% out in 2d', isWarning: true },
    { text: ' · ctx 3% · $1.00', isWarning: false },
  ])
})

test('falls back to the status line only where no surface has a band', async () => {
  expect(needsStatus(['terminal'])).toBe(false)
  expect(needsStatus(['terminal', 'desktop'])).toBe(false)
  expect(needsStatus(['terminal', 'mobile'])).toBe(false)
  expect(needsStatus(['mobile'])).toBe(true)
  expect(needsStatus(['vscode'])).toBe(true)
  expect(needsStatus([])).toBe(true)
})
