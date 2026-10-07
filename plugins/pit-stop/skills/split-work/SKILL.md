---
name: split-work
description: How to size and split work across subagents so no single agent grows huge. Use before starting any subagent or teammate for multi-step work, when planning parallel builders, when a subagent's report starts with "CHECKPOINT:", or when the person asks whether agents are sized well or why a session burns tokens.
---

# Split work across agents

You decide how work is split. The pit-stop plugin measures each subagent's context and enforces two limits: at the first it asks the agent to checkpoint, and past the second it refuses the agent's tools. Those limits are a backstop for a bad split. A good split never reaches them.

## Why size matters

Every request an agent makes re-sends its whole context. An agent's cost therefore grows with the square of its length. In one measured session of 26 subagents, the typical agent started near 47K tokens of context and read about 200K more before its first edit. The largest peaked near 770K. The long ones did most of the spending.

Two things cut that cost. The first is ending agents before they grow large. The second, which matters more, is making a fresh agent cheap to start, so that handing off costs little.

## Choose the shape

1. **One agent** fits a job with one goal that touches a few files and that you could describe in a short paragraph.
2. **Parallel agents** fit independent jobs that edit different files. Check the file lists before you start them. Two agents editing the same file will collide.
3. **A relay** fits a large job whose parts touch the same files. One fresh agent does one phase, commits, and writes a handoff note. The next fresh agent starts from that note. Run the legs one after another.

A job is too big for one agent when it has more than about three separate items, when it spans the largest or busiest files, or when its scope is open-ended ("fix whatever you find"). Split it into phases before you start anything.

## Write a brief that is cheap to start from

Most of a fresh agent's cost is orientation. A precise brief replaces exploration. Include each of these:

- The goal in one or two sentences, and what done means.
- The exact files, functions and line ranges to read first. Name what it should not read.
- The commands that check the work, such as the test command and the linter, and how to keep their output short.
- The boundary: what is out of scope, and what to do if the job turns out bigger than described.
- Where to write the handoff note, if it has to stop early. A file in the repo, such as `docs/handoff/<phase>.md`, keeps your own context small.
- The model, set with the Agent tool's `model` parameter. See "Pick the model" below.

Do not paste large file contents or long history into a brief. Point to files and line ranges instead.

## Pick the model

Choose a model for each agent from its job, not from the session's model.

- Use a stronger model, such as `opus`, for judgment: design, debugging, review, and tricky code.
- Use a cheaper model, such as `sonnet`, for mechanical, search, bulk, or fully specified work. A brief precise enough to follow step by step usually needs no more.

Leaving `model` unset runs the agent on the default subagent model. Unless the person has set one, that is your own model, which may be the most expensive one available. If the person asks how to stop this, they can set a fallback in the `env` block of `~/.claude/settings.json`:

```json
{ "env": { "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet" } }
```

That covers agents started without a model. Keep setting `model` on each call anyway, because the right model depends on the job.

## Handle a CHECKPOINT report

A final report that starts with "CHECKPOINT:" means the agent stopped on purpose with work left. Do not resume that agent, because it would carry its whole context forward. Do this instead:

1. Read only the report and the handoff note. Do not re-read the files yourself.
2. Decide whether the remaining work is one phase or several. Split it again if needed.
3. Start a fresh agent whose brief is the handoff note's read list and its numbered remaining items, plus your boundary and test commands.

## A good handoff note

- What is done and verified, with commit ids and real test counts.
- What is left, as a numbered list. Each item names the files and functions it touches.
- Traps found along the way, such as a misleading name or a test that only passes in isolation.
- The read list: exactly which files and line ranges the next agent should read first, and nothing more.

## Keep the main thread thin

Your own context is re-sent on every turn too. Ask agents for conclusions, not file dumps. Read their reports, not their transcripts. Avoid reading whole files yourself when an agent is already working in them.
