import type { EngineInterface, ModelUsage, Register, SessionRateLimit, SessionUsage } from 'claude-code'

const HOUR = 3_600_000
const LABELS: Record<string, string> = { five_hour: '5h', seven_day: '7d', spend_limit: 'spend' }
// a rolling rate needs at least this much history before it is shown
const MIN_SPAN_MS = 5 * 60_000
// the weekly pace is the window's own average, once it has run this long
const MIN_WEEK_ELAPSED_MS = 6 * HOUR
const WEEK_MS = 7 * 24 * HOUR
// a resetsAt that moves less than this is the same window, reported again
const SAME_WINDOW_MS = 10 * 60_000
// a request is a cache drop when it rewrites at least this share of a context at least
// this big, longer than this after the same agent's previous request
const DROP_SHARE = 0.5
const DROP_MIN_CONTEXT = 100_000
const DROP_MIN_GAP_MS = 4 * 60_000
// the surfaces that raise the AbovePrompt band; any other gets the line as a status
const BAND_SURFACES: readonly string[] = ['terminal', 'desktop']

export type Sample = { t: number; p: number }
export type History = { resetsAt?: string; samples: Sample[] }

// "2h14m" / "3d4h" / "12m"
export function duration(ms: number): string {
  const mins = Math.max(0, Math.round(ms / 60000))
  const d = Math.floor(mins / 1440)
  const h = Math.floor((mins % 1440) / 60)
  const m = mins % 60
  return d > 0 ? `${d}d${h}h` : h > 0 ? `${h}h${m}m` : `${m}m`
}

function sameWindow(a: string | undefined, b: string | undefined): boolean {
  if (a === undefined || b === undefined) return a === b
  return Math.abs(Date.parse(a) - Date.parse(b)) < SAME_WINDOW_MS
}

// adds a reading to a window's history; a new window (its reset time moved) starts afresh
export function record(prev: History | undefined, limit: SessionRateLimit, now: number, keepMs: number): History {
  const kept = prev !== undefined && sameWindow(prev.resetsAt, limit.resetsAt) ? prev.samples : []
  const samples = [...kept, { t: now, p: limit.percentUsed }].filter(s => now - s.t <= keepMs)
  return { resetsAt: limit.resetsAt, samples }
}

// percentage points per hour across the samples; undefined while the history is too short
export function burnRate(samples: readonly Sample[]): number | undefined {
  const first = samples[0]
  const last = samples[samples.length - 1]
  if (first === undefined || last === undefined || last.t - first.t < MIN_SPAN_MS) return undefined
  return ((last.p - first.p) / (last.t - first.t)) * HOUR
}

// the pace a window is judged by, in points per hour: the weekly window by its own average
// so far (nights and weekends included), the others by the recent rolling rate
export function pace(limit: SessionRateLimit, samples: readonly Sample[], now: number): number | undefined {
  if (limit.kind === 'seven_day') {
    if (limit.resetsAt === undefined) return undefined
    const elapsed = now - (Date.parse(limit.resetsAt) - WEEK_MS)
    return elapsed >= MIN_WEEK_ELAPSED_MS ? (limit.percentUsed / elapsed) * HOUR : undefined
  }
  return burnRate(samples)
}

// "+38%/h", or per day for the weekly window; undefined when too small to matter
export function rateText(kind: string, rate: number | undefined): string | undefined {
  if (rate === undefined) return undefined
  if (kind === 'seven_day') return rate * 24 >= 1 ? `+${Math.round(rate * 24)}%/d` : undefined
  return rate >= 1 ? `+${Math.round(rate)}%/h` : undefined
}

// how long until the window hits 100% at this pace, when that comes before it resets
export function runsOutIn(limit: SessionRateLimit, rate: number | undefined, now: number): number | undefined {
  if (rateText(limit.kind, rate) === undefined || limit.percentUsed >= 100) return undefined
  const outIn = ((100 - limit.percentUsed) / rate!) * HOUR
  const resetIn = limit.resetsAt === undefined ? Infinity : Date.parse(limit.resetsAt) - now
  return outIn < resetIn ? outIn : undefined
}

export function hasReset(limit: SessionRateLimit, now: number): boolean {
  return limit.resetsAt !== undefined && Date.parse(limit.resetsAt) <= now
}

