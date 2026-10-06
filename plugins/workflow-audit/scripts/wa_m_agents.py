"""agents.*: Agent tool calls, explicit model rate, which model subagents really ran, subagent size."""
from wa_common import iso_week
from wa_registry import metric, example

SIZE_STEPS = (200000, 300000, 450000)


def _calls(ctx):
    return [c for s in ctx.sessions for c in s["agent_calls"]]


@metric
def agent_calls(ctx):
    calls = _calls(ctx)
    weeks, expl = {}, {}
    for c in calls:
        w = iso_week(c["ts"]) if c["ts"] else "unknown"
        weeks[w] = weeks.get(w, 0) + 1
        expl[w] = expl.get(w, 0) + (1 if c["model"] else 0)
    n_expl = sum(1 for c in calls if c["model"])
    return {
        "agents.calls": {"total": len(calls), "n": len(calls), "by_week": dict(sorted(weeks.items()))},
        "agents.explicit_model_rate": {
            "overall": round(n_expl / len(calls), 4) if calls else None, "n": len(calls), "explicit": n_expl,
            "by_week": {w: {"n": weeks[w], "explicit": expl[w], "rate": round(expl[w] / weeks[w], 4)}
                        for w in sorted(weeks)}},
    }


@metric
def agents_by_model(ctx):
    out = {}
    for sub in ctx.subs:
        row = out.setdefault(sub["child_model"] or "unknown", {"total": 0, "explicit": 0, "inherited": 0})
        row["total"] += 1
        row["explicit" if sub["explicit_model"] else "inherited"] += 1
    return {"agents.by_model": {"n": len(ctx.subs),
                                "models": dict(sorted(out.items(), key=lambda kv: -kv[1]["total"]))}}


@metric
def agents_size(ctx):
    sized = [(max((r["ctx"] for r in sub["requests"]), default=0), sub) for sub in ctx.subs]
    sized.sort(key=lambda x: -x[0])
    out = {"n": len(sized), "max": sized[0][0] if sized else 0}
    for step in SIZE_STEPS:
        out["over_%dk" % (step // 1000)] = sum(1 for m, _ in sized if m > step)
    out["top"] = [dict(example(sub["parent"] or sub, m), agent=sub["agent_id"], model=sub["child_model"])
                  for m, sub in sized[:10]]
    return {"agents.size": out}
