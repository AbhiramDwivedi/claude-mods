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
        parts = [p for p in re.split(r"[\/]+", cwd) if p]
        if parts:
            return parts[-1]
    return folder.split("-")[-1] if folder else "unknown"


def home_dir():
    return os.path.expanduser("~")


def pct(x, total):
    return round(100.0 * x / total, 3) if total else 0.0
