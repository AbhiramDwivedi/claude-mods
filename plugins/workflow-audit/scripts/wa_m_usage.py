"""sessions.shape, verification.check_after_last_edit, practices.usage."""
import re
import statistics

from wa_common import percentile
from wa_m_rework import messages
from wa_registry import metric, example, insufficient

ACTIVE_GAP_MIN = 10
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")
CHECK = re.compile(
    r"\b(pytest|py\.test|unittest|tox|nox|"
    r"(npm|pnpm|yarn|bun)\s+(run\s+)?(test|build|lint|typecheck|check)\b|jest|vitest|"
    r"tsc|cargo\s+(test|build|check|clippy)|go\s+(test|build|vet)|mvn|gradle|gradlew|make\s+(test|check|lint|build)|"
    r"ruff|flake8|pylint|eslint|mypy|pyright|dotnet\s+(test|build)|"
    r"claude\s+plugin\s+(test|validate)|py_compile|compileall|pre-commit)\b", re.I)
# a project's own check script run by an interpreter: python bin/selftest.py, bash run_tests.sh, node check.mjs
SCRIPT_CHECK = re.compile(
    r"\b(python3?|py(\s+-3)?|node|bun|deno|bash|sh|pwsh|powershell)\s+(-\S+\s+)*\S*?"
    r"(test|tests|check|checks|verify|lint|validate)\w*\.(py|sh|js|mjs|cjs|ts|ps1)\b", re.I)


def active_minutes(s):
    stamps = sorted([r["ts"] for r in s["requests"] if r["ts"]] + [h["ts"] for h in s["humans"] if h["ts"]]
                    + [t["ts"] for t in s["tools"] if t["ts"]])
    total = 0.0
    for a, b in zip(stamps, stamps[1:]):
        gap = (b - a) / 60.0
        if gap <= ACTIVE_GAP_MIN:
            total += gap
    return total


def _med(v):
    return round(statistics.median(v), 1) if v else None


@metric
def sessions_shape(ctx):
    sess = [s for s in ctx.sessions if s["interactive"]]
    if not sess:
        return {"sessions.shape": insufficient("no interactive sessions")}
    hm = [len(messages(s)) for s in sess]
    return {"sessions.shape": {
        "n": len(sess), "interactive": len(sess),
        "active_minutes_median": _med([active_minutes(s) for s in sess]),
        "sessions_with_2plus_compactions": sum(1 for s in sess if len(s["compactions"]) >= 2),
        "human_messages": {"median": _med(hm), "p90": percentile(hm, 90), "max": max(hm)}}}


def is_check(cmd):
    return bool(cmd and (CHECK.search(cmd) or SCRIPT_CHECK.search(cmd)))


@metric
def check_after_last_edit(ctx):
    sess = [s for s in ctx.sessions if s["interactive"]]
    editing, ok, none_at_all, missed = 0, 0, 0, []
    for s in sess:
        tools = s["tools"]
        checks = [i for i, t in enumerate(tools) if t["name"] in SHELL_TOOLS and is_check(t.get("cmd"))]
        if not checks:
            none_at_all += 1
        edits = [i for i, t in enumerate(tools) if t["name"] in EDIT_TOOLS]
        if not edits:
            continue
        editing += 1
        if checks and checks[-1] > edits[-1]:
            ok += 1
        else:
            missed.append((len(edits), s))
    if not editing:
        return {"verification.check_after_last_edit": insufficient("no interactive sessions with file edits",
                                                                   n=0, interactive=len(sess))}
    missed.sort(key=lambda x: -x[0])
    return {"verification.check_after_last_edit": {
        "share": round(ok / editing, 4), "n": editing, "checked_after_last_edit": ok,
        "interactive_sessions": len(sess), "sessions_with_no_check_command": none_at_all,
        "share_with_no_check_command": round(none_at_all / len(sess), 4) if sess else None,
        "top_unchecked": [example(s, "%d edits" % n) for n, s in missed[:10]]}}


def _top(counter, n=10):
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n])


@metric
def practices_usage(ctx):
    sess = [s for s in ctx.sessions if s["interactive"]]
    if not sess:
        return {"practices.usage": insufficient("no interactive sessions")}
    plan_sessions, plan_uses = 0, 0
    modes, skills, cmds = {}, {}, {}
    interrupts = queued = worktree = rejections = 0
    for s in sess:
        entered = sum(1 for _t, m in s["modes"] if m == "plan")
        tool_uses = sum(1 for t in s["tools"] if t["name"] in ("EnterPlanMode", "ExitPlanMode"))
        plan_uses += entered + tool_uses
        plan_sessions += 1 if entered or tool_uses else 0
        for m in {m for _t, m in s["modes"]}:
            modes[m] = modes.get(m, 0) + 1
        interrupts += len(s["interrupts"])
        rejections += len(s["rejections"])
        queued += sum(1 for h in s["humans"] if h["kind"] == "queued")
        for h in s["humans"]:
            if h["kind"] == "command" and h.get("cmd"):
                cmds[h["cmd"]] = cmds.get(h["cmd"], 0) + 1
        for t in s["tools"]:
            if t["name"] == "Skill" and t.get("skill"):
                skills[t["skill"]] = skills.get(t["skill"], 0) + 1
        if any(t["name"] == "EnterWorktree" or (t["name"] in SHELL_TOOLS and re.search(
                r"--worktree\b|git\s+worktree\b", t.get("cmd") or "")) for t in s["tools"]):
            worktree += 1
    return {"practices.usage": {
        "n": len(sess),
        "plan_mode": {"uses": plan_uses, "sessions": plan_sessions},
        "permission_modes": {"sessions_by_mode_seen": _top(modes, 20), "note": "sessions in which each mode appeared"},
        "interrupts": interrupts, "tool_rejections": rejections, "queued_messages": queued,
        "commands": {"/clear": cmds.get("/clear", 0), "/rewind": cmds.get("/rewind", 0),
                     "/compact": cmds.get("/compact", 0)},
        "worktree_sessions": worktree,
        "skills_used": _top(skills), "top_slash_commands": _top(cmds)}}
