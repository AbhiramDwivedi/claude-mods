# usage-limits

Shows your 5-hour and weekly usage windows in a line above the Claude Code prompt: how much you've used, how fast it's climbing, and when you'll run out if that comes before the reset. It also counts prompt-cache drops.

```
⚠ 5h 41% +38%/h out in 1h33m · 7d 18% +6%/d (resets 4d2h) · ctx 22% · $14.10 · cache drops 3 (1.9M)
```

The line is dim. Only a window marked ⚠, one that runs out before it resets at the current pace, is drawn in the warning color. The line sits in the band above the prompt, alongside any other plugin's line there; collapse the band with its `[-]` or ctrl+x ctrl+a. In the VS Code extension and on a phone, which have no band, the line falls back to the plugin status line. That status shows everywhere, in its usual yellow, while such a surface is attached.

`cache drops 3 (1.9M)` appears after the first drop: 3 requests this session had to rebuild their prompt cache, 1.9M tokens rewritten in all. A request counts when it isn't that agent's first, its context is at least 100K, at least half of the context was written to the cache afresh, and more than 4 minutes passed since the same agent's previous request. That pattern means the cache expired, usually over a long wait; subagents get a 5-minute cache by default. The main thread, subagents and in-process teammates all count. The count starts over on `/clear` and when the plugin reloads.

| Setting | Default | What it does |
| --- | --- | --- |
| `warnAtPercent` | 90 | Toasts once when a window passes this percentage. |
| `rateWindowMinutes` | 30 | Sets how far back the 5-hour burn rate looks (10 to 300). |

The [main README](../../README.md) covers installing, reading the line, and what it can't see.
