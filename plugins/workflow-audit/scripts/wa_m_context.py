"""context.claude_md: how many CLAUDE.md lines each session starts with."""
import os
import re

from wa_common import iso, owner_root
from wa_registry import metric, insufficient

OVER_LINES = 200
PROJECT_FILES = (("CLAUDE.md",), (".claude", "CLAUDE.md"), ("CLAUDE.local.md",))
IMPORT = re.compile(r"^\s*@(\S+)\s*$")
MAX_IMPORT_DEPTH = 5


def count_lines(path, _depth=0, _seen=None):
    """Line count of a text file plus the files it imports with a line of its own like `@AGENTS.md`, the way
    Claude Code loads them; 0 if it is missing or unreadable."""
    seen = _seen if _seen is not None else set()
    key = os.path.normcase(os.path.abspath(path))
    if key in seen:
        return 0
    seen.add(key)
    try:
        with open(path, encoding="utf8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return 0
    total = len(lines)
    if _depth < MAX_IMPORT_DEPTH:
        for line in lines:
            m = IMPORT.match(line)
            if m:
                target = os.path.join(os.path.dirname(path), os.path.expanduser(m.group(1)))
                if os.path.isfile(target):
                    total += count_lines(target, _depth + 1, seen)
    return total


def mtime_iso(path):
    """Last-modified time as ISO UTC, or None."""
    try:
        return iso(os.stat(path).st_mtime)
    except OSError:
        return None


def project_files(cwd):
    """{abs path: {lines, mtime}} for the CLAUDE.md files that exist under cwd."""
    out = {}
    if not cwd:
        return out
    for parts in PROJECT_FILES:
        p = os.path.join(cwd, *parts)
        if os.path.isfile(p):
            out[os.path.abspath(p)] = {"lines": count_lines(p), "mtime": mtime_iso(p)}
    agents = os.path.join(cwd, "AGENTS.md")
    if not os.path.isfile(os.path.join(cwd, "CLAUDE.md")) and os.path.isfile(agents):
        # Claude Code reads AGENTS.md when a folder has no CLAUDE.md (2.1.277 and later)
        out[os.path.abspath(agents)] = {"lines": count_lines(agents), "mtime": mtime_iso(agents)}
    return out


def readable_root(cwd):
    """cwd itself, or for a worktree that has since been cleaned up, the project it belonged to."""
    if not cwd or os.path.isdir(cwd):
        return cwd
    root = owner_root(cwd)
    return root if root and os.path.isdir(root) else cwd


@metric
def claude_md(ctx):
    if not ctx.sessions:
        return {"context.claude_md": insufficient("no sessions")}
    gpath = os.path.abspath(os.path.join(ctx.home or os.path.expanduser("~"), ".claude", "CLAUDE.md"))
    glines = count_lines(gpath)
    by_cwd, sessions_per_cwd = {}, {}
    for s in ctx.sessions:
        key = s["cwd"] or ""
        sessions_per_cwd[key] = sessions_per_cwd.get(key, 0) + 1
        if key not in by_cwd:
            by_cwd[key] = (s["project"], project_files(readable_root(s["cwd"])))
    projects, paths, over, weighted, mt, missing, counted = {}, [], [], 0, {}, [], 0
    for cwd, (name, files) in by_cwd.items():
        if cwd and not os.path.isdir(readable_root(cwd)):
            # moved or renamed since: its CLAUDE.md can't be read, which is not the same as having none
            missing.append({"project": name, "cwd": cwd, "sessions": sessions_per_cwd[cwd]})
            continue
        counted += sessions_per_cwd[cwd]
        plines = sum(v["lines"] for v in files.values())
        total = glines + plines
        weighted += total * sessions_per_cwd[cwd]
        row = projects.setdefault(name, {"cwd": cwd, "project_lines": plines, "loaded_lines": total,
                                         "sessions": 0, "files": files})
        row["sessions"] += sessions_per_cwd[cwd]
        paths.extend(p for p in files if p not in paths)
        mt.update({p: v["mtime"] for p, v in files.items()})
        if total > OVER_LINES:
            over.append(name)
    if glines and gpath not in paths:
        paths.insert(0, gpath)
    mt[gpath] = mtime_iso(gpath)
    top = dict(sorted(projects.items(), key=lambda kv: -kv[1]["loaded_lines"])[:15])
    return {"context.claude_md": {
        "n": len(ctx.sessions), "global": {"path": gpath, "lines": glines, "mtime": mtime_iso(gpath) if glines else None},
        "projects": top, "paths": [{"path": p, "mtime": mt.get(p)} for p in paths],
        "projects_over_%d" % OVER_LINES: sorted(set(over)), "n_projects": len(projects),
        "missing_cwds": missing,
        "avg_lines_loaded": round(weighted / counted, 1) if counted else None,
        "note": "lines include @imports and AGENTS.md when there is no CLAUDE.md; missing_cwds no longer exist "
                "on disk, so their files can't be read and they are left out of the average"}}
