#!/usr/bin/env python3
"""ctx-study: how large Claude Code subagents get, and whether pit-stop handoffs work.

Reads ~/.claude/projects/<project>/<session>/subagents/agent-*.jsonl (read-only) and writes
report-YYYY-MM-DD.md, agents-YYYY-MM-DD.csv and a history.csv line into --out.
Standard library only; runs on Windows (py -3), macOS and Linux (python3).
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import statistics
import sys
from pathlib import Path

EDIT_TOOLS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
SIM_LIMITS = (200_000, 250_000, 300_000, 350_000, 450_000)
DEFAULT_F = 0.6

# Marker strings from plugins/pit-stop/hooks/register.ts. The note regexes demand concrete
# numbers, so a transcript that merely read the TypeScript source (`${tokens(context)}`) does not match.
CONTRACT_HEAD = '[pit-stop] Context budget.'
CONTRACT_BODY = 'Every request you make re-sends your whole context'
TOK = r'(\d+(?:\.\d)?)([KM])'
NUDGE_RE = re.compile(r'\[pit-stop\] Your context has reached ' + TOK + r' tokens')
WIND_RE = re.compile(r'\[pit-stop\] Your context is ' + TOK + r' tokens, past the ' + TOK + r' limit')
REFUSE_RE = re.compile(r'\[pit-stop\] Refused: your context \(' + TOK + r' tokens\) is past the ' + TOK + r' limit')
CHECKPOINT_RE = re.compile(r'^[\s*#_>`"]*CHECKPOINT\s*:', re.I)
PATH_RE = re.compile(r'[\w.~:-]*[\\/][\w./\\~:-]+\.\w{1,5}|\b[\w.-]+\.(?:md|txt)\b')
NOTE_WORDS = ('handoff', 'hand-off', 'checkpoint', 'note', 'relay')


def tok_value(num, unit):
    return float(num) * (1e6 if unit == 'M' else 1e3)


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text')
    return ''


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def q(values, p):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    i = (len(v) - 1) * p
    a = int(i)
    b = min(a + 1, len(v) - 1)
    return v[a] + (v[b] - v[a]) * (i - a)


def med(values):
    return q(values, 0.5)


def K(x):
    return '-' if x is None else (f'{x / 1e6:.2f}M' if x >= 1e6 else f'{x / 1000:.0f}K')


def pct(x):
    return '-' if x is None else f'{100 * x:.1f}%'


def short_project(p):
    p = re.sub(r'^[A-Za-z]--', '', p)                 # Windows drive: C--sw-foo -> sw-foo
    p = re.sub(r'^-(?:Users|home)-[^-]+-', '', p)      # macOS/Linux home: -Users-me-foo -> foo
    return p or '(root)'


def weighted(u):
    return (u['input'] + 1.25 * u['cc'] + 0.1 * u['cr'] + 5 * u['out'])


def parse_agent(path, limits):
    """One subagent transcript -> dict of metrics, or None if it has no usage."""
    project, session = path.parents[2].name, path.parents[1].name
    agent_id = path.name[len('agent-'):-len('.jsonl')]
    try:
        meta = json.loads(path.with_name(path.name[:-len('.jsonl')] + '.meta.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        meta = {}
    reqs, order = {}, []
    texts = {}            # message id -> concatenated text blocks (for the final report)
    brief = None
    first_ts = last_ts = None
    marks = {'nudge': [], 'wind': [], 'refuse': []}
    seen_mark_lines = set()
    with path.open(encoding='utf-8', errors='replace') as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ts = d.get('timestamp')
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            typ = d.get('type')
            if typ == 'user' and brief is None:
                brief = text_of((d.get('message') or {}).get('content'))
                continue
            if typ == 'assistant':
                m = d.get('message') or {}
                u = m.get('usage')
                k = m.get('id') or d.get('requestId') or d.get('uuid')
                if u:
                    if k not in reqs:
                        reqs[k] = {'u': u, 'edit': False, 'model': m.get('model')}
                        order.append(k)
                    elif (u.get('output_tokens') or 0) >= (reqs[k]['u'].get('output_tokens') or 0):
                        reqs[k]['u'] = u
                for c in m.get('content') or []:
                    if not isinstance(c, dict):
                        continue
                    if c.get('type') == 'tool_use' and c.get('name') in EDIT_TOOLS and k in reqs:
                        reqs[k]['edit'] = True
                    if c.get('type') == 'text' and c.get('text'):
                        texts.setdefault(k, []).append(c['text'])
                continue
            # pit-stop notes reach the agent as tool results or attachments, never in its own output
            if '[pit-stop]' in line:
                key = d.get('uuid') or line
                if key in seen_mark_lines:
                    continue
                seen_mark_lines.add(key)
                for kind, rx in (('nudge', NUDGE_RE), ('wind', WIND_RE), ('refuse', REFUSE_RE)):
                    for mt in rx.finditer(line):
                        marks[kind].append(tok_value(mt.group(1), mt.group(2)))
    if not order:
        return None
    ctx, ccs, wts, edit_at = [], [], [], None
    for i, k in enumerate(order):
        u = reqs[k]['u']
        x = {'input': u.get('input_tokens') or 0, 'cc': u.get('cache_creation_input_tokens') or 0,
             'cr': u.get('cache_read_input_tokens') or 0, 'out': u.get('output_tokens') or 0}
        ctx.append(x['input'] + x['cc'] + x['cr'])
        ccs.append(x['cc'])
        wts.append(weighted(x))
        if edit_at is None and reqs[k]['edit']:
            edit_at = i
    peak = max(ctx)
    # a note quotes the agent's own context; one far above what the agent reached is a quotation, not a note
    for kind in marks:
        marks[kind] = [v for v in marks[kind] if peak >= 0.9 * v]
    final_text = ''
    for k in reversed(list(texts)):
        if texts[k]:
            final_text = '\n'.join(texts[k]).strip()
            break
    model = next((reqs[k]['model'] for k in order if reqs[k]['model'] and reqs[k]['model'] != '<synthetic>'),
                 meta.get('model'))
    brief = brief or ''
    r = dict(
        project=project, session=session, agent=agent_id,
        date=(first_ts or '')[:10], start_ts=first_ts, end_ts=last_ts,
        model=model, agent_type=meta.get('agentType'), description=meta.get('description') or '',
        fork=bool(meta.get('isFork')), brief_chars=len(brief),
        start_ctx=ctx[0], R_edit=ctx[edit_at] if edit_at is not None else None,
        n_before_edit=edit_at, peak_ctx=peak, n_requests=len(ctx),
        weighted_total=sum(wts),
        contract=CONTRACT_HEAD in brief and CONTRACT_BODY in brief,
        nudges=len(marks['nudge']), wind_downs=len(marks['wind']), refusals=len(marks['refuse']),
        checkpoint=bool(CHECKPOINT_RE.match(final_text)),
    )
    for L in limits:
        r[f'w_above_{L // 1000}K'] = sum(w for c, w in zip(ctx, wts) if c > L)
    rw = [i for i in range(1, len(ctx)) if ctx[i] and ccs[i] >= 0.5 * ctx[i]]
    r['rewrites'] = len(rw)
    r['rewrites_w'] = sum(wts[i] for i in rw)
    r['rewrites_hi'] = sum(1 for i in rw if ctx[i] >= limits[0])
    r['rewrites_hi_w'] = sum(wts[i] for i in rw if ctx[i] >= limits[0])
    r['_ctx'] = ctx
    r['_brief'] = brief
    r['_final'] = final_text
    return r


# ---------- pit-stop handoff pairing ----------

def shingles(text, n=8):
    w = re.findall(r'\w+', text.lower())
    return {' '.join(w[i:i + n]) for i in range(len(w) - n + 1)}


def note_paths(report):
    """Path-like tokens in a CHECKPOINT report that look like a handoff note."""
    out = set()
    for p in PATH_RE.findall(report):
        norm = p.replace('\\', '/').strip('`\'".,:;()').lower()
        if any(w in norm for w in NOTE_WORDS):
            out.add(norm.rsplit('/', 1)[-1])
    return out


def references(pred, cand):
    """How the candidate's brief references the predecessor's handoff, or None."""
    brief = cand['_brief'].split(CONTRACT_HEAD)[0]     # the appended contract is not the brief's own text
    low = brief.lower().replace('\\', '/')
    if pred['agent'] in brief:
        return 'agent-id'
    for name in note_paths(pred['_final']):
        if len(name) >= 6 and name in low:
            return 'note-path'
    if len(shingles(pred['_final']) & shingles(brief)) >= 3:
        return 'text'
    return None


def pair_handoffs(agents):
    """Predecessor = non-fork agent ending with CHECKPOINT or refused by pit-stop. Successor = the first later
    non-fork agent in the same parent session (started after the predecessor's last event) whose brief
    names the predecessor's agent id, a note file from its report, or shares >=3 8-word runs with it."""
    by_session = {}
    for a in agents:
        by_session.setdefault((a['project'], a['session']), []).append(a)
    pairs, unmatched, taken = [], [], set()
    for group in by_session.values():
        group.sort(key=lambda a: a['start_ts'] or '')
        for pred in group:
            if not (pred['checkpoint'] or pred['refusals']):
                continue
            end = parse_ts(pred['end_ts'])
            match = None
            for cand in group:
                if cand is pred or id(cand) in taken:
                    continue
                st = parse_ts(cand['start_ts'])
                if st is None or end is None or st < end - dt.timedelta(seconds=5):
                    continue
                how = references(pred, cand)
                if how:
                    match = (cand, how)
                    break
            if match:
                taken.add(id(match[0]))
                pairs.append((pred, match[0], match[1]))
            else:
                unmatched.append(pred)
    return pairs, unmatched


# ---------- what-if simulation (from the one-off sim.py) ----------

def sim_cost(seq):
    c, prev = 0.0, 0.0
    for x in seq:
        c += 0.1 * prev + 1.25 * max(0.0, x - prev)
        prev = x
    return c


def sim_run(t, start, R, nb, L, f):
    """Replay a trajectory under limit L: 3 note-writing requests (+5K each), then a fresh agent at the
    original start re-orients to start + f*(R-start) over f*nb requests, then the original increments."""
    out, i, cur, stops = [], 0, None, 0
    while i < len(t):
        x = t[i] if cur is None else cur + (t[i] - t[i - 1])
        if x >= L and stops < 8 and i > 0:
            stops += 1
            base = out[-1]
            out += [base + 5e3 * j for j in (1, 2, 3)]
            tgt = start + f * (R - start)
            n = max(1, round(f * nb))
            out += [start + (tgt - start) * (j + 1) / n for j in range(n)]
            cur = out[-1]
            i += 1
            continue
        out.append(x)
        if cur is not None:
            cur = x
        i += 1
    return out, stops


def simulate(agents, f):
    med_R = med([a['R_edit'] for a in agents]) or 91e3
    med_nb = med([a['n_before_edit'] for a in agents if a['n_before_edit'] is not None]) or 9
    runs = []
    for a in agents:
        t = a['_ctx']
        if len(t) < 2:
            continue
        R = a['R_edit'] if a['R_edit'] is not None else min(med_R, max(t))
        nb = a['n_before_edit'] if a['n_before_edit'] is not None else med_nb
        runs.append((t, a['start_ctx'], R, nb))
    base = sum(sim_cost(t) for t, *_ in runs)
    rows = []
    for L in SIM_LIMITS:
        tot, hs = 0.0, 0
        for t, st, R, nb in runs:
            o, h = sim_run(t, st, R, nb, L, f)
            tot += sim_cost(o)
            hs += h
        rows.append((L, (tot / base - 1) if base else 0.0, hs))
    return rows


# ---------- report ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--projects', default=str(Path.home() / '.claude' / 'projects'))
    ap.add_argument('--since', type=float, default=7, help='days back by agent start time; 0 = all')
    ap.add_argument('--out', default=str(Path.home() / '.claude' / 'ctx-study'))
    ap.add_argument('--limits', default='300,450', help='nudge,stop limits in K tokens')
    args = ap.parse_args(argv)
    limits = [int(float(x) * 1000) for x in args.limits.split(',') if x.strip()]
    L1, L2 = limits[0], limits[-1]
    projects, out = Path(args.projects).expanduser(), Path(args.out).expanduser()
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=args.since) if args.since > 0 else None
    # the session running this script is still writing its transcripts; skip it when the env names it
    self_session = os.environ.get('CLAUDE_CODE_SESSION_ID') or ''

    agents, skipped_self = [], 0
    for path in sorted(projects.glob('*/*/subagents/agent-*.jsonl')):
        if self_session and path.parents[1].name == self_session:
            skipped_self += 1
            continue
        if cutoff and dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc) < cutoff:
            continue              # last written before the window, so it also started before it
        r = parse_agent(path, limits)
        if r is None:
            continue
        st = parse_ts(r['start_ts'])
        if cutoff and (st is None or st < cutoff):
            continue
        agents.append(r)

    forks = [a for a in agents if a['fork']]
    nf = [a for a in agents if not a['fork']]
    pairs, unmatched = pair_handoffs(nf)
    successors = {id(s) for _, s, _ in pairs}
    base_growth = med([a['R_edit'] - a['start_ctx'] for a in nf if a['R_edit'] is not None and id(a) not in successors])
    pair_rows = []
    for p, s, how in pairs:
        frac = None
        if s['R_edit'] is not None and base_growth:
            frac = (s['R_edit'] - s['start_ctx']) / base_growth
        s['successor_of'] = p['agent']
        s['match_by'] = how
        s['reorient_frac'] = frac
        pair_rows.append((p, s, how, frac))
    fracs = [f for *_, f in pair_rows if f is not None]
    med_frac = med(fracs)
    f_used, f_src = (med_frac, f'measured median of {len(fracs)} pairs') if len(fracs) >= 3 \
        else (DEFAULT_F, f'default {DEFAULT_F} (only {len(fracs)} measured pair(s); need 3)')

    tw = sum(a['weighted_total'] for a in nf)

    def share(rs, L):
        t = sum(a['weighted_total'] for a in rs)
        return sum(a[f'w_above_{L // 1000}K'] for a in rs) / t if t else None

    def over(rs, L):
        return sum(a['peak_ctx'] > L for a in rs)

    today = now.astimezone().date().isoformat()
    suffix = '' if args.since == 7 else ('-all' if args.since <= 0 else f'-{args.since:g}d')
    window = 'all time' if cutoff is None else f'last {args.since:g} days (since {cutoff.date()})'
    out.mkdir(parents=True, exist_ok=True)

    # ---- agents CSV ----
    cols = ['project', 'session', 'agent', 'date', 'model', 'agent_type', 'description', 'fork', 'brief_chars',
            'start_ctx', 'R_edit', 'n_before_edit', 'peak_ctx', 'n_requests', 'weighted_total'] + \
           [f'w_above_{L // 1000}K' for L in limits] + \
           ['rewrites', 'rewrites_w', 'contract', 'nudges', 'wind_downs', 'refusals', 'checkpoint',
            'successor_of', 'match_by', 'reorient_frac']
    with (out / f'agents-{today}{suffix}.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for a in sorted(agents, key=lambda a: a['start_ts'] or ''):
            row = {k: a.get(k) for k in cols}
            for k in ('weighted_total', 'rewrites_w') + tuple(f'w_above_{L // 1000}K' for L in limits):
                row[k] = round(row[k])
            if row['reorient_frac'] is not None:
                row['reorient_frac'] = round(row['reorient_frac'], 3)
            w.writerow(row)

    # ---- report ----
    R = []
    add = R.append
    add(f'# Subagent context report {today}')
    add('')
    add(f'Window: {window}. Source: `{projects}`.' +
        (f' Skipped {skipped_self} transcript(s) of the running session {self_session[:8]}.' if skipped_self else ''))
    editing = [a for a in nf if a['R_edit'] is not None]
    add(f'Agents: **{len(nf)}** non-fork ({len(forks)} forks excluded); {len(editing)} editing, '
        f'{len(nf) - len(editing)} never edited.')
    if not nf:
        add('')
        add('No subagents in this window.')
    else:
        add('')
        add('| ctx | p25 | median | p75 | p90 | max |')
        add('|---|---|---|---|---|---|')
        for lab, key in (('start', 'start_ctx'), ('R_edit (first edit)', 'R_edit'), ('peak', 'peak_ctx')):
            v = [a[key] for a in nf]
            add(f'| {lab} | ' + ' | '.join(K(q(v, p)) for p in (.25, .5, .75, .9)) +
                f' | {K(max((x for x in v if x is not None), default=None))} |')
        add('')
        add('## Limits')
        for L in limits:
            add(f'- Over {K(L)}: {over(nf, L)} agents ({100 * over(nf, L) / len(nf):.1f}%); '
                f'cost share of requests above {K(L)}: {pct(share(nf, L))}')
        big = sorted((a for a in nf if a['peak_ctx'] > L2), key=lambda a: -a['peak_ctx'])
        if big:
            add('')
            add(f'Agents over {K(L2)}:')
            add('')
            add('| project | session | date | model | description | peak |')
            add('|---|---|---|---|---|---|')
            for a in big:
                desc = a['description'].replace('|', '/')[:50]
                add(f'| {short_project(a["project"])} | {a["session"][:8]} | {a["date"]} | {a["model"]} | {desc} | {K(a["peak_ctx"])} |')
        for title, keyf, top in (('By project', lambda a: short_project(a['project']), 10),
                                 ('By model', lambda a: a['model'] or '?', 8)):
            add('')
            add(f'## {title}')
            add('')
            add(f'| {title[3:]} | n | med start | med R_edit | med peak | >{K(L1)} | cost share | >{K(L1)} share |')
            add('|---|---|---|---|---|---|---|---|')
            groups = {}
            for a in nf:
                groups.setdefault(keyf(a), []).append(a)
            ranked = sorted(groups.items(), key=lambda kv: -sum(a['weighted_total'] for a in kv[1]))
            rest = [a for _, g in ranked[top:] for a in g]
            shown = ranked[:top] + ([(f'({len(ranked) - top} others)', rest)] if rest else [])
            for name, g in shown:
                gw = sum(a['weighted_total'] for a in g)
                add(f'| {name} | {len(g)} | {K(med([a["start_ctx"] for a in g]))} | {K(med([a["R_edit"] for a in g]))} | '
                    f'{K(med([a["peak_ctx"] for a in g]))} | {over(g, L1)} | {pct(gw / tw if tw else None)} | {pct(share(g, L1))} |')

    # ---- pit-stop ----
    add('')
    add('## pit-stop')
    n_contract = sum(a['contract'] for a in nf)
    nudged = [a for a in nf if a['nudges']]
    wound = [a for a in nf if a['wind_downs']]
    refused = [a for a in nf if a['refusals']]
    cps = [a for a in nf if a['checkpoint']]
    add(f'- Loaded: {"yes" if n_contract else "no sign"} ({n_contract}/{len(nf)} briefs carry the contract)')
    add(f'- Nudged: {len(nudged)}; wind-down notes: {len(wound)} agents; refused: {len(refused)} agents '
        f'({sum(a["refusals"] for a in refused)} refusals); CHECKPOINT reports: {len(cps)}')
    add(f'- Successor pairs: {len(pairs)} ({len(unmatched)} predecessor(s) with no successor found)')
    for p, s, how, frac in pair_rows:
        add(f'  - {short_project(p["project"])} {p["session"][:8]}: {p["agent"][:8]} (peak {K(p["peak_ctx"])}) -> '
            f'{s["agent"][:8]} by {how}; start {K(s["start_ctx"])}, R_edit {K(s["R_edit"])}, '
            f'fraction {"-" if frac is None else f"{frac:.2f}"}')
    add(f'- Re-orientation fraction (successor R_edit - start, over the median {K(base_growth)} for other agents): '
        + (f'median {med_frac:.2f} over {len(fracs)} pair(s)' if fracs else 'no measured pairs yet'))

    # ---- cache rewrites ----
    rw_n = sum(a['rewrites'] for a in nf)
    rw_w = sum(a['rewrites_w'] for a in nf)
    rh_n = sum(a['rewrites_hi'] for a in nf)
    rh_w = sum(a['rewrites_hi_w'] for a in nf)
    n_req = sum(a['n_requests'] for a in nf)
    add('')
    add('## Cache-expiry rewrites')
    add(f'Requests after an agent\'s first whose cache_creation is >=50% of ctx: {rw_n} of {n_req} '
        f'({pct(rw_n / n_req if n_req else None)}), {pct(rw_w / tw if tw else None)} of weighted cost. '
        f'At ctx >= {K(L1)}: {rh_n} requests, {pct(rh_w / tw if tw else None)} of weighted cost.')

    # ---- what-if ----
    sim = simulate(nf, f_used) if nf else []
    add('')
    add(f'## What-if: limit with handoff (re-orientation fraction {f_used:.2f}, {f_src})')
    add('')
    add('| limit | ' + ' | '.join(K(L) for L, _, _ in sim) + ' |')
    add('|---|' + '---|' * len(sim))
    add('| cost change | ' + ' | '.join(f'{100 * c:+.1f}%' for _, c, _ in sim) + ' |')
    add('| handoffs | ' + ' | '.join(str(h) for _, _, h in sim) + ' |')

    # ---- verdict ----
    add('')
    medR = med([a['R_edit'] for a in nf])
    if sim and medR:
        best_L, best_c, _ = min(sim, key=lambda r: r[1])
        rule = 2 * medR
        off = abs(best_L - L1) > 50_000
        add(f'**Verdict:** {"FLAG" if off else "OK"}. Rule of thumb 2 x median R_edit = {K(rule)}; best simulated limit '
            f'{K(best_L)} ({100 * best_c:+.1f}%). '
            + (f'The best simulated limit is more than 50K from {K(L1)}; revisit the {K(L1)}/{K(L2)} limits.'
               if off else f'{K(L1)}/{K(L2)} still looks right.')
            + (f' Note: the rule of thumb is more than 50K from the simulated best; the simulation counts the '
               f'handoff cost, the rule does not.' if abs(rule - best_L) > 50_000 else ''))
    else:
        add('**Verdict:** not enough data.')
    text = '\n'.join(R) + '\n'
    (out / f'report-{today}{suffix}.md').write_text(text, encoding='utf-8')

    # ---- history ----
    hist = out / 'history.csv'
    hcols = ['run_date', 'window_days', 'limits', 'n_agents', 'n_forks', 'median_start', 'median_R_edit',
             'median_peak', 'pct_over_limit1', 'pct_over_limit2', 'cost_share_limit1', 'cost_share_limit2',
             'n_contract', 'n_checkpoints', 'n_handoffs', 'median_reorient_fraction']
    new = not hist.exists()
    with hist.open('a', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(hcols)

        def r0(x, nd=0):
            return '' if x is None else round(x, nd) if nd else round(x)
        w.writerow([today, f'{args.since:g}', f'{L1 // 1000}/{L2 // 1000}', len(nf), len(forks),
                    r0(med([a['start_ctx'] for a in nf])), r0(medR), r0(med([a['peak_ctx'] for a in nf])),
                    r0(100 * over(nf, L1) / len(nf), 2) if nf else '', r0(100 * over(nf, L2) / len(nf), 2) if nf else '',
                    r0(100 * share(nf, L1), 2) if nf else '', r0(100 * share(nf, L2), 2) if nf else '',
                    n_contract, len(cps), len(pairs), r0(med_frac, 3)])
    print(text)
    print(f'Wrote {out / f"report-{today}{suffix}.md"}, agents-{today}{suffix}.csv, history.csv', file=sys.stderr)


if __name__ == '__main__':
    main()
