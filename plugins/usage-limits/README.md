# usage-limits

Shows your 5-hour and weekly usage windows under the Claude Code prompt: how much you've used, how fast it's climbing, and when you'll run out if that comes before the reset.

```
⚠ 5h 41% +38%/h out in 1h33m · 7d 18% +6%/d (resets 4d2h) · ctx 22% · $14.10
```

| Setting | Default | What it does |
| --- | --- | --- |
| `warnAtPercent` | 90 | Toasts once when a window passes this percentage. |
| `rateWindowMinutes` | 30 | Sets how far back the 5-hour burn rate looks (10 to 300). |

The [main README](../../README.md) covers installing, reading the line, and what it can't see.
