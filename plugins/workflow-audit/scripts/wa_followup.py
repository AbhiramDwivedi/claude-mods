"""followup: compare the experiments an earlier run committed to against the metrics now."""
import json
import os


def find_previous(run_roots, current_dir):
    """Newest run dir (not current_dir) under any of run_roots that holds experiments.json, or None."""
    cur = os.path.normcase(os.path.abspath(current_dir))
    best = None
    seen = set()
    for root in run_roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for n in names:
            d = os.path.abspath(os.path.join(root, n))
            if os.path.normcase(d) == cur or d in seen:
                continue
            seen.add(d)
            f = os.path.join(d, "experiments.json")
            try:
                m = os.stat(f).st_mtime
            except OSError:
                continue
            if best is None or m > best[0]:
                best = (m, d)
    return best[1] if best else None


def resolve(metrics, metric, path):
    """(value, reason). Walks the nested metrics by the dotted metric key then the dotted path."""
    node = metrics
    for part in (metric or "").split(".") + ([p for p in path.split(".") if p] if path else []):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None, "no value at %s%s (stopped at '%s')" % (metric, "." + path if path else "", part)
    if isinstance(node, dict) and node.get("insufficient"):
        return None, "metric has too little data: %s" % node.get("reason")
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None, "value at that path is not a number"
    return node, None


def judge(now, target, direction):
    if now is None or target is None:
        return None
    return now >= target if direction == "up" else now <= target if direction == "down" else None


def followup(metrics, prev_dir):
    try:
        with open(os.path.join(prev_dir, "experiments.json"), encoding="utf8") as f:
            exps = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(exps, list):
        exps = [exps]
    current = (metrics.get("meta") or {}).get("metrics_version")
    rows = []
    for e in exps:
        if not isinstance(e, dict):
            continue
        now, reason = resolve(metrics, e.get("metric"), e.get("path"))
        row = {k: e.get(k) for k in ("id", "change", "metric", "path", "baseline", "target", "direction", "committed")}
        row["now"] = now
        row["met"] = judge(now, e.get("target"), e.get("direction"))
        if e.get("metrics_version") != current:
            # measured under another definition: show the number, but don't call it met or missed
            row["met"] = None
            reason = "the baseline was measured with metrics version %s and this run uses %s; set a new baseline" % (
                e.get("metrics_version"), current)
        if reason:
            row["reason"] = reason
        rows.append(row)
    return rows
