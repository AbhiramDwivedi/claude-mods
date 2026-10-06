"""Metric registry. A metric function takes the Ctx and returns {dotted.key: value}.

To add metrics (step 1b): write a module with @metric functions and append its name to
METRIC_MODULES in audit.py. Nothing else changes.
"""
import importlib

_METRICS = []


def metric(fn):
    _METRICS.append(fn)
    return fn


def insufficient(reason, **extra):
    return dict(extra, insufficient=True, reason=reason)


def example(session, value):
    """One example row for a metric that points at sessions."""
    return {"session": session["id"], "session8": session["id8"], "project": session["project"],
            "date": session["date"], "value": value}


def _set_nested(root, key, value):
    parts = key.split(".")
    for p in parts[:-1]:
        root = root.setdefault(p, {})
    root[parts[-1]] = value


def run_all(ctx, modules):
    for m in modules:
        importlib.import_module(m)
    out = {}
    for fn in _METRICS:
        for key, value in fn(ctx).items():
            _set_nested(out, key, value)
    return out