export function formatLimit(limit: SessionRateLimit, now: number, rate?: number): string {
  const label = LABELS[limit.kind] ?? limit.kind
  // readings only arrive with a response, so an idle session's last one can outlive its window
  if (hasReset(limit, now)) return `${label} reset`
  let text = `${label} ${Math.round(limit.percentUsed)}%`
  const shown = rateText(limit.kind, rate)
  if (shown !== undefined) text += ` ${shown}`
  const out = runsOutIn(limit, rate, now)
  if (out !== undefined) return `⚠ ${text} out in ${duration(out)}`
  return limit.resetsAt === undefined ? text : `${text} (resets ${duration(Date.parse(limit.resetsAt) - now)})`
}

export type Drops = { count: number; tokens: number }

// 955492 -> 955K, 1900000 -> 1.9M
export function tokens(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : `${Math.round(n / 1000)}K`
}

// the line's parts, before the cache drops
export function usageParts(
  usage: Omit<SessionUsage, 'startedAt'>,
  now: number,
  rates: ReadonlyMap<string, number | undefined> = new Map(),
): string[] {
  const parts = usage.rateLimits.map(l => formatLimit(l, now, rates.get(l.kind)))
  if (parts.length === 0) parts.push('limits: no reading yet')
  if (usage.context.percent !== undefined) parts.push(`ctx ${Math.round(usage.context.percent)}%`)
  if (usage.cost !== undefined) parts.push(`$${usage.cost.usd.toFixed(2)}`)
  return parts
}

// "cache drops 3 (1.9M)" appended, or nothing while there are none
export function withDrops(parts: readonly string[], drops: Drops): string[] {
  return drops.count > 0 ? [...parts, `cache drops ${drops.count} (${tokens(drops.tokens)})`] : [...parts]
}

export function formatUsage(
  usage: Omit<SessionUsage, 'startedAt'>,
  now: number,
  rates: ReadonlyMap<string, number | undefined> = new Map(),
  drops: Drops = { count: 0, tokens: 0 },
): string {
  return withDrops(usageParts(usage, now, rates), drops).join(' · ')
}

// the tokens a request rebuilt when it is a cache drop, else undefined: not the agent's
// first request (`prevAt` undefined), more than four minutes since its previous request
// started, a context of 100K or more, and at least half of it written to the cache afresh
export function cacheDrop(prevAt: number | undefined, now: number, usage: ModelUsage): number | undefined {
  if (prevAt === undefined || now - prevAt <= DROP_MIN_GAP_MS) return undefined
  const context = usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
  if (context < DROP_MIN_CONTEXT || usage.cache_creation_input_tokens < context * DROP_SHARE) return undefined
  return usage.cache_creation_input_tokens
}

// the line as runs of text: each part marked ⚠ a warning run of its own, the other
// parts and the separators merged into dim runs
export type Run = { text: string; isWarning: boolean }
export function runs(parts: readonly string[]): Run[] {
  const out: Run[] = []
  parts.forEach((part, i) => {
    const pieces: Run[] = i > 0 ? [{ text: ' · ', isWarning: false }] : []
    pieces.push({ text: part, isWarning: part.startsWith('⚠') })
    for (const piece of pieces) {
      const last = out[out.length - 1]
      if (last !== undefined && !last.isWarning && !piece.isWarning) last.text += piece.text
      else out.push({ ...piece })
    }
  })
  return out
}

// whether no surface the session draws on raises a band (or nothing draws at all, as
// under -p or an SDK host), so the line goes out as a status instead; a phone or IDE
// attached beside a terminal goes without, so the terminal keeps its quiet band alone
export function needsStatus(surfaces: readonly string[]): boolean {
  return !surfaces.some(s => BAND_SURFACES.includes(s))
}

// a configured number, or the default when unset or not a number, held within bounds
export function setting(value: unknown, fallback: number, min: number, max: number): number {
  const n = Number(value ?? fallback)
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback
}

// module state, which a reload starts over: the cache drops so far, when each agent's
// last request started, the line's parts before the drops, and the line the band draws
let drops: Drops = { count: 0, tokens: 0 }
const lastStepAt = new Map<string, number>()
let base: string[] | undefined
let line: string[] | undefined

