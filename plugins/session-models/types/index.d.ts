// what the mod has seen of one agent ('main', or a subagent or teammate id)
export type AgentSeen = {
  // the model id its latest request called; absent in state from before 0.5.0
  model?: string
  // tokens its latest request carried: input plus cache reads and writes
  context: number
  // the effort its latest request asked for: a level or an integer budget; absent
  // for a model that takes none
  effort?: string | number
}

export type AgentsSeen = Record<string, AgentSeen>

declare module 'claude-code' {
  interface PluginState {
    'session-models': { agents: AgentsSeen }
  }
}
