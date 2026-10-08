"""permissions.denials: what the permission system refused, and how the refused shell commands look."""
import os
import re

from wa_registry import metric, example, insufficient

SHELL_TOOLS = ("Bash", "PowerShell")
SHAPE_KINDS = ("permission-rule", "user-rejected")
READ_ONLY = {"ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "pwd", "echo", "which", "type", "file",
             "stat", "du", "df", "cd", "get-childitem", "get-content", "select-string", "test-path"}
READ_ONLY_GIT = {"status", "log", "diff", "show", "branch", "rev-parse"}
INTERPRETERS = {"python", "python3", "py", "node", "bash", "sh", "pwsh", "powershell", "ruby", "deno", "bun"}
INLINE = re.compile(r"(?:^|[\s;&|])(?:(?:python3?|py)(?:\s+-\d)?\s+-c\b|node\s+(?:-\S+\s+)*-e\b|"
                    r"(?:powershell|pwsh)(?:\.exe)?\s+(?:-\S+\s+)*-(?:command|c)\b|(?:ba)?sh\s+-c\b)", re.I)
ABS = re.compile(r"^(?:[A-Za-z]:[\/]|/|\\|~[\/])")
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
SEP = re.compile(r"&&|\|\||;|\||\n")
FD_REDIRECT = re.compile(r"\d*>&\d|\d*>>?\s*/dev/null|&>\s*/dev/null|\d*>\s*\$null", re.I)
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _tokens(seg):
    out = []
    for t in seg.split():
        if ENV_ASSIGN.match(t) and not out:
            continue
        out.append(t.strip("\"'"))
    return out


def program_name(tokens):
    """Readable program name of one segment: 'git status', 'cat', or the basename of the program."""
    if not tokens:
        return None
    prog = os.path.basename(tokens[0].replace("\\", "/")).lower()
    if prog.endswith(".exe"):
        prog = prog[:-4]
    if prog == "git":
        rest, i = tokens[1:], 0
        while i < len(rest) and rest[i].startswith("-"):
            i += 2 if rest[i] in ("-C", "-c") else 1
        return "git " + rest[i].lower() if i < len(rest) else "git"
    return prog


def _is_read_only(name):
    if name is None:
        return False
    if name.startswith("git "):
        return name[4:] in READ_ONLY_GIT
    return name in READ_ONLY


def classify(cmd):
    """(shape, [program names]) for a shell command. First match wins: read_only, chained, inline_interpreter,
    absolute_path, other."""
    flat = QUOTED.sub('""', cmd or "")
    flat = FD_REDIRECT.sub(" ", flat)
    segs = [s.strip() for s in SEP.split(flat) if s.strip()]
    toks = [_tokens(s) for s in segs]
    names = [program_name(t) for t in toks if t]
    if names and all(_is_read_only(n) for n in names) and ">" not in flat:
        return "read_only", names
    if len(segs) > 1:
        return "chained", names
    if INLINE.search(cmd or ""):
        return "inline_interpreter", names
    t = toks[0] if toks else []
    if t and ABS.match(t[0]):
        return "absolute_path", names
    if t and program_name(t) in INTERPRETERS:
        args = [a for a in t[1:] if not a.startswith("-")]
        if args and ABS.match(args[0]):
            return "absolute_path", names
    return "other", names


def _bump(d, k, n=1):
    d[k] = d.get(k, 0) + n


def _top(counter, n=10):
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n])


@metric
def permissions_denials(ctx):
    sess = list(ctx.sessions)  # unattended runs too: pipeline denials are what the triage is for
    by_kind = {"main": {}, "subagent": {}}
    by_sk = {"interactive": 0, "unattended": 0}
    reasons, proj, shapes, ro_prog, counts = {}, {}, {}, {}, []
    for s in sess:
        n = 0
        sk = "interactive" if s["interactive"] else "unattended"
        threads = [("main", s)] + [("subagent", u) for u in s.get("subs", [])]
        for who, th in threads:
            for d in th.get("denials", []):
                n += 1
                _bump(by_kind[who], d["kind"])
                _bump(by_sk, sk)
                _bump(proj.setdefault(s["project"], {}), d["kind"])
                if d.get("reason"):
                    _bump(reasons, d["reason"])
                if d["kind"] in SHAPE_KINDS and d.get("tool") in SHELL_TOOLS and d.get("cmd"):
                    shape, names = classify(d["cmd"])
                    _bump(shapes, shape)
                    if shape == "read_only":
                        for nm in names:
                            _bump(ro_prog, nm)
        if n:
            counts.append((n, s))
    total = sum(sum(v.values()) for v in by_kind.values())
    if not total:
        return {"permissions.denials": insufficient("no tool denials recorded", n=0)}
    top_proj = sorted(proj.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))[:10]
    counts.sort(key=lambda x: -x[0])
    return {"permissions.denials": {
        "n": total, "by_kind": by_kind, "by_session_kind": by_sk, "classifier_reasons": _top(reasons, 15),
        "by_project": [dict(project=p, **dict(sorted(k.items()))) for p, k in top_proj],
        "by_shape": dict(shapes, note="shell commands denied by permission-rule or user-rejected"),
        "read_only_top": _top(ro_prog),
        "examples": [example(s, "%d denials" % n) for n, s in counts[:10]]}}
