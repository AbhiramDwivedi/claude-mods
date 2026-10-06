"""context.claude_md: how many CLAUDE.md lines each session starts with."""
import os

from wa_registry import metric, insufficient

OVER_LINES = 200
PROJECT_FILES = (("CLAUDE.md",), (".claude", "CLAUDE.md"), ("CLAUDE.local.md",))


def count_lines(path):
    """Line count of a text file; 0 if it is missing or unreadable."""
    try:
        with open(path, encoding="utf8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def project_files(cwd):
    """{abs path: lines} for the CLAUDE.md files that exist under cwd."""
    out = {}
    if not cwd:
        return out
    for parts in PROJECT_FILES:
        p = os.path.join(cwd, *parts)
        if os.path.isfile(p):
            out[os.path.abspath(p)] = count_lines(p)
    return out


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
            by_cwd[key] = (s["project"], project_files(s["cwd"]))
    projects, paths, over, weighted = {}, [], [], 0
    for cwd, (name, files) in by_cwd.items():
        plines = sum(files.values())
        total = glines + plines
        weighted += total * sessions_per_cwd[cwd]
        row = projects.setdefault(name, {"cwd": cwd, "project_lines": plines, "loaded_lines": total,
                                         "sessions": 0, "files": files})
        row["sessions"] += sessions_per_cwd[cwd]
        paths.extend(p for p in files if p not in paths)
        if total > OVER_LINES:
            over.append(name)
    if glines and gpath not in paths:
        paths.insert(0, gpath)
    top = dict(sorted(projects.items(), key=lambda kv: -kv[1]["loaded_lines"])[:15])
    return {"context.claude_md": {
        "n": len(ctx.sessions), "global": {"path": gpath, "lines": glines},
        "projects": top, "paths": paths,
        "projects_over_%d" % OVER_LINES: sorted(over), "n_projects": len(projects),
        "avg_lines_loaded": round(weighted / len(ctx.sessions), 1)}}
