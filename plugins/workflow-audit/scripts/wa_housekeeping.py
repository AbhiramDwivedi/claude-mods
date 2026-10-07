"""Keep workflow-audit from holding conversation text longer than Claude Code itself does.

Claude Code deletes transcripts after `cleanupPeriodDays` (30 by default). The parse cache keeps the human
messages it read, and each run's samples/ keeps excerpts, so both would outlive the transcripts. Each run:
- drops cache entries whose transcript no longer exists;
- deletes samples/ from run folders older than the retention period. metrics.json, experiments.json,
  sample-verdicts.json and report.md stay: the follow-up needs them, and the report is the person's record.
"""
import json
import os
import re
import shutil
import time

DEFAULT_RETENTION_DAYS = 30
RUN_NAME = re.compile(r"^(\d{8})-(\d{6})$")


def retention_days(home):
    """cleanupPeriodDays from ~/.claude/settings.json, else Claude Code's default of 30."""
    try:
        with open(os.path.join(home, ".claude", "settings.json"), encoding="utf8") as f:
            value = json.load(f).get("cleanupPeriodDays")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return value
    except (OSError, ValueError, AttributeError):
        pass
    return DEFAULT_RETENTION_DAYS


def prune_cache(cache_dir):
    """Delete cache entries whose source transcript is gone. Returns how many were deleted."""
    removed = 0
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return 0
    for n in names:
        if not n.endswith(".json"):
            continue
        p = os.path.join(cache_dir, n)
        try:
            with open(p, encoding="utf8") as f:
                key = json.load(f).get("key")
            source = key[1] if isinstance(key, list) and len(key) > 1 else None
        except (OSError, ValueError, AttributeError):
            source = None  # unreadable entry: it would be re-parsed anyway, so drop it
        if source and os.path.exists(source):
            continue
        try:
            os.remove(p)
            removed += 1
        except OSError:
            pass
    return removed


def run_age_days(run_dir, now):
    """Age of a run folder from its YYYYMMDD-HHMMSS name, else from its mtime."""
    m = RUN_NAME.match(os.path.basename(run_dir))
    if m:
        try:
            return (now - time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))) / 86400
        except (ValueError, OverflowError):
            pass
    try:
        return (now - os.stat(run_dir).st_mtime) / 86400
    except OSError:
        return 0


def expire_samples(runs_dir, days, current_dir, now=None):
    """Delete samples/ in run folders under runs_dir older than `days`. Returns how many folders were cleared."""
    now = now or time.time()
    cleared = 0
    try:
        names = os.listdir(runs_dir)
    except OSError:
        return 0
    cur = os.path.normcase(os.path.abspath(current_dir)) if current_dir else None
    for n in names:
        d = os.path.join(runs_dir, n)
        if not RUN_NAME.match(n) or os.path.normcase(os.path.abspath(d)) == cur:
            continue
        samples = os.path.join(d, "samples")
        if os.path.isdir(samples) and run_age_days(d, now) > days:
            shutil.rmtree(samples, ignore_errors=True)
            cleared += 1
    return cleared


def tidy(home, cache_dir, runs_dir, current_dir):
    days = retention_days(home)
    return {"retention_days": days, "cache_entries_removed": prune_cache(cache_dir),
            "sample_folders_expired": expire_samples(runs_dir, days, current_dir)}
