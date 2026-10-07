# ctx-study

A weekly check on how large Claude Code subagents get, and whether the subagent-limits handoffs work.

It reads the subagent transcripts under `~/.claude/projects/<project>/<session>/subagents/agent-*.jsonl` and never writes there. Forks (`isFork` in the `.meta.json`) are left out of every number. It measures:

- context at each agent's first request, at its first Edit/Write (R_edit), and at its peak
- how many agents pass each limit, and what share of weighted cost (`input + 1.25 cache_write + 0.1 cache_read + 5 output`) went to requests above it
- cache-expiry rewrites: requests after an agent's first whose cache write is at least half its context
- subagent-limits activity: briefs carrying the contract, nudges, wind-down notes, refusals, final reports starting with `CHECKPOINT:`, and predecessor-to-successor pairs
- the re-orientation fraction: a successor's growth before its first edit, divided by the median for other agents
- a what-if simulation of the cost change at limits of 200K to 450K, and a verdict on the 300K/450K limits

## Run it

Python 3.8 or newer, standard library only.

```
py -3 tools/ctx-study/ctx_study.py              # Windows
python3 tools/ctx-study/ctx_study.py            # macOS, Linux
```

Options: `--since DAYS` (default 7, `0` for all time), `--limits 300,450` (in K tokens), `--projects DIR` (default `~/.claude/projects`), `--out DIR` (default `~/.claude/ctx-study`).

To run it every Monday at 09:00:

```
schtasks /Create /TN ctx-study /SC WEEKLY /D MON /ST 09:00 /TR "C:\Windows\pyw.exe -3 C:\path\to\claude-ops\tools\ctx-study\ctx_study.py"
0 9 * * 1  python3 /path/to/claude-ops/tools/ctx-study/ctx_study.py >/dev/null   # crontab
```

## Output

Everything goes to `--out`:

- `report-YYYY-MM-DD.md`: the report. A run with a window other than 7 days adds a suffix (`-all`, `-30d`), so it doesn't overwrite the weekly one.
- `agents-YYYY-MM-DD.csv`: one row per agent, forks included and flagged.
- `history.csv`: one line per run, appended, to show trends across weeks. Filter by `window_days` when comparing.

The reports contain project names and agent descriptions. That's why they're written to your home directory and not this repo. Don't commit them.

## How subagent-limits is detected

The marker strings come from `plugins/subagent-limits/hooks/register.ts`. If they change there, update them here. Before 0.3.0 the plugin was called pit-stop and tagged its notes `[pit-stop]`; both tags are matched, so older transcripts still count.

- Contract: the agent's brief contains `[subagent-limits] Context budget.`
- Nudge, wind-down and refusal: the note text with a concrete token count, found in anything except the agent's own output. A note whose count is more than 10% above the agent's own peak is treated as a quotation and ignored. That stops an agent that read the mod's source or tests from being counted.
- CHECKPOINT: the agent's last text message starts with `CHECKPOINT:`.
- Successor: a predecessor is an agent that ended with CHECKPOINT or was refused. Its successor is the first non-fork agent in the same parent session that started after the predecessor's last event and whose brief (minus the appended contract) either names the predecessor's agent id, names a note file from its report (a path containing handoff, checkpoint, note or relay), or shares at least three 8-word runs with the report. Each agent can succeed only one predecessor.

## Limitations

- The simulation uses 0.6 as the re-orientation fraction until at least 3 measured pairs exist. Its cost model ignores output tokens.
- The verdict flags the limits when the cheapest simulated limit is more than 50K from 300K. It also prints the rule of thumb (2 x median R_edit), which ignores the cost of handing off and so usually comes out lower.
- When `CLAUDE_CODE_SESSION_ID` is set (the script is run from inside Claude Code), that session's transcripts are skipped. A scheduled run doesn't skip anything, so it includes partly written transcripts from any session still running at the time.
- Only edits made through Edit, Write, MultiEdit and NotebookEdit count as an agent's first edit. Edits made through Bash don't.
