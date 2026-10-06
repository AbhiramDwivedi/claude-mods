"""Shared test setup: path wiring, fixture locations, a tiny synthetic-transcript writer."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

FIXTURES = os.path.join(HERE, "fixtures")
PROJECTS = os.path.join(FIXTURES, "projects")
PRICES = os.path.join(FIXTURES, "prices.json")
MAIN_ID = "11111111-aaaa-4aaa-8aaa-000000000001"
SELF_ID = "22222222-bbbb-4bbb-8bbb-000000000002"
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def stamp(minutes):
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def usage(cr, cc, one_hour, inp=10, out=5):
    split = {"ephemeral_5m_input_tokens": 0 if one_hour else cc, "ephemeral_1h_input_tokens": cc if one_hour else 0}
    return {"input_tokens": inp, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc,
            "output_tokens": out, "cache_creation": split}


def write_thread(path, session, steps, sub=False, one_hour=True):
    """steps: dicts with t (minutes), cr, cc and optional model, ver, compact (bool), before (list of record dicts
    with a 't' key). One assistant request per step."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    base = {"sessionId": session, "cwd": "C:/work/synthetic", "isSidechain": sub, "entrypoint": "cli"}
    with open(path, "w", encoding="utf8") as f:
        def put(rec):
            f.write(json.dumps(rec) + "\n")
        put(dict(base, type="user", timestamp=stamp(0), version="1.0", message={"role": "user", "content": "start the task"}))
        for i, s in enumerate(steps):
            if s.get("compact"):
                put(dict(base, type="system", subtype="compact_boundary", timestamp=stamp(s["t"] - 0.1)))
            for b in s.get("before", []):
                put(dict(base, version="1.0", **{k: v for k, v in b.items() if k != "t"}, timestamp=stamp(b["t"])))
            put(dict(base, type="assistant", timestamp=stamp(s["t"]), version=s.get("ver", "1.0"),
                     message={"id": "req%d" % i, "role": "assistant", "model": s.get("model", "claude-test"),
                              "content": [{"type": "text", "text": "step %d" % i}],
                              "usage": usage(s["cr"], s["cc"], one_hour)}))


def temp_projects():
    d = tempfile.TemporaryDirectory()
    return d, os.path.join(d.name, "projects"), os.path.join(d.name, "cache")


def warm(t, n=3, start=1, step=1, big=100000):
    """n ordinary requests: warm cache, small writes."""
    return [dict(t=start + i * step, cr=big, cc=1000) for i in range(n)]
