import contextlib
import io
import json
import os
import tempfile
import unittest

import helpers
from helpers import MAIN_ID, PRICES, PROJECTS, SELF_ID
import audit
import wa_model
import wa_registry
from wa_prices import Prices

NOW = helpers.T0.timestamp() + 86400


def build(exclude=()):
    with tempfile.TemporaryDirectory() as cache:
        ctx = wa_model.build_context(PROJECTS, 36500, cache, Prices.load(PRICES), exclude_ids=exclude, now=NOW)
    return ctx


class Exclusion(unittest.TestCase):
    def test_own_workflow_audit_session_is_excluded(self):
        ctx = build()
        self.assertEqual([s["id"] for s in ctx.sessions], [MAIN_ID])
        self.assertEqual(ctx.excluded, [{"session": SELF_ID, "reason": "own /workflow-audit session"}])

    def test_exclude_session_by_id_drops_its_subagents_too(self):
        ctx = build(exclude=[MAIN_ID[:8]])
        self.assertEqual(ctx.sessions, [])
        self.assertEqual(ctx.subs, [])
        self.assertEqual(len(ctx.excluded), 2)


class Agents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = wa_registry.run_all(build(), audit.METRIC_MODULES)

    def test_explicit_model_rate(self):
        r = self.m["agents"]["explicit_model_rate"]
        self.assertEqual((r["n"], r["explicit"], r["overall"]), (2, 1, 0.5))
        self.assertEqual(r["by_week"]["2026-W40"]["rate"], 0.5)

    def test_child_model_comes_from_the_subagent_file_and_is_inherited(self):
        bm = self.m["agents"]["by_model"]["models"]
        self.assertEqual(bm, {"claude-test-sub": {"total": 1, "explicit": 0, "inherited": 1}})

    def test_size(self):
        s = self.m["agents"]["size"]
        self.assertEqual((s["n"], s["max"], s["over_200k"]), (1, 302, 0))

    def test_meta_and_cost(self):
        meta = self.m["meta"]
        self.assertEqual(meta["counts"]["main_sessions"], 1)
        self.assertEqual(meta["counts"]["subagents"], 1)
        self.assertEqual(meta["prices"]["source"], "fixture")
        self.assertGreater(self.m["cost"]["total"]["usd"], 0)
        self.assertAlmostEqual(self.m["cost"]["total"]["usd"],
                               self.m["cost"]["total"]["main"] + self.m["cost"]["total"]["subagent"], places=2)


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = audit.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_run_writes_metrics_and_prints_run_dir_last(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "run")
            code, stdout, _ = self.run_cli("run", "--projects-dir", PROJECTS, "--days", "36500", "--out", out,
                                           "--prices", PRICES, "--cache-dir", os.path.join(d, "c"))
            self.assertEqual(code, 0)
            self.assertEqual(stdout.strip().splitlines()[-1], out)
            with open(os.path.join(out, "metrics.json"), encoding="utf8") as f:
                m = json.load(f)
            self.assertIn("waste_pct", m["cost"]["cache"])

    def test_cached_run_does_not_parse_again(self):
        with tempfile.TemporaryDirectory() as d:
            args = ["run", "--projects-dir", PROJECTS, "--days", "36500", "--prices", PRICES,
                    "--cache-dir", os.path.join(d, "c")]
            self.run_cli(*args, "--out", os.path.join(d, "r1"))
            self.run_cli(*args, "--out", os.path.join(d, "r2"))
            with open(os.path.join(d, "r2", "metrics.json"), encoding="utf8") as f:
                cache = json.load(f)["meta"]["cache"]
            self.assertEqual(cache["parsed"], 0)
            self.assertEqual(cache["hits"], 3)

    def test_no_transcripts_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            code, _, err = self.run_cli("run", "--projects-dir", d, "--out", os.path.join(d, "o"), "--prices", PRICES,
                                        "--cache-dir", os.path.join(d, "c"))
            self.assertEqual(code, 2)
            self.assertIn("No transcripts", err)

    def test_bad_arguments_exit_3(self):
        code, _, err = self.run_cli("run", "--days", "abc")
        self.assertEqual(code, 3)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertEqual(self.run_cli("run", "--days", "0")[0], 3)
        self.assertEqual(self.run_cli("bogus")[0], 3)


if __name__ == "__main__":
    unittest.main()
