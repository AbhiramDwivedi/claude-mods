"""effort.by_model: which effort level sessions and subagents ran at, per model."""
from wa_registry import metric, insufficient


def _mode(values):
    c = {}
    for v in values:
        c[v] = c.get(v, 0) + 1
    return max(sorted(c), key=lambda k: c[k]) if c else None


def thread_effort(th):
    """(model, effort) of a thread: its most common model and effort over deduped requests; effort 'unknown' if none."""
    reqs = th["requests"]
    return _mode([r["model"] for r in reqs if r.get("model")]), _mode([r["eff"] for r in reqs if r.get("eff")]) or "unknown"


@metric
def effort_by_model(ctx):
    sess = [s for s in ctx.sessions if s["interactive"]]
    main, sub = {}, {}
    ultra = efforts = 0
    for s in sess:
        model, eff = thread_effort(s)
        if model:
            row = main.setdefault(model, {})
            row[eff] = row.get(eff, 0) + 1
        for u in s.get("subs", []):
            model, eff = thread_effort(u)
            if model:
                row = sub.setdefault(model, {})
                row[eff] = row.get(eff, 0) + 1
        for h in s["humans"]:
            if h["kind"] != "command" and "ultrathink" in (h.get("text") or "").lower():
                ultra += 1
            if h["kind"] == "command" and h.get("cmd") == "/effort":
                efforts += 1
    if not main:
        return {"effort.by_model": insufficient("no interactive sessions with requests", n=0)}
    return {"effort.by_model": {"n": len(sess), "main": main, "subagent": sub,
                                "ultrathink_messages": ultra, "effort_commands": efforts}}
