import type { Register, SessionRateLimit, SessionUsage } from 'claude-code'

const HOUR = 3_600_000
const LABELS: Record<string, string> = { five_hour: '5h', seven_day: '7d', spend_limit: 'spend' }
// a rolling rate needs at least this much history before it is shown
const MIN_SPAN_MS = 5 * 60_000
// the weekly pace is the window's own average, once it has run this long
const MIN_WEEK_ELAPSED_MS = 6 * HOUR
const WEEK_MS = 7 * 24 * HOUR
// a resetsAt that moves less than this is the same window, reported again
const SAME_WINDOW_MS = 10 * 60_000

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

export function formatUsage(
  usage: Omit<SessionUsage, 'startedAt'>,
  now: number,
  rates: ReadonlyMap<string, number | undefined> = new Map(),
): string {
  const parts = usage.rateLimits.map(l => formatLimit(l, now, rates.get(l.kind)))
  if (parts.length === 0) parts.push('limits: no reading yet')
  if (usage.context.percent !== undefined) parts.push(`ctx ${Math.round(usage.context.percent)}%`)
  if (usage.cost !== undefined) parts.push(`$${usage.cost.usd.toFixed(2)}`)
  return parts.join(' · ')
}

// a configured number, or the default when unset or not a number, held within bounds
export function setting(value: unknown, fallback: number, min: number, max: number): number {
  const n = Number(value ?? fallback)
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback
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
    const show = async () => {
      try {
        const now = await $.clock.now()
        const usage = await $.session.usage()
        $.ui.status(formatUsage(usage, now, rates(usage.rateLimits, now)))
      } catch {
        // the next tick or measurement draws it again
      }
    }
    await show()
    // keep the countdowns and rates moving between turns
    $.clock.every(60_000, show)
    return result
  })

  on('session.measure', async ($, e, next) => {
    const now = await $.clock.now()
    const r = rates(e.rateLimits, now)
    $.ui.status(formatUsage(e, now, r))
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
}
