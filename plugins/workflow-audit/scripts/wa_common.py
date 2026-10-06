"""Small helpers shared by the workflow-audit modules."""
import os
import re
from datetime import datetime, timezone


def parse_ts(s):
    """ISO timestamp string -> epoch seconds, or None."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def day(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") if t else None


def iso_week(t):
    y, w, _ = datetime.fromtimestamp(t, timezone.utc).isocalendar()
    return "%d-W%02d" % (y, w)


def project_name(cwd, folder=""):
    """Readable project name: last path part of cwd, else of the folder slug."""
    if cwd:
        parts = path_parts(cwd)
        if parts:
            return parts[-1]
    return folder.split("-")[-1] if folder else "unknown"


def path_parts(cwd):
    return [p for p in re.split(r"[\\/]+", cwd or "") if p]


def percentile(values, q):
    """Nearest-rank percentile (q in 0..100) of a list, or None."""
    v = sorted(values)
    if not v:
        return None
    return v[min(len(v) - 1, max(0, int(round(q / 100.0 * len(v) + 0.5)) - 1))]


def home_dir():
    return os.path.expanduser("~")


def pct(x, total):
    return round(100.0 * x / total, 3) if total else 0.0


_SECRET_PATTERNS = [
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghs|github_pat|xox[a-z]|AKIA|AIza)[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|apikey)(\s*[=:]\s*)[^\s\"',;]+"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
]
_LONG_RUN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


def _long_run(m):
    s = m.group(0)
    return "[redacted]" if re.search(r"\d", s) and re.search(r"[A-Za-z]", s) else s


def redact(text):
    """Replace secret-looking strings with [redacted]."""
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 2:
            text = pat.sub(lambda m: m.group(1) + m.group(2) + "[redacted]", text)
        else:
            text = pat.sub("[redacted]", text)
    return _LONG_RUN.sub(_long_run, text)
