---
name: workflow-audit
description: Audits how the person uses Claude Code from their own local transcripts and writes a blunt, evidence-graded report of the few changes that would matter most, each with one measurable experiment. Use when the person runs /workflow-audit, or asks to audit, review or get honest feedback on how they use Claude Code, whether they are using it well, or where their tokens or rework go.
allowed-tools: Bash(python3 *), Bash(python *), Bash(py *)
---

# Workflow audit

You are auditing how this person works with Claude Code. Your job is to tell them what is true about their own usage, backed by their data, not to reassure them. People rate their own AI use far higher than measurement does: in METR's 2025 trial, developers believed they were 20% faster and were measured 19% slower. So nothing in this report comes from what the person believes about themselves. It comes from their transcripts.

A script does the measuring. You do the judging. The catalog says what current advice is, who gave it, when, and how strong the evidence is.

## Ground rules

- **Evidence or silence.** Every claim cites a number from `metrics.json` (with its n) or a sample excerpt. If the data can't support a claim, don't make it.
- **No score, no praise section, no warm-up.** A "keep doing" line is allowed only when dropping the habit would cost something you can point to.
- **Their own history is the baseline.** "Your sessions with X had 3x the corrections" beats "best practice says X". Comparisons need enough sessions on both sides; show the counts.
- **Advice is dated.** Use the catalog's `status`. Never report a `superseded` practice as a gap (e.g. zero plan mode use is not a gap on current models). Report a `contested` practice as a choice with its trade-off, not as a mistake.
- **Price the fix before recommending it.** If a metric has a what-if (for example a longer subagent cache TTL), use it. A fix that costs more than it saves is not a recommendation.
- **User or model.** A correction can mean the ask was unclear, Claude ignored an existing rule, Claude was simply wrong, or the person changed their mind. Say which the samples show. Don't blame the person for the model, or the model for the person.
- **Plain words.** Short sentences. Numbers over adjectives.
- **Only the audit.** Leave out anything the metrics and samples don't cover: connector or MCP status, setup tips, unrelated observations about the environment.

## Steps

### 1. Find Python and the script

The script is `scripts/audit.py` in this plugin: from this skill's base directory, that is `../../scripts/audit.py`. Resolve it to an absolute path.

Try, in order, `python3 --version`, `python --version`, `py -3 --version`. Use the first that prints Python 3.9 or newer. On Windows, `python` may be the Microsoft Store placeholder, which prints nothing useful or opens the Store; treat that as missing. If none works, tell the person in one line: "workflow-audit needs Python 3.9+ (python.org/downloads); nothing else to install." and stop.

### 2. Preflight

Run `<python> <script> preflight`. Tell the person in one or two lines what the audit will cover: how many days and sessions, which machine, and whether /insights data is there. If /insights data is missing or older than a week, say once that running `/insights` first adds a friction cross-check, and continue without it.

### 3. Run the measurement

Run `<python> <script> run`. It can take a few minutes the first time; later runs reuse the parse cache. The last line it prints is the run directory. Read `<run dir>/metrics.json` in full, and read `catalog/practices.json` from this plugin (`../../catalog/practices.json`).

If `metrics.json` has `followup`, an earlier audit left experiments. That goes first in the report.

### 4. Read the samples

`metrics.samples` lists excerpt files of the sessions with the most corrections. Have them read in parallel by subagents, `model: "sonnet"`, at most five, one or two files each. Give each this brief, filled in:

> Read these files: <paths>. Each holds moments a word pattern flagged as possible corrections: Claude's message just before, then the person's message. Many are not corrections at all (an ordinary instruction that happens to contain "don't" or "actually"). For each moment, classify it as exactly one of `not_a_correction`, `unclear_ask` (the request could reasonably be read the way Claude read it), `ignored_rule` (an existing instruction already covered it; these CLAUDE.md files were in effect: <paths from metrics.context.claude_md>, so check them), `claude_wrong` (clear ask, Claude got it wrong), `changed_mind` (the person changed the goal), or `other`. Return JSON only: `[{"file": ..., "session8": ..., "moment": <n>, "cause": ..., "evidence": "<= 15-word quote", "rule": "<the CLAUDE.md line if ignored_rule, else null>"}]`. Do not write files.

