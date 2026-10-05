# pit-stop

Keeps subagents small. The main agent still decides how work is split. This mod tells it how to split well, watches each subagent's context, and steps in when one grows too large.

- It adds a short section to the main agent's system prompt with the rules for sizing and splitting work.
- It adds a context budget to every subagent's brief: read files by line range, keep output short, and write a handoff note when asked to checkpoint.
- When a subagent's requests carry `nudgeAtK` thousand tokens of context, it asks the agent to finish its current item and checkpoint.
- Past `stopAtK`, the agent gets 8 more tool calls to commit and write its note, and then every tool call is refused.
- When a subagent waits over 4 minutes on one of its own tool calls and its next request rebuilds most of a large context (100K tokens or more), its prompt cache expired. The mod shows you a toast and tells that agent once, with the measured size and pause, so it checks on long jobs sooner. Agents whose caches never expire never see it.
- It ships the `pit-stop:split-work` skill, with templates for briefs and handoff notes.

| Setting | Default | What it does |
| --- | --- | --- |
| `nudgeAtK` | 300 | Asks a subagent to checkpoint when its requests carry this many thousand tokens of context. |
| `stopAtK` | 450 | Gives a subagent 8 tool calls to checkpoint past this many thousand tokens, then refuses its tools. Always at least 50 above `nudgeAtK`. |
| `cacheNotes` | true | Tells a subagent once when its prompt cache expired during a long pause. Off: only you get the toast. |

The [main README](../../README.md) covers installing, why the limits sit where they do, and what it can't see.
