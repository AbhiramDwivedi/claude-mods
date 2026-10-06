"""cost.total and cost.cache.* : price-weighted cost, cache breaks, their causes and what-ifs."""
from wa_common import pct
from wa_registry import metric, example

CAUSES = ("compaction", "model_change", "idle_over_ttl", "version_change", "idle_under_ttl", "unexplained")


def _kind(t):
    return "subagent" if t["kind"] == "sub" else "main"


def _owner(t):
    return t.get("parent") or t


def _round_map(d, nd=4):
    return {k: round(v, nd) for k, v in sorted(d.items(), key=lambda kv: -kv[1])}


@metric
def cost_total(ctx):
    by_model, by_project, by_kind = {}, {}, {"main": 0.0, "subagent": 0.0}
    for t, r in ctx.requests():
        c = r["cost"]
        by_model[r["model"] or "unknown"] = by_model.get(r["model"] or "unknown", 0) + c
        by_project[t["project"]] = by_project.get(t["project"], 0) + c
        by_kind[_kind(t)] += c
    total = sum(by_kind.values())
    return {"cost.total": {"usd": round(total, 2), "n": sum(len(t["requests"]) for t in ctx.threads()),
                           "main": round(by_kind["main"], 2), "subagent": round(by_kind["subagent"], 2),
                           "by_model": _round_map(by_model, 2),
                           "by_project": _round_map(dict(sorted(by_project.items(), key=lambda kv: -kv[1])[:15]), 2),
                           "unit": "USD at list prices"}}


def _resume_kind(r, prev, ttl_min):
    # What came right before a subagent's break: a message to it, a tool call that ran past the TTL, or nothing special.
    if r["pre"] == "message":
        return "message"
    if r["pre"] == "tool_result" and r.get("pre_ts") and prev["ts"] and (r["pre_ts"] - prev["ts"]) / 60.0 > ttl_min:
        return "long_tool_call"
    return "other"


@metric
def cost_cache(ctx):
    total = sum(r["cost"] for _, r in ctx.requests())
    waste = {"main": 0.0, "subagent": 0.0}
    causes = {}
    resume = {k: [0, 0.0] for k in ("message", "long_tool_call", "other")}
    start = extra_1h = saved_1h = 0.0
    per_session = {}
    ttl_sub = ctx.ttl["sub"]
    for t in ctx.threads():
        kind = _kind(t)
        reqs = t["requests"]
        for i, r in enumerate(reqs):
            if kind == "subagent":
                if r["first"]:
                    start += r["cc"] * r["extra_per_tok"]
                rates = ctx.prices.rates(r["model"])
                extra_1h += r["cc5"] * (rates["cache_write_1h"] - rates["cache_write_5m"]) / 1e6
            if not r["brk"]:
                continue
            waste[kind] += r["waste"]
            row = causes.setdefault((kind, r["cause"]), [0, 0, 0.0])
            row[0] += 1
            row[1] += r["rew"]
            row[2] += r["waste"]
            o = _owner(t)
            ps = per_session.setdefault(o["id"], [o, 0.0, 0])
            ps[1] += r["waste"]
            ps[2] += 1
            if kind == "subagent":
                k = _resume_kind(r, reqs[i - 1], ttl_sub)
                resume[k][0] += 1
                resume[k][1] += r["waste"]
                if r["cause"] == "idle_over_ttl" and r["gap"] <= 60 and ttl_sub < 60:
                    saved_1h += r["waste"]
    by_cause = [{"thread": k, "cause": c, "count": v[0], "rewritten_tokens": v[1], "waste_pct": pct(v[2], total)}
                for (k, c), v in sorted(causes.items(), key=lambda kv: (kv[0][0], CAUSES.index(kv[0][1])))]
    top = sorted(per_session.values(), key=lambda v: -v[1])[:10]
    return {
        "cost.cache.waste_pct": {"main": pct(waste["main"], total), "subagent": pct(waste["subagent"], total),
                                 "total": pct(waste["main"] + waste["subagent"], total), "n": len(ctx.threads())},
        "cost.cache.by_cause": by_cause,
        "cost.cache.subagent_start_pct": pct(start, total),
        "cost.cache.resume_breaks": {k: {"count": v[0], "waste_pct": pct(v[1], total)} for k, v in resume.items()},
        "cost.cache.what_if.subagent_ttl_1h": {
            "extra_pct": pct(extra_1h, total), "saved_pct": pct(saved_1h, total),
            "net_pct": pct(saved_1h - extra_1h, total),
            "note": "extra = rate premium of 1h over 5m writes; saved = sub breaks idle between 5 and 60 min"},
        "cost.cache.top_sessions": [dict(example(o, pct(w, total)), breaks=n) for o, w, n in top],
    }
