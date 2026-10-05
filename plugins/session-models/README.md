# session-models

Shows which models your session's agents run on and how many are running now. Agents include the main thread, subagents and teammates that run inside the session. It warns when too many run at once, or when one sends a huge context with every request.

```
model: Opus · agents: Opus (14, 13 live), Sonnet (2) · ⚠ 14 live · ⚠ ctx 910K
```

The line is dim. Only the warnings marked ⚠ are drawn in the warning color. The line sits in the band above the prompt, alongside any other plugin's line there; collapse the band with its `[-]` or ctrl+x ctrl+a. In the VS Code extension and on a phone, which have no band, the line falls back to the plugin status line. That status shows everywhere, in its usual yellow, while such a surface is attached.

| Setting | Default | What it does |
| --- | --- | --- |
| `liveAgentsWarn` | 6 | Warns when this many agents run at once, counting the main thread. |
| `contextWarnK` | 300 | Warns when a running agent sends this many thousand tokens of context per request. |

The [main README](../../README.md) covers installing, reading the line, and what it can't see.
