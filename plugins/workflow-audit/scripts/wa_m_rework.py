"""rework.*: corrections, correction streaks, /insights agreement; plus the samples written for sample readers."""
import json
import os
import re

from wa_common import redact
from wa_registry import metric, example, insufficient

# Tight: the message opens with a correction. Measured ~55% precise on one user (hand-labelled).
TIGHT = re.compile(r"^\s*(no|nope|wrong|stop|wait|actually|that'?s not|that is not|not what|i said|why did you)\b", re.I)
# Loose: the prototype's wide net. "don't" fires mostly on benign instructions, so it is only a secondary count.
LOOSE = re.compile(r"(^\s*(no|nope|wrong|stop|wait|actually)\b)|not what|\bi said\b|\bstop\b|don'?t|do not|"
                   r"why did you|\bactually\b|\binstead\b|\bwrong\b", re.I)
PRECISION_NOTE = ("The tight pattern (message opens with no/nope/wrong/stop/wait/actually/not what/I said/why did you) "
                  "measured about 55% precise on one user's hand-labelled sample; the loose count (any 'don't', "
                  "'instead', 'actually' ...) about 35%. Treat both as a signal to read samples, not a verdict.")
MIN_INSIGHTS_JOIN = 20
MAX_SAMPLES = 8
MAX_MOMENTS = 12


def messages(s):
    """Human messages that are text (typed or queued), in order. Slash commands are not messages here."""
    return [h for h in s["humans"] if h["kind"] != "command"]


def _streak(pairs):
    """Longest run of consecutive message indexes flagged True, if it has 2+ messages; else []."""
    best, run = [], []
    for i, flagged in pairs:
        if flagged:
            run = run + [i] if run and run[-1] == i - 1 else [i]
            if len(run) >= 2 and len(run) >= len(best):
                best = list(run)
        else:
            run = []
    return best


def analyse(s):
    """Per session: non-first messages flagged tight / loose, and the longest tight streak. Cached on the dict."""
    if "_rw" in s:
        return s["_rw"]
    msgs = messages(s)
    flags = [(i, bool(TIGHT.search(h["text"])), bool(LOOSE.search(h["text"]))) for i, h in enumerate(msgs) if i]
    best, lbest = _streak([(i, t) for i, t, _l in flags]), _streak([(i, l) for i, _t, l in flags])
    s["_rw"] = {"msgs": msgs, "non_first": len(flags), "tight": sum(1 for f in flags if f[1]),
                "loose": sum(1 for f in flags if f[2]), "tight_idx": [f[0] for f in flags if f[1]],
                "flagged_idx": [f[0] for f in flags if f[1] or f[2]], "streak": best, "loose_streak": lbest}
    return s["_rw"]


def _rate(n, d):
    return round(n / d, 4) if d else None


def _interactive(ctx):
    return [s for s in ctx.sessions if s["interactive"]]


@metric
def correction_rate(ctx):
    sess = _interactive(ctx)
    if not sess:
        return {"rework.correction_rate": insufficient("no interactive sessions")}
    nf = sum(analyse(s)["non_first"] for s in sess)
    tight = sum(analyse(s)["tight"] for s in sess)
    loose = sum(analyse(s)["loose"] for s in sess)
    by_proj = {}
    for s in sess:
        a = analyse(s)
        row = by_proj.setdefault(s["project"], {"sessions": 0, "non_first": 0, "tight": 0, "loose": 0})
        row["sessions"] += 1
        row["non_first"] += a["non_first"]
        row["tight"] += a["tight"]
        row["loose"] += a["loose"]
    for row in by_proj.values():
        row["rate"] = _rate(row["tight"], row["non_first"])
    top = sorted(by_proj.items(), key=lambda kv: -kv[1]["tight"])[:10]
    ranked = sorted(sess, key=lambda s: (-analyse(s)["tight"], -analyse(s)["loose"]))
    return {"rework.correction_rate": {
        "overall": _rate(tight, nf), "overall_loose": _rate(loose, nf), "n": len(sess), "non_first_messages": nf,
        "tight": tight, "loose": loose, "sessions_with_tight": sum(1 for s in sess if analyse(s)["tight"]),
        "by_project": dict(top),
        "top_sessions": [example(s, analyse(s)["tight"]) for s in ranked[:10] if analyse(s)["tight"]],
        "precision_note": PRECISION_NOTE}}


def _streak_rows(ctx, key):
    rows = []
    for s in _interactive(ctx):
        a = analyse(s)
        if len(a[key]) >= 2:
            ex = example(s, len(a[key]))
            ex["examples"] = [redact(a["msgs"][i]["text"][:120]) for i in a[key][:3]]
            rows.append(ex)
    rows.sort(key=lambda r: -r["value"])
    return rows


@metric
def correction_streaks(ctx):
    tight, loose = _streak_rows(ctx, "streak"), _streak_rows(ctx, "loose_streak")
    return {"rework.correction_streaks": {
        "sessions": len(tight), "n": len(_interactive(ctx)), "top": tight[:10],
        "loose_sessions": len(loose), "loose_top": loose[:5],
        "note": "sessions: 2+ consecutive messages matching the tight pattern; loose_*: same with the loose pattern"}}


