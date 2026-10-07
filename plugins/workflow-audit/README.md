# workflow-audit

An honest audit of how you use Claude Code, built from your own transcripts rather than from what you believe about yourself.

Most people think they use AI tools better than they do. In METR's 2025 trial, experienced developers believed AI made them 20% faster and were measured 19% slower. You can't fix what you can't see, and you can't see your own habits from inside a session.

Run `/workflow-audit` in a fresh session. It reads your local transcripts, measures what happened, checks it against current advice from Anthropic's docs and staff, and writes a short report: at most five findings, ranked by what they cost you, each with one experiment to try for two weeks. The next run tells you whether the experiment worked.

## What it measures

- **Cost you can avoid.** Prompt-cache breaks and what caused them (idle gaps, model switches, compaction, subagents woken up after their cache expired), priced at list rates. Subagents that inherited an expensive model because nobody set one. Subagents that grew too large. Before it recommends a fix, it prices the fix: some obvious ones cost more than they save.
- **Rework.** How often you correct Claude, and runs of corrections in a row. A few of the worst sessions are read by subagents to say whose side the problem was on: an unclear ask, a rule Claude already had and ignored, Claude simply being wrong, or you changing your mind.
- **Context weight.** How many lines of CLAUDE.md load into every turn, per project.
- **Verification.** Whether a test, build or lint ran after the last edit.
- **Practices.** Permission modes, plan mode, worktrees, skills, slash commands, measured against the catalog, which records who gave each piece of advice, when, for which model, and whether it has since been reversed.

If you have run `/insights` recently, it uses that data as a cross-check. It doesn't need it.

## What it won't tell you

Whether you are faster or more productive. Transcripts can't measure that, and the research says self-reports can't either. It also gives no score. A score invites comparison and gaming; a ranked list of what to change does not.

## Privacy

Everything runs locally. A Python script reads `~/.claude/projects` and writes to `~/.claude/workflow-audit/`. The report stays on your machine. The only data that reaches a model is what any Claude Code session sends: the compact metrics and a few short excerpts around your corrections, with secret-looking strings redacted.

It keeps nothing longer than Claude Code keeps your transcripts. Claude Code deletes them after `cleanupPeriodDays` (30 unless you've set it). On every run the audit:

- drops cached data for any transcript Claude Code has deleted;
- deletes the excerpt files (`samples/`) of runs older than that period.

What stays in each run folder is the report, the metrics, the experiments you chose, and the sample verdicts. Those contain short quotes of at most 15 words, kept because the next run compares against them and because the report is your record. Deleting `~/.claude/workflow-audit/` removes all of it.

## Requirements

Python 3.9 or newer, standard library only. Nothing to `pip install`.

## Install

```
/plugin marketplace add AbhiramDwivedi/claude-ops
/plugin install workflow-audit@claude-ops
```

The advice catalog changes as models and Claude Code change. To get updates automatically, run `/plugin`, open **Marketplaces**, select claude-ops and choose **Enable auto-update**. It is off by default for marketplaces outside Anthropic's own.

## Cost of a run

The measurement is free: a script, about 10 seconds the first time and about a second after that. The report uses a few subagent reads of excerpts on Sonnet and one review pass on Opus, roughly 150K to 300K tokens in all. Run it in its own session, about once a month.