// the band draws the line where it is raised; the status carries it where it is not
async function show($: EngineInterface, parts: string[]) {
  base = parts
  const shown = withDrops(parts, drops)
  if (line === undefined || line.join(' · ') !== shown.join(' · ')) {
    line = shown
    $.ui.invalidate('ui.render')
  }
  $.ui.status(needsStatus(await $.session.surfaces()) ? shown.join(' · ') : undefined)
}

async function reshow($: EngineInterface) {
  if (base !== undefined) await show($, base)
}

export const register: Register = (on, options) => {
  const warnAt = setting(options.warnAtPercent, 90, 1, 100)
  const rateWindowMs = setting(options.rateWindowMinutes, 30, 10, 300) * 60_000
  const history = new Map<string, History>()
  // one toast per window per reset per reason
  const toasted = new Set<string>()
  const rates = (limits: readonly SessionRateLimit[], now: number) => {
    const out = new Map<string, number | undefined>()
    for (const limit of limits) {
      if (hasReset(limit, now)) {
        history.delete(limit.kind)
        continue
      }
      const h = record(history.get(limit.kind), limit, now, rateWindowMs)
      history.set(limit.kind, h)
      out.set(limit.kind, pace(limit, h.samples, now))
    }
    return out
  }

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    const tick = async () => {
      try {
        const now = await $.clock.now()
        const usage = await $.session.usage()
        await show($, usageParts(usage, now, rates(usage.rateLimits, now)))
      } catch {
        // the next tick or measurement draws it again
      }
    }
    await tick()
    // keep the countdowns and rates moving between turns
    $.clock.every(60_000, tick)
    return result
  })

  on('session.end', { reason: 'clear' }, async ($, e, next) => {
    drops = { count: 0, tokens: 0 }
    lastStepAt.clear()
    await reshow($)
    return next(e)
  })

  // every model request of the main loop, a subagent or an in-process teammate
  on('turn.step', async function* ($, e, next) {
    const at = await $.clock.now()
    const result = yield* next(e)
    // a request that got no response read and wrote no cache
    if (result.usage === null) return result
    const id = e.agentId ?? 'main'
    const rebuilt = cacheDrop(lastStepAt.get(id), at, result.usage)
    lastStepAt.set(id, at)
    if (rebuilt !== undefined) {
      drops = { count: drops.count + 1, tokens: drops.tokens + rebuilt }
      await reshow($)
    }
    return result
  })

  on('session.measure', async ($, e, next) => {
    const now = await $.clock.now()
    const r = rates(e.rateLimits, now)
    await show($, usageParts(e, now, r))
    for (const limit of e.rateLimits) {
      if (hasReset(limit, now)) continue
      const window = `${limit.kind}:${limit.resetsAt ?? ''}`
      const label = LABELS[limit.kind] ?? limit.kind
      const out = runsOutIn(limit, r.get(limit.kind), now)
      if (out !== undefined && !toasted.has(`${window}:pace`)) {
        toasted.add(`${window}:pace`)
        $.ui.toast(`At this pace the ${label} limit runs out in ${duration(out)}, before it resets`)
      }
      if (limit.percentUsed >= warnAt && !toasted.has(`${window}:warn`)) {
        toasted.add(`${window}:warn`)
        $.ui.toast(`Usage: ${formatLimit(limit, now, r.get(limit.kind))}`)
      }
    }
    return next(e)
  })

  // a phone or an IDE joining or leaving changes whether the status is needed
  on('session.attach', async ($, e, next) => {
    const result = await next(e)
    await reshow($)
    return result
  })
  on('session.detach', async ($, e, next) => {
    const result = await next(e)
    await reshow($)
    return result
  })

  // one dim line in the band above the prompt, under what the plugins beneath drew;
  // only the parts marked ⚠ take the warning color
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const below = await next(e)
    if (e.props.hasSurvey || line === undefined) return below
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {below}
        <Text wrap="truncate-end">
          {runs(line).map(r => (r.isWarning ? <Text color="warning">{r.text}</Text> : <Text dimColor>{r.text}</Text>))}
        </Text>
      </Box>
    )
  })
}
