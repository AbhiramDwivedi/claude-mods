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
- **Advice is dated.** Use the catalog's `status`. Never report a `superseded` practice as a gap (e.g. zero plan mode use is not a gap on current models). Report a `contested` practice as a choice with its trade-off, not as a mistake. Absence of a practice is never a gap on its own; the data has to show the failure the advice is meant to prevent.
- **Price the fix before recommending it.** If a metric has a what-if (for example a longer subagent cache TTL), use it. A fix that costs more than it saves is not a recommendation.
- **User or model.** A correction can mean the ask was unclear, Claude ignored an existing rule, Claude was simply wrong, or the person changed their mind. Say which the samples show. Don't blame the person for the model, or the model for the person.
- **Write like Zinsser** (*On Writing Well*): clear, simple, brief, human. Lead with the point. Cut every word that does no work. Short plain words, active verbs, numbers over adjectives. No qualifiers ("quite", "somewhat", "a bit"), no jargon where a plain word works, one idea per sentence.
- **Only the audit.** Leave out anything the metrics and samples don't cover: connector or MCP status, setup tips, unrelated observations about the environment. A command a finding's catalog entry suggests (step 5) is part of the audit; a general "did you know" tip is not.

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

`metrics.samples` lists excerpt files of the sessions with the most corrections. Have them read in parallel by subagents, `model: "sonnet"`, at most five, one or two files each. Start them all in one message, in the foreground (`run_in_background: false`), and wait for their answers before going on. Never schedule a wakeup or a timer during the audit (no ScheduleWakeup, no CronCreate, no sleep loops). The readers take a minute or two, and in a non-interactive run a pending wakeup keeps the process alive long after the report is done. Give each reader this brief, filled in:

