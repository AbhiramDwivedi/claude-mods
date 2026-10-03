// what the mod has seen of one agent ('main', or a subagent or teammate id)
export type AgentSeen = {
  // every model id it has called
  models: string[]
  // tokens its latest request carried: input plus cache reads and writes
  context: number
}

export type AgentsSeen = Record<string, AgentSeen>

declare module 'claude-code' {
  interface PluginState {
    'session-models': { agents: AgentsSeen }
  }
}
