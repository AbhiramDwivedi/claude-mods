#!/usr/bin/env python3
"""workflow-audit: measure how Claude Code is used, from local transcripts.

  audit.py preflight
  audit.py run [--projects-dir P] [--days N] [--out DIR] [--exclude-session ID ...]

See plugins/workflow-audit/CONTRACT.md. Python 3.9+, standard library only.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wa_model  # noqa: E402
import wa_registry  # noqa: E402
from wa_common import day, home_dir  # noqa: E402
from wa_prices import Prices  # noqa: E402

# Step 1b appends its modules here.
METRIC_MODULES = ["wa_m_meta", "wa_m_cost", "wa_m_agents"]

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PRICES = os.path.join(HERE, "..", "catalog", "prices.json")
EXIT_NO_TRANSCRIPTS, EXIT_BAD_ARGS = 2, 3


class ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgError(message)


def build_parser():
    ap = _Parser(prog="audit.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("preflight")
    run = sub.add_parser("run")
    run.add_argument("--projects-dir")
    run.add_argument("--days", type=int, default=30)
    run.add_argument("--out")
    run.add_argument("--exclude-session", action="extend", nargs="+", default=[], metavar="ID")
    # Test hooks, not part of the documented interface.
    run.add_argument("--prices", help=argparse.SUPPRESS)
    run.add_argument("--cache-dir", help=argparse.SUPPRESS)
    return ap


def default_projects_dir():
    return os.path.join(home_dir(), ".claude", "projects")


def workflow_dir():
    return os.path.join(home_dir(), ".claude", "workflow-audit")


def preflight():
    pdir = default_projects_dir()
    files = []
    for root, _dirs, names in os.walk(pdir):
        for n in names:
            if n.endswith(".jsonl"):
                files.append(os.path.join(root, n))
    mtimes = []
    for f in files:
        try:
            mtimes.append(os.stat(f).st_mtime)
        except OSError:
            pass
    ids = [os.path.basename(f)[:-6] for f in files if os.path.basename(os.path.dirname(f)) != "subagents"]
    return {
        "python": sys.version.split()[0],
        "projects_dir": pdir,
        "projects_dir_exists": os.path.isdir(pdir),
        "transcript_files": len(files),
        "subagent_files": sum(1 for f in files if os.path.basename(os.path.dirname(f)) == "subagents"),
        "oldest": day(min(mtimes)) if mtimes else None,
        "newest": day(max(mtimes)) if mtimes else None,
        "insights": wa_model.insights_info(home_dir(), ids),
        "prices_file": os.path.isfile(DEFAULT_PRICES),
    }


def run(args):
    if args.days < 1:
        raise ArgError("--days must be a positive number")
    projects = os.path.abspath(os.path.expanduser(args.projects_dir)) if args.projects_dir else default_projects_dir()
    prices_path = args.prices or DEFAULT_PRICES
    try:
        prices = Prices.load(prices_path)
    except (OSError, ValueError) as e:
        raise ArgError("cannot read prices file %s: %s" % (os.path.basename(prices_path), e.__class__.__name__))
    out_dir = os.path.abspath(os.path.expanduser(args.out)) if args.out else os.path.join(
        workflow_dir(), "runs", datetime.now().strftime("%Y%m%d-%H%M%S"))
    cache_dir = args.cache_dir or os.path.join(workflow_dir(), "cache")

    ctx = wa_model.build_context(projects, args.days, cache_dir, prices, exclude_ids=args.exclude_session)
    if not ctx.n_files:
        sys.stderr.write("No transcripts found in %s within the last %d days.\n" % (projects, args.days))
        return EXIT_NO_TRANSCRIPTS
    metrics = wa_registry.run_all(ctx, METRIC_MODULES)
    os.makedirs(os.path.join(out_dir, "samples"), exist_ok=True)
    with open(os.path.join(out_dir, "metrics.json"), "w", encoding="utf8") as f:
        json.dump(metrics, f, indent=1, ensure_ascii=False)
    print(out_dir)
    return 0


def main(argv=None):
    ap = build_parser()
    try:
        args = ap.parse_args(argv)
        if args.cmd == "preflight":
            print(json.dumps(preflight(), indent=1))
            return 0
        if args.cmd == "run":
            return run(args)
        raise ArgError("usage: audit.py preflight | run [--projects-dir P] [--days N] [--out DIR] [--exclude-session ID ...]")
    except ArgError as e:
        sys.stderr.write("Error: %s\n" % e)
        return EXIT_BAD_ARGS


if __name__ == "__main__":
    sys.exit(main())
