# claude-mods

Two [Claude Code](https://claude.com/claude-code) mods that tell you a session is eating your usage limits while you can still stop it, not after you hit the wall.

Each adds a line under the prompt:

```
⚠ 5h 41% +38%/h out in 1h33m · 7d 18% +6%/d (resets 4d2h) · ctx 22% · $14.10
model: Opus · agents: Opus (14, 13 live), Sonnet (2) · ⚠ 14 live · ⚠ ctx 910K
```

[`usage-limits`](plugins/usage-limits) tracks the 5-hour and weekly windows. It shows how much of each you've used, how fast that number is climbing, and when it will hit 100% if that comes before the reset.

[`session-models`](plugins/session-models) tracks the agents in your session: which models they run on, how many are running right now, and how much context each one sends with every request.

## Why I wrote these

I kept running out of limits on a top-tier plan and couldn't see why. When I dug into the transcripts, one session explained most of it, and it wasn't a session where I'd been sloppy.

My global CLAUDE.md tells Claude to hand complex work to subagents. For this job I asked for teams of agents to implement, review and test, and my prompt said to use Opus or Sonnet for them as the work required. I put the main thread on Fable, the most capable and most expensive model, to plan and coordinate while cheaper models did the work. For the first several hours that's what happened. The session started 13 agents in the first hour, and every one had a model picked for its job.

The job ran long, and the conversation was compacted three times. A compaction replaces the conversation with a summary of it. The session kept delegating, as CLAUDE.md said to, but it stopped naming a model when it started an agent. An agent with no model runs on the main thread's model. Mine was Fable, so every new agent ran on Fable too. By the third summary, my line about Opus and Sonnet was gone.

Nothing on screen changed. The work looked the same as before. About two hours later I noticed how fast my usage was climbing and asked whether it was still using Opus and Sonnet agents. It said no: it hadn't set a model, so they had all run on Fable. Two minutes after that I hit the limit.

I hadn't done anything careless. I said the right thing once, at the start, and it wore off over hours of work and three summaries. Claude can't tell which line in a long conversation I still care about unless something keeps saying it, and I couldn't see the switch, because nothing showed which model each agent was running.

The well-behaved first half cost more than I expected too. Those agents ran a long time; the longest made 673 requests over 13 hours. Every request sends the agent's whole context again, and for 11 of the 42 agents that context passed 500K tokens, peaking near 965K. Most of what the session used was the same context read again and again.

Accidents like this happen to careful people. These mods work like the sign before a sharp bend: they don't drive for you, they just tell you what's coming while you can still slow down. With them, a line like `agents: Fable (6, 5 live), Opus (27), Sonnet (1)` would have appeared the minute the switch happened, and the usage line would have shown the 5-hour window climbing and a run-out time well before the wall.

## Install

You need Claude Code 2.1.287 or newer, the first release with mods. The mod API is early access and can change between releases.

```
/plugin marketplace add AbhiramDwivedi/claude-mods
/plugin install usage-limits@claude-mods
/plugin install session-models@claude-mods
```

The mods load when your next session starts.

Each threshold appears as a row in `/config`. You can also set it under `pluginConfigs` in `~/.claude/settings.json`.

| Mod | Setting | Default | What it does |
| --- | --- | --- | --- |
| usage-limits | `warnAtPercent` | 90 | Toasts once when a window passes this percentage. |
| usage-limits | `rateWindowMinutes` | 30 | Sets how far back the 5-hour burn rate looks (10 to 300). |
| session-models | `liveAgentsWarn` | 6 | Warns when this many agents run at once, counting the main thread. |
| session-models | `contextWarnK` | 300 | Warns when a running agent sends this many thousand tokens of context per request. |

Claude Code also has a built-in mod worth turning on alongside these. "You should know" runs a side agent that points out things you or Claude may have missed. Enable it with `/plugin enable cc-plugin-you-should-know@builtin`. It needs a first-party session with telemetry on.

## Reading the usage line

`5h 24% (resets 2h14m)` means you've used 24% of the 5-hour window and it resets in 2 hours 14 minutes.

`+38%/h` is how fast the 5-hour figure has climbed over the last 30 minutes. It appears after 5 minutes of readings, and only when the rate reaches 1% an hour.

`+6%/d` is the weekly window's pace, measured as the average since the week began, nights and weekends included. A busy afternoon would make a 30-minute rate look alarming for a whole week, so this mod doesn't use one. The weekly pace appears 6 hours into the week.

`⚠ 5h 41% +38%/h out in 1h33m` means that at this pace the window runs out in 1 hour 33 minutes, before it resets. A toast fires the first time this happens in each window. Another fires when you pass `warnAtPercent`.

`5h reset` means the last reading's reset time has passed. The next request brings a fresh figure.

`ctx 22%` is how full the main thread's context window is. `$14.10` is the session's cost at API prices, the same figure `/cost` reports.

## Reading the agents line

`model: Opus` is the main thread's model. Until a subagent runs, that's all the line shows.

`agents: Opus (14, 13 live), Sonnet (2)` counts every agent the session has run, by model: the main thread, subagents and teammates that run inside the session. Fourteen have used Opus and 13 of those are running now. An agent that switched models counts under each. An agent started without a model runs on the main thread's model, so if your main thread's model shows up here when you meant the work to go to cheaper ones, that's the sign.

`⚠ 14 live` appears while at least `liveAgentsWarn` agents are running. The toast fires once. It fires again only after the count drops 2 below the threshold, and never twice within 10 minutes.

`⚠ ctx 910K` is the largest context any running agent sent with its last request. The agent pays for that context again on every request, so a handful at this size will drain a window fast. Each agent gets one toast when it first crosses `contextWarnK`.

## Limitations

The limit figures come from this session's own API responses. Your windows are shared by every session you run, but a session only learns the latest numbers when it makes a request. An idle session's line falls behind. The session doing the damage stays current.

Only Claude subscriptions (Pro and Max) report limits. With an API key, the usage line reads `limits: no reading yet`.

Teammates that run in their own terminal or tmux pane don't show up in the lead's count. Each is a separate process with its own copy of the mod. Teammates inside the lead's process are counted.

Burn rate is measured in percent of your window, not tokens. However your plan weighs cached reads, output and different models, the percentage already includes it.

The agent counts reset on `/clear`. They survive a mod reload but not a restart.

## Develop

To run the mods from a clone instead of the marketplace, pass the folders for one session:

```
claude --plugin-dir ./plugins/usage-limits --plugin-dir ./plugins/session-models
```

Or list them in the `env` block of `~/.claude/settings.json`. Separate the paths with `;` on Windows and `:` elsewhere:

```json
{ "env": { "CLAUDE_CODE_PLUGIN_DIRS": "/path/to/claude-mods/plugins/usage-limits:/path/to/claude-mods/plugins/session-models" } }
```

An interactive session watches those folders and reloads a mod when you save a file.

Before you commit:

```
claude plugin validate plugins/usage-limits   # checks the manifest and module as the engine reads them
claude plugin test plugins/usage-limits       # runs tests/*.test.ts
```

When a mod loads, Claude Code writes its API types into the mod's `.claude-plugin/types/` folder, along with a list of the MCP tools on your machine. Git ignores that folder. After the first load, `tsc -p plugins/<mod>` type-checks the mod.

## License

[MIT](LICENSE)