> Read these files: <paths>. Each holds moments a word pattern flagged as possible corrections: Claude's message just before, then the person's message. Many are not corrections at all (an ordinary instruction that happens to contain "don't" or "actually"). For each moment, classify it as exactly one of `not_a_correction`, `unclear_ask` (the request could reasonably be read the way Claude read it), `ignored_rule` (an instruction in these CLAUDE.md files covers it: <paths and mtimes from metrics.context.claude_md>), `claude_wrong` (clear ask, Claude got it wrong), `out_of_scope` (Claude changed or added things the person didn't ask for), `changed_mind` (the person changed the goal), or `other`. You can only see each file as it is today. For `ignored_rule`, set `in_force` to `true` when the moment is dated after that file's last change (so the rule was certainly there), otherwise `"unknown"`. Return JSON only: `[{"file": ..., "session8": ..., "date": ..., "moment": <n>, "cause": ..., "in_force": <true|"unknown"|null>, "evidence": "<= 15-word quote", "rule": "<the CLAUDE.md line if ignored_rule, else null>"}]`. Do not write files.

If you can't start subagents, read the files yourself.

The sample readers' verdicts are the real correction count. Report the share of flagged moments that were real corrections, and the causes among those. Count `ignored_rule` only where `in_force` is true, and list the unknown ones separately as "rule exists now, may not have then". This applies to every total you derive too, the headline count of real corrections included: a sum such as "N real corrections" or "N were on Claude's side" includes only confirmed ignored rules, and states the unknowns next to it. Use `rework.correction_rate` for its trend and by-project spread, not as an exact count: the word patterns are imprecise (`precision_note`).

Save the verdicts as `<run dir>/sample-verdicts.json`. If an earlier run dir under `~/.claude/workflow-audit/runs/` has a `sample-verdicts.json`, compare: the share of flagged moments that were real corrections, and the count of each cause. That comparison, not the word-pattern rate, is how a correction experiment is judged. Compare rates, never raw counts, because each run samples a different number of sessions and moments: a cause's count per flagged moment, and per sampled session. Set targets the same way, for example "Claude-wrong moments: 12 of 55 flagged (0.22) → under 0.11". The samples are the worst sessions, not a random draw, so say that next to any comparison. Readers also disagree with each other: on the same data, two runs' cause counts have differed by about 3 in 55 moments. If an earlier run covered mostly the same window, use the difference between its verdicts and yours as the noise estimate. Set a target only if the change it asks for is clearly bigger than that noise, and say how big the noise is.

### 5. Choose the findings

Collect candidates from every area of `metrics.json`: cost (cache waste and its causes, inherited agent models, agent size, model mix), rework (correction rate, streaks, /insights friction), context (CLAUDE.md weight), verification, practices. Skip any metric marked `insufficient`.

Read each metric for what it can and can't show:

- `verification.check_after_last_edit` recognises common test, build and lint commands and a project's own check scripts only. A session that checked its work another way (a browser, the person looking at it) counts as unchecked. Treat a low share as a question to put to the person, with the session list, not as proof. Its denominator is sessions that edited files. Don't quote `share_with_no_check_command`, which counts sessions that edited nothing.
- `context.claude_md` counts lines the way Claude Code loads them: `@imports` included, and AGENTS.md when a folder has no CLAUDE.md. A project in `missing_cwds` has moved or been renamed since, so its files couldn't be read. Never report such a project as having no CLAUDE.md.
- Cost percentages are at list prices. On a subscription they show where usage limits go, not a bill.
- Unattended sessions (no human messages, or `claude -p`) count toward cost but not toward behaviour metrics. Say in the opening line what share of spend they are (`cost.total.by_kind`). `cost.cache.waste_pct_by_kind` is the waste rate within each kind (waste over that kind's own cost). Whether a finding comes mostly from unattended runs shows in the `kind` and `share_of_waste` of `cost.cache.top_sessions`. When it does, the finding is about a harness or pipeline, not a daily habit: say so and aim the fix there.
- **Concentration.** When one session supplies more than half of a finding's number (`share_of_waste` in `cost.cache.top_sessions`, or the examples list), put that in the finding's first line and describe what that session was. A habit is something that shows up across many sessions; one bad day isn't one.
- **Known change dates.** If something that changes behaviour was installed or changed inside the window (`meta.plugins_installed`, CLAUDE.md `mtime` in `context.claude_md`, a jump in a per-week series such as `agents.explicit_model_rate` or `agents.size.by_week`), split the numbers before and after that date instead of hedging. Base the finding on the "after" numbers when there are enough of them, and say how many there are.
- `permissions.denials` counts every session, unattended ones too (`by_session_kind`). Triage by `by_shape`: repeated `read_only` commands are what `/fewer-permission-prompts` fixes; `chained`, `absolute_path` and `inline_interpreter` usually mean an allowed command was written in a shape the allowlist doesn't match, so the fix is an instruction about how to write commands, not a new rule. Never suggest allowing a whole interpreter, shell or network tool. `classifier_reasons` are auto mode doing its job; they are a finding only when the same block repeats on work the person wanted done.
- `verification.review_after_edits` can't see a person reading the diff themselves. An unreviewed long run is a question for the person, not proof, unless later corrections or reverts in the same work show the cost.
- `effort.by_model` describes; it doesn't grade. Read it against `match-effort-to-task` per model.
- `practices.usage.commands_used` lists slash commands with a leading `/` and skills without one, sometimes with a `plugin:` prefix. Match a suggestion's name against both forms.
- **Correction experiments.** Never set an experiment target on `rework.correction_rate`. Its word patterns are too imprecise to grade anyone by. Judge correction experiments by comparing sample verdicts between runs (step 4). Give that experiment `"metric": "sample-verdicts"` and no `path`; the script will report it as unresolved, and you compare it yourself.

Rank them by what they cost the person: a share of spend for cost findings, and how many sessions it touched and how badly for rework findings. Keep **at most five**. Three strong findings beat five padded ones.

For each finding, write:

1. **A title that states the problem plainly**, e.g. "Idle subagents re-cache their whole context: 9.7% of your spend".
2. **What the data shows**: the numbers with n, the worst sessions (8-character id, project, date), and the sample causes if they apply.
3. **What current advice says**: the catalog entry's claim, its source and date, and its grade (`measured`, `anthropic-advice`, `anthropic-staff` or `opinion`), in one line. Where an `anthropic-staff` post and the docs disagree, the catalog has already sided with the newer post; follow its `status`.
4. **The fix, with its price.** The fix has to fit every session you cite as evidence. If a cited session is in another project or doing different work, drop it from the list or say the fix doesn't cover it. Before you call a CLAUDE.md section boilerplate the catalog warns against, quote it and check it really is that (a generic "verify your work" nudge is; a rule about what to report to the person is not). Use the matching what-if in `cost.cache.what_if` (for example `fresh_instead_of_resume` when the advice is "start a fresh subagent instead of messaging an idle one"), with its assumption. If no what-if prices a cost fix, say the fix is unpriced. Don't say it "pays".
5. **The tool that helps**, only when the entry has `suggest`: name the official command, skill or plugin, what it does in one short sentence, and its link. Skip any the person already uses (`practices.usage.commands_used`, `meta.plugins_installed`). At most two per finding. Leave the line out when nothing is left.
6. **One experiment**: a change to try for two weeks and the metric that will show whether it worked, with today's value and a target. Use a real key from `metrics.json`.

### 6. Check the draft before showing it

Start one fresh subagent with `model: "opus"`. Give it the draft report and the path to `metrics.json`, and ask it to list every sentence that flatters, softens a problem, or claims something the metrics or samples don't show, every number that doesn't match `metrics.json`, and every sentence that breaks Zinsser's rules (clutter, qualifiers, jargon, passive voice where active works, a buried point). Fix what it finds. If you can't start a subagent, do this pass yourself, line by line.

### 7. Save and show

Write `<run dir>/report.md` and `<run dir>/proposed-experiments.json`: one entry per experiment in the report, in the format in this plugin's `CONTRACT.md`, with `metrics_version` copied from `metrics.meta.metrics_version`. Then show the person the report in chat, and give them the path. Never publish or upload it; it describes their private work.

### 8. Let the person choose what to commit to

An experiment is the person's commitment, not yours. The next audit grades them on whatever is in `experiments.json`, so only they decide what goes in it.

Ask with AskUserQuestion, `multiSelect: true`: one option per proposed experiment, labelled with the change and its target, plus the automatic "Other" for adjusting a target. Write `<run dir>/experiments.json` with only the ones they pick, using the targets they set. If they pick none, write nothing.

If AskUserQuestion isn't available or fails (a non-interactive run such as `claude -p`), don't write `experiments.json`, and don't ask in plain text either: in a non-interactive run nobody can answer. Your final message is then the full report, ending with a line saying nothing was committed and the next interactive run will offer the proposals again. A non-interactive run only prints its final message, so anything that isn't in that message is lost.

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
