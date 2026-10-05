# claude-mods

Three [Claude Code](https://claude.com/claude-code) mods. Two tell you a session is eating your usage limits while you can still stop it, not after you hit the wall. The third keeps subagents from growing large enough to do that.

The first two each add a line under the prompt:

```
⚠ 5h 41% +38%/h out in 1h33m · 7d 18% +6%/d (resets 4d2h) · ctx 22% · $14.10
model: Opus · agents: Opus (14, 13 live), Sonnet (2) · ⚠ 14 live · ⚠ ctx 910K
```

[`usage-limits`](plugins/usage-limits) tracks the 5-hour and weekly windows. It shows how much of each you've used, how fast that number is climbing, and when it will hit 100% if that comes before the reset.

[`session-models`](plugins/session-models) tracks the agents in your session: which models they run on, how many are running right now, and how much context each one sends with every request.

[`pit-stop`](plugins/pit-stop) acts on that last number. It tells the main agent how to size and split work. When a subagent's context grows large, it calls the subagent in for a pit stop: the agent writes a handoff note, and a fresh agent goes back out with it. Past a hard limit it refuses the subagent's tools.

## Why these exist

I built these after a long session burned through my limits while everything on screen looked fine. I had done what the guides say: hand big work to subagents and pick the right model for each. It still got away from me. Here's how that happens.

You start a big job. You tell Claude to split it across subagents, Opus for the hard parts and Sonnet for the rest, and you put a strong model in charge. It goes well. Agents start, finish and report back.

Hours later the conversation has been compacted a few times. Somewhere in a summary, "Opus for the hard parts" became "use agents." New agents start without a model, so they run on whatever the main thread runs on. One agent's job grows from a fix into a whole feature, and every request it makes sends half a million tokens of context. Nothing on screen changes. The main thread looks calm because it is calm. The spending is happening where you aren't looking.

You find out when you hit the wall.

Nobody did anything wrong. Claude followed the instructions it still had, and you gave good ones at the start. Long sessions wear instructions down, and you can't steer by what you can't see.

These mods are the sign before the sharp bend. They don't take the wheel. They tell you what's ahead while you can still brake:

```
⚠ 5h 41% +38%/h out in 1h33m · 7d 18% +6%/d (resets 4d2h) · ctx 22% · $14.10
model: Fable · agents: Fable (6, 5 live), Opus (27), Sonnet (1) · ⚠ ctx 645K
```

Your agents have drifted onto your most expensive model, one of them is carrying a huge context, and at this pace the 5-hour window runs out in an hour and a half. You'd see all of that hours before the wall, while it's still cheap to fix.

pit-stop is the exception. The other two are the gauges and the road signs, and pit-stop is the pit crew. It changes what your agents do, so install it only if you want that.

## Install

You need Claude Code 2.1.287 or newer, the first release with mods. The mod API is early access and can change between releases.

```
/plugin marketplace add AbhiramDwivedi/claude-mods
/plugin install usage-limits@claude-mods
/plugin install session-models@claude-mods
/plugin install pit-stop@claude-mods
```

The mods load when your next session starts.

Each threshold appears as a row in `/config`. You can also set it under `pluginConfigs` in `~/.claude/settings.json`.

| Mod | Setting | Default | What it does |
| --- | --- | --- | --- |
| usage-limits | `warnAtPercent` | 90 | Toasts once when a window passes this percentage. |
| usage-limits | `rateWindowMinutes` | 30 | Sets how far back the 5-hour burn rate looks (10 to 300). |
| session-models | `liveAgentsWarn` | 6 | Warns when this many agents run at once, counting the main thread. |
| session-models | `contextWarnK` | 300 | Warns when a running agent sends this many thousand tokens of context per request. |
| pit-stop | `nudgeAtK` | 300 | Asks a subagent to checkpoint when its requests carry this many thousand tokens of context. |
| pit-stop | `stopAtK` | 450 | Gives a subagent 8 tool calls to checkpoint past this many thousand tokens, then refuses its tools. |

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

## What pit-stop does

session-models shows you an agent carrying a huge context. pit-stop keeps agents from getting there. The main agent still decides how to split the work, because only it knows the task. The mod gives it the rules and enforces two limits.

The main agent gets a short section in its system prompt. It says to give each agent one phase of work and to run agents in parallel only when they edit different files. When they would share files, it says to run a relay instead: one fresh agent per phase, each starting from the last one's handoff note. The `pit-stop:split-work` skill has the longer version, with templates for briefs and handoff notes.

Every subagent's brief gets a context budget added to the end. It asks the agent to read files by line range, keep command output short, and write a handoff note if it is asked to checkpoint.

When a subagent's requests carry `nudgeAtK` thousand tokens of context, its next tool result comes with a note asking it to finish its current item and checkpoint. Past `stopAtK`, it gets 8 more tool calls to commit and write its note, and then every tool call is refused. Its final report starts with `CHECKPOINT:`, which tells the main agent to start a fresh agent from the note rather than resume the old one. A toast tells you each time.

The defaults come from replaying 26 subagents from one long session against different limits. A fresh agent there started near 47K tokens of context and typically read about 200K more before its first edit. Even one that started from a good handoff note read 117K. Low limits therefore cause so many handoffs that they cost more than they save: at 200K the replay used 14% more tokens and took 70% longer. Around 300K it used about a quarter fewer tokens and ran slightly slower. Briefs that cut what a fresh agent reads before it starts work are worth more than any limit. If a fresh agent needed only 40K tokens to get going, a 200K limit would save about half.

## Limitations

The limit figures come from this session's own API responses. Your windows are shared by every session you run, but a session only learns the latest numbers when it makes a request. An idle session's line falls behind. The session doing the damage stays current.

Only Claude subscriptions (Pro and Max) report limits. With an API key, the usage line reads `limits: no reading yet`.

Teammates that run in their own terminal or tmux pane don't show up in the lead's count. Each is a separate process with its own copy of the mod. Teammates inside the lead's process are counted.

Burn rate is measured in percent of your window, not tokens. However your plan weighs cached reads, output and different models, the percentage already includes it.

The agent counts reset on `/clear`. They survive a mod reload but not a restart.

pit-stop never limits the main thread, which Claude Code compacts on its own. It doesn't limit forks either, because a fork starts with its parent's whole context and shares its prompt cache.

pit-stop keeps its counts inside the mod, so a reload starts them over. After one, an agent may be asked to checkpoint a second time, and a fork that is still running loses its exemption.

## Develop

To run the mods from a clone instead of the marketplace, pass the folders for one session:

```
claude --plugin-dir ./plugins/usage-limits --plugin-dir ./plugins/session-models --plugin-dir ./plugins/pit-stop
```

Or list them in the `env` block of `~/.claude/settings.json`. Separate the paths with `;` on Windows and `:` elsewhere:

```json
{ "env": { "CLAUDE_CODE_PLUGIN_DIRS": "/path/to/claude-mods/plugins/usage-limits:/path/to/claude-mods/plugins/session-models:/path/to/claude-mods/plugins/pit-stop" } }
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