def auc(positives, negatives):
    """P(random positive scores above random negative), ties count half. Rank-based."""
    if not positives or not negatives:
        return None
    scored = sorted([(v, 1) for v in positives] + [(v, 0) for v in negatives])
    ranks, i = {}, 0
    while i < len(scored):
        j = i
        while j < len(scored) and scored[j][0] == scored[i][0]:
            j += 1
        ranks[scored[i][0]] = (i + 1 + j) / 2.0
        i = j
    rsum = sum(ranks[v] for v in positives)
    n1, n0 = len(positives), len(negatives)
    return round((rsum - n1 * (n1 + 1) / 2.0) / (n1 * n0), 3)


def load_facets(home):
    d = os.path.join(home, ".claude", "usage-data", "facets")
    out = {}
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if n.endswith(".json"):
            try:
                with open(os.path.join(d, n), encoding="utf8") as f:
                    out[n[:-5]] = json.load(f)
            except (OSError, ValueError):
                pass
    return out


def _dissat(f):
    return ((f.get("user_satisfaction_counts") or {}).get("dissatisfied") or 0) > 0


@metric
def insights(ctx):
    facets = load_facets(ctx.home or os.path.expanduser("~"))
    joined = [(s, facets[s["id"]]) for s in ctx.sessions if s["id"] in facets]
    if not joined:
        return {"rework.insights": insufficient("no /insights facets for sessions in this window", n_joined=0)}
    outcomes, friction = {}, {}
    for _s, f in joined:
        o = f.get("outcome") or "unknown"
        outcomes[o] = outcomes.get(o, 0) + 1
        for k, v in (f.get("friction_counts") or {}).items():
            friction[k] = friction.get(k, 0) + (v or 0)
    out = {"n": len(joined), "n_joined": len(joined),
           "outcomes": dict(sorted(outcomes.items(), key=lambda kv: -kv[1])),
           "friction": dict(sorted(friction.items(), key=lambda kv: -kv[1]))}
    inter = [(s, f) for s, f in joined if s["interactive"]]
    out["n_interactive_joined"] = len(inter)
    if len(inter) < MIN_INSIGHTS_JOIN:
        out["auc"] = insufficient("fewer than %d interactive sessions joined" % MIN_INSIGHTS_JOIN)
        return {"rework.insights": out}
    dis = [s for s, f in inter if _dissat(f)]
    non = [s for s, f in inter if not _dissat(f)]

    def rate(s, key):
        a = analyse(s)
        return a[key] / a["non_first"] if a["non_first"] else 0.0

    def share(g, key):
        return round(sum(1 for s in g if analyse(s)[key] >= 1) / len(g), 3) if g else None

    out["auc"] = {"dissatisfied_vs_not": {
        "tight_rate": auc([rate(s, "tight") for s in dis], [rate(s, "tight") for s in non]),
        "loose_rate": auc([rate(s, "loose") for s in dis], [rate(s, "loose") for s in non]),
        "n_dissatisfied": len(dis), "n_not": len(non),
        "share_with_tight_correction": {"dissatisfied": share(dis, "tight"), "not": share(non, "tight")},
        "share_with_loose_correction": {"dissatisfied": share(dis, "loose"), "not": share(non, "loose")}},
        "note": "AUC 0.5 = no signal, 1.0 = perfect. Only interactive sessions that /insights faceted."}
    return {"rework.insights": out}


def select_samples(ctx):
    # the loose pattern is too noisy to count on but fine to read: the sample readers say which moments are not
    # corrections at all, and the tight pattern alone leaves too few sessions to sample
    sess = [s for s in _interactive(ctx) if len(analyse(s)["flagged_idx"]) >= 2]
    sess.sort(key=lambda s: (-analyse(s)["tight"], -len(analyse(s)["flagged_idx"])))
    return sess[:MAX_SAMPLES]


def render_sample(s):
    a = analyse(s)
    lines = ["# Corrections in session %s" % s["id8"], "",
             "session: %s" % s["id"], "project: %s" % s["project"], "date: %s" % s["date"],
             "human messages: %d" % len(a["msgs"]), "flagged moments: %d (tight pattern: %d)" % (len(a["flagged_idx"]), a["tight"]), ""]
    for n, i in enumerate(a["flagged_idx"][:MAX_MOMENTS], 1):
        h = a["msgs"][i]
        before = redact(h.get("tail") or "")[-600:].replace("\n", " ") or "(no text)"
        lines += ["## Moment %d (message %d of %d, %s pattern)" % (n, i + 1, len(a["msgs"]), "tight" if i in a["tight_idx"] else "loose"), "",
                  "Claude (before): " + before, "",
                  "Person: " + redact(h["text"])[:600].replace("\n", " "), ""]
    return "\n".join(lines)


@metric
def samples(ctx):
    rows = []
    if not ctx.out_dir:
        return {"samples": rows}
    d = os.path.join(ctx.out_dir, "samples")
    os.makedirs(d, exist_ok=True)
    for n, s in enumerate(select_samples(ctx), 1):
        path = os.path.abspath(os.path.join(d, "%02d-%s.md" % (n, s["id8"])))
        with open(path, "w", encoding="utf8", newline="\n") as f:
            f.write(render_sample(s))
        rows.append({"file": path, "session": s["id"], "session8": s["id8"], "project": s["project"],
                     "corrections": len(analyse(s)["flagged_idx"]), "tight": analyse(s)["tight"]})
    return {"samples": rows}