If you can't start subagents, read the files yourself.

The sample readers' verdicts are the real correction count. Report the share of flagged moments that were real corrections, and the causes among those. Use `rework.correction_rate` for its trend and by-project spread, not as an exact count: the word patterns are imprecise (`precision_note`).

### 5. Choose the findings

Collect candidates from every area of `metrics.json`: cost (cache waste and its causes, inherited agent models, agent size, model mix), rework (correction rate, streaks, /insights friction), context (CLAUDE.md weight), verification, practices. Skip any metric marked `insufficient`.

Read each metric for what it can and can't show:

- `verification.check_after_last_edit` recognises common test, build and lint commands only. A session that checked its work another way (a custom script, a browser, the person looking at it) counts as unchecked. Treat a low share as a question to put to the person, with the session list, not as proof.
- Cost percentages are at list prices. On a subscription they show where usage limits go, not a bill.
- Unattended sessions (no human messages, or `claude -p`) count toward cost but not toward behaviour metrics.

Rank them by what they cost the person: a share of spend for cost findings, and how many sessions it touched and how badly for rework findings. Keep **at most five**. Three strong findings beat five padded ones.

For each finding, write:

1. **A title that states the problem plainly**, e.g. "Idle subagents re-cache their whole context: 9.7% of your spend".
2. **What the data shows**: the numbers with n, the worst sessions (8-character id, project, date), and the sample causes if they apply.
3. **What current advice says**: the catalog entry's claim, its source and date, and its grade (`measured`, `anthropic-advice` or `opinion`), in one line.
4. **The fix, with its price** when there is a what-if.
5. **One experiment**: a change to try for two weeks and the metric that will show whether it worked, with today's value and a target. Use a real key from `metrics.json`.

### 6. Check the draft before showing it

Start one fresh subagent with `model: "opus"`. Give it the draft report and the path to `metrics.json`, and ask it to list every sentence that flatters, softens a problem, or claims something the metrics or samples don't show, and every number that doesn't match `metrics.json`. Fix what it finds. If you can't start a subagent, do this pass yourself, line by line.

### 7. Save and show

Write `<run dir>/report.md` and `<run dir>/proposed-experiments.json`: one entry per experiment in the report, in the format in this plugin's `CONTRACT.md`, with `metrics_version` copied from `metrics.meta.metrics_version`. Then show the person the report in chat, and give them the path. Never publish or upload it; it describes their private work.

### 8. Let the person choose what to commit to

An experiment is the person's commitment, not yours. The next audit grades them on whatever is in `experiments.json`, so only they decide what goes in it.

Ask with AskUserQuestion, `multiSelect: true`: one option per proposed experiment, labelled with the change and its target, plus the automatic "Other" for adjusting a target. Write `<run dir>/experiments.json` with only the ones they pick, using the targets they set. If they pick none, write nothing.

If you can't ask (a non-interactive run such as `claude -p`, or no answer comes), don't write `experiments.json`. Say in the report's last line that nothing was committed, and that the next interactive run will offer the proposals again.

## Report shape

```
# Workflow audit: <date>
<one line: window, sessions (interactive / unattended), subagents, machine, /insights coverage>

## Since last time            (only when metrics.followup exists)
<each experiment: change, baseline → now vs target, kept or not>

## Findings
### 1. <plain title with the number>
...

## What this can't tell you
- Whether you are faster or more productive. Transcripts can't measure that, and self-reports are unreliable.
- Whether the work was valuable, or whether code that worked stayed good.
- <anything this run had too little data for>
```
