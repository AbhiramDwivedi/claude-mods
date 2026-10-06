"""meta: what was read, and under which billing assumptions."""
import json
import os

from wa_common import METRICS_VERSION, day, iso
from wa_registry import metric


def _count(items):
    out = {}
    for k in items:
        if k:
            out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def plugins_installed(home):
    """[{name, version, installed_at}] from ~/.claude/plugins/installed_plugins.json, or None if unreadable."""
    path = os.path.join(home, ".claude", "plugins", "installed_plugins.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        out = []
        for name, entries in (data.get("plugins") or {}).items():
            for e in entries if isinstance(entries, list) else [entries]:
                when = e.get("installedAt") or e.get("lastUpdated")
                if not when and e.get("installPath"):
                    try:
                        when = iso(os.stat(e["installPath"]).st_mtime)
                    except OSError:
                        when = None
                out.append({"name": name, "version": e.get("version"), "installed_at": when})
        return sorted(out, key=lambda r: r["name"])
    except (OSError, ValueError, AttributeError):
        return None


@metric
def meta(ctx):
    threads = ctx.threads()
    reqs = [r for _, r in ctx.requests()]
    stamps = [t["first_ts"] for t in threads if t["first_ts"]] + [t["last_ts"] for t in threads if t["last_ts"]]
    versions = {}
    for t in threads:
        for v, n in t["versions"].items():
            versions[v] = versions.get(v, 0) + n
    p = ctx.prices
    out = {"meta": {
        "metrics_version": METRICS_VERSION,
        "window": {"days": ctx.days, "since": day(max(0, ctx.now - ctx.days * 86400)), "until": day(ctx.now),
                   "first_record": iso(min(stamps)) if stamps else None,
                   "last_record": iso(max(stamps)) if stamps else None},
        "counts": {"main_sessions": len(ctx.sessions),
                   "interactive": sum(1 for s in ctx.sessions if s["interactive"]),
                   "unattended": sum(1 for s in ctx.sessions if s["unattended"]),
                   "subagents": len(ctx.subs), "requests": len(reqs), "files": ctx.n_files,
                   "bad_lines": sum(t["bad_lines"] for t in threads)},
        "versions": dict(sorted(versions.items(), key=lambda kv: -kv[1])),
        "models": _count(r["model"] for r in reqs),
        "billing": ctx.billing,
        "insights": ctx.insights,
        "excluded_sessions": ctx.excluded,
        "prices": {"source": p.source, "checked": p.checked, "file": p.path,
                   "unknown_models": dict(p.unknown)},
        "cache": ctx.cache_stats,
    }}
    pl = plugins_installed(ctx.home)
    if pl is not None:
        out["meta"]["plugins_installed"] = pl
    return out
