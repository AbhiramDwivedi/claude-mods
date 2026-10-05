import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AgentsSeen } from '../types'

const agentsSeen = atom({ plugin: 'session-models', key: 'agents' } as const, {} as AgentsSeen)

export type Thresholds = { liveAgents: number; context: number }

// the crowd toast re-arms only once the count drops this far below the threshold,
// and never fires twice within the quiet period
const CROWD_HYSTERESIS = 2
const CROWD_QUIET_MS = 10 * 60_000
// a busy session steps many times a second across its agents: redraw at most this often
const REFRESH_MIN_MS = 2_000

// claude-opus-5-5 -> Opus; an id outside the known families is shown as-is
export function family(model: string): string {
  const m = /(opus|sonnet|haiku|fable)/i.exec(model)
  if (m === null) return model.replace(/^claude-/, '')
  const name = m[1]!.toLowerCase()
  return name[0]!.toUpperCase() + name.slice(1)
}

// 955492 -> 955K, 1200000 -> 1.2M
export function tokens(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : `${Math.round(n / 1000)}K`
}

// the agents running now: the main thread always, plus every running subagent or teammate
export function liveAgents(agents: AgentsSeen, running: ReadonlySet<string>): string[] {
  return Object.keys(agents).filter(id => id === 'main' || running.has(id))
}

// the live agent carrying the most context, when any carries at least `threshold`
export function biggestContext(agents: AgentsSeen, live: readonly string[], threshold: number) {
  let top: { id: string; context: number } | undefined
  for (const id of live) {
    const context = agents[id]?.context ?? 0
    if (context >= threshold && (top === undefined || context > top.context)) top = { id, context }
  }
  return top
}

// "model: Opus · agents: Opus (29, 13 live), Sonnet (4) · ⚠ 14 live · ⚠ ctx 955K"
// the agents part appears once anything beyond the main thread has run;
// an agent that used two families counts under each
export function formatModels(
  current: string,
  agents: AgentsSeen,
  running: ReadonlySet<string>,
  limits: Thresholds,
): string {
  const parts = [`model: ${family(current)}`]
  const live = new Set(liveAgents(agents, running))
  if (Object.keys(agents).some(id => id !== 'main')) {
    const counts = new Map<string, { total: number; live: number }>()
    for (const [id, seen] of Object.entries(agents)) {
      for (const f of new Set(seen.models.map(family))) {
        const c = counts.get(f) ?? { total: 0, live: 0 }
        counts.set(f, { total: c.total + 1, live: c.live + (live.has(id) ? 1 : 0) })
      }
    }
    const list = [...counts]
      .sort((a, b) => b[1].live - a[1].live || b[1].total - a[1].total)
      .map(([f, c]) => (c.live > 0 ? `${f} (${c.total}, ${c.live} live)` : `${f} (${c.total})`))
      .join(', ')
    parts.push(`agents: ${list}`)
  }
  if (live.size >= limits.liveAgents) parts.push(`⚠ ${live.size} live`)
  const top = biggestContext(agents, [...live], limits.context)
  if (top !== undefined) parts.push(`⚠ ctx ${tokens(top.context)}`)
  return parts.join(' · ')
}

export type Crowd = { isArmed: boolean; lastToastAt: number }

// whether this live count earns a crowd toast, and the alarm's next state
export function crowdAlarm(crowd: Crowd, live: number, now: number, threshold: number) {
  if (live < threshold - CROWD_HYSTERESIS) return { toast: false, crowd: { ...crowd, isArmed: true } }
  if (live >= threshold && crowd.isArmed && now - crowd.lastToastAt >= CROWD_QUIET_MS) {
    return { toast: true, crowd: { isArmed: false, lastToastAt: now } }
  }
  return { toast: false, crowd }
}

// an agent by the task it was given, falling back to its id when it has none
export function agentLabel(id: string, description: string | undefined): string {
  if (id === 'main') return 'The main thread'
  return description !== undefined && description !== '' ? description : `Agent ${id.slice(0, 8)}`
}

// a configured number, or the default when unset or not a number, held within bounds
export function setting(value: unknown, fallback: number, min: number, max: number): number {
  const n = Number(value ?? fallback)
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback
}

// module state: a reload starts these over, so a toast may repeat once after one
let crowd: Crowd = { isArmed: true, lastToastAt: -Infinity }
const flaggedContext = new Set<string>()
let lastRefreshAt = -Infinity

async function refresh($: EngineInterface, limits: Thresholds) {
  const now = await $.clock.now()
  lastRefreshAt = now
  const agents = await read($, agentsSeen)
  const listed = await $.agent.list()
  const running = new Set(listed.filter(a => a.status === 'running').map(a => a.id))
  const descriptions = new Map(listed.map(a => [a.id, a.description]))
  $.ui.status(formatModels(await $.session.model(), agents, running, limits))

  const live = liveAgents(agents, running)
  const alarm = crowdAlarm(crowd, live.length, now, limits.liveAgents)
  crowd = alarm.crowd
  if (alarm.toast) $.ui.toast(`${live.length} agents are running at once in this session`)
  for (const id of live) {
    const context = agents[id]?.context ?? 0
    if (context >= limits.context && !flaggedContext.has(id)) {
      flaggedContext.add(id)
      $.ui.toast(`${agentLabel(id, descriptions.get(id))} is re-reading ${tokens(context)} of context on every request`)
    }
  }
}

export const register: Register = (on, options) => {
  const limits: Thresholds = {
    liveAgents: setting(options.liveAgentsWarn, 6, 2, 100),
    context: setting(options.contextWarnK, 300, 10, 10_000) * 1000,
  }

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await refresh($, limits)
    // agents finish between steps: keep the live counts honest
    $.clock.every(15_000, () => refresh($, limits).catch(() => undefined))
    return result
  })

  on('session.end', { reason: 'clear' }, async ($, e, next) => {
    await update($, agentsSeen, () => ({}))
    flaggedContext.clear()
    crowd = { isArmed: true, lastToastAt: -Infinity }
    const result = await next(e)
    await refresh($, limits)
    return result
  })

  // every model request of the main loop, a subagent or an in-process teammate
  on('turn.step', async function* ($, e, next) {
    const result = yield* next(e)
    const usage = result.usage
    // a request that got no response used no model
    if (usage === null) return result
    // the model that actually answered (a fallback may differ from the one asked)
    const model = usage.model
    const id = e.agentId ?? 'main'
    const context = usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens
    // a new agent or model redraws at once; otherwise the throttle decides
    const isNew = !(await read($, agentsSeen))[id]?.models.includes(model)
    await update($, agentsSeen, agents => {
      const seen = agents[id] ?? { models: [], context: 0 }
      return {
        ...agents,
        [id]: { models: seen.models.includes(model) ? seen.models : [...seen.models, model], context },
      }
    })
    if (isNew || (await $.clock.now()) - lastRefreshAt >= REFRESH_MIN_MS) await refresh($, limits)
    return result
  })

  on('classic.PostModelSwitch', async ($, e, next) => {
    const result = await next(e)
    await refresh($, limits)
    return result
  })
}
