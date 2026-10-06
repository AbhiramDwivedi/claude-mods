"""Step 1b metrics: corrections, streaks, verification, CLAUDE.md, samples, redaction, followup, project names."""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

import helpers  # noqa: F401  (puts scripts/ on sys.path)
import wa_followup
import wa_m_context
import wa_m_rework
import wa_m_usage
import wa_model
from wa_common import project_name, redact


def human(text, kind="typed", tail="", cmd=None):
    h = {"ts": 1000.0, "kind": kind, "text": text, "tail": tail}
    if cmd:
        h["cmd"] = cmd
    return h


def session(sid="aaaaaaaa-0000", humans=(), tools=(), cwd="C:/work/p", **kw):
    s = {"id": sid, "id8": sid[:8], "project": project_name(cwd), "date": "2026-10-01", "interactive": True,
         "unattended": False, "subs": [], "agent_ids": {}, "humans": list(humans), "tools": list(tools), "modes": [],
         "interrupts": [], "rejections": [], "compactions": [], "agent_calls": [], "cwd": cwd, "requests": []}
    s.update(kw)
    return s


def ctx_of(*sessions, **kw):
    return SimpleNamespace(sessions=list(sessions), home=kw.get("home", "/nonexistent-home"), out_dir=kw.get("out_dir"))


def tool(name, **kw):
    return dict(ts=1.0, name=name, **kw)


class Corrections(unittest.TestCase):
    def test_tight_hits_and_misses(self):
        for t in ("no, that's wrong", "Wait. use the other file", "actually do it differently", "I said tabs",
                  "why did you delete it", "Stop"):
            self.assertTrue(wa_m_rework.TIGHT.search(t), t)
        for t in ("don't touch the config", "do not commit yet", "now run the tests", "note that x", "nothing else"):
            self.assertFalse(wa_m_rework.TIGHT.search(t), t)

    def test_dont_instruction_counts_loose_not_tight(self):
        s = session(humans=[human("build it"), human("don't use classes"), human("looks fine")])
        a = wa_m_rework.analyse(s)
        self.assertEqual((a["tight"], a["loose"], a["non_first"]), (0, 1, 2))

    def test_first_message_and_commands_excluded(self):
        s = session(humans=[human("no, wrong start"), human("", kind="command", cmd="/clear"), human("no that's wrong")])
        a = wa_m_rework.analyse(s)
        self.assertEqual((a["non_first"], a["tight"]), (1, 1))

    def test_rate_overall_and_unattended_excluded(self):
        a = session("a1111111", humans=[human("go"), human("no"), human("fine"), human("ok")])
        b = session("b2222222", humans=[human("no")], interactive=False, unattended=True)
        m = wa_m_rework.correction_rate(ctx_of(a, b))["rework.correction_rate"]
        self.assertEqual((m["n"], m["tight"], m["non_first_messages"], m["overall"]), (1, 1, 3, 0.3333))
        self.assertIn("55%", m["precision_note"])
        self.assertEqual(m["by_project"]["p"]["tight"], 1)

    def test_streaks(self):
        s = session(humans=[human("go"), human("no"), human("wrong again"), human("ok"), human("no")])
        t = session("b2222222", humans=[human("go"), human("no"), human("fine"), human("no")])
        m = wa_m_rework.correction_streaks(ctx_of(s, t))["rework.correction_streaks"]
        self.assertEqual(m["sessions"], 1)
        self.assertEqual(m["top"][0]["value"], 2)
        self.assertEqual(m["top"][0]["examples"], ["no", "wrong again"])


class Auc(unittest.TestCase):
    def test_auc_values(self):
        self.assertEqual(wa_m_rework.auc([3, 4], [1, 2]), 1.0)
        self.assertEqual(wa_m_rework.auc([1, 2], [3, 4]), 0.0)
        self.assertEqual(wa_m_rework.auc([1, 2], [1, 2]), 0.5)
        self.assertIsNone(wa_m_rework.auc([], [1]))

    def test_insights_join_and_threshold(self):
        with tempfile.TemporaryDirectory() as home:
            d = os.path.join(home, ".claude", "usage-data", "facets")
            os.makedirs(d)
            sess = []
            for i in range(24):
                sid = "s%07d-0000" % i
                bad = i < 8
                sess.append(session(sid, humans=[human("go")] + [human("no")] * (2 if bad else 0) + [human("ok")] * 2))
                with open(os.path.join(d, sid + ".json"), "w") as f:
                    json.dump({"outcome": "partially_achieved" if bad else "fully_achieved",
                               "friction_counts": {"wrong_approach": 1} if bad else {},
                               "user_satisfaction_counts": {"dissatisfied": 1} if bad else {}}, f)
            m = wa_m_rework.insights(ctx_of(*sess, home=home))["rework.insights"]
            self.assertEqual(m["n_joined"], 24)
            self.assertEqual(m["outcomes"], {"fully_achieved": 16, "partially_achieved": 8})
            self.assertEqual(m["friction"], {"wrong_approach": 8})
            self.assertEqual(m["auc"]["dissatisfied_vs_not"]["tight_rate"], 1.0)
            few = wa_m_rework.insights(ctx_of(*sess[:10], home=home))["rework.insights"]
            self.assertTrue(few["auc"]["insufficient"])
            none = wa_m_rework.insights(ctx_of(*sess, home=home + "x"))["rework.insights"]
            self.assertTrue(none["insufficient"])


class Verification(unittest.TestCase):
    def run_check(self, *sessions):
        return wa_m_usage.check_after_last_edit(ctx_of(*sessions))["verification.check_after_last_edit"]

    def test_check_after_last_edit(self):
        ok = session("a1111111", tools=[tool("Edit", path="x"), tool("Bash", cmd="python -m pytest -q")])
        late_edit = session("b2222222", tools=[tool("Bash", cmd="npm test"), tool("Write", path="y")])
        none = session("c3333333", tools=[tool("Edit", path="x"), tool("Bash", cmd="ls")])
        readonly = session("d4444444", tools=[tool("Read")])
        m = self.run_check(ok, late_edit, none, readonly)
        self.assertEqual((m["n"], m["checked_after_last_edit"], m["share"]), (3, 1, 0.3333))
        self.assertEqual(m["sessions_with_no_check_command"], 2)  # none + readonly

    def test_patterns(self):
        for c in ("pytest", "cargo test --all", "go vet ./...", "pnpm run build", "ruff check .", "tsc --noEmit",
                  "claude plugin validate .", "dotnet build", "make test", "python -m unittest discover"):
            self.assertTrue(wa_m_usage.is_check(c), c)
        for c in ("ls -la", "git status", "npm install", "echo contest"):
            self.assertFalse(wa_m_usage.is_check(c), c)

    def test_no_editing_sessions_is_insufficient(self):
        self.assertTrue(self.run_check(session(tools=[tool("Read")]))["insufficient"])


class Usage(unittest.TestCase):
    def test_practices(self):
        s = session(humans=[human("a"), human("b", kind="queued"), human("", kind="command", cmd="/clear"),
                            human("", kind="command", cmd="/compact"), human("", kind="command", cmd="/compact")],
                    tools=[tool("Skill", skill="humanizer"), tool("EnterPlanMode"),
                           tool("Bash", cmd="git worktree add ../x")],
                    modes=[[1, "auto"], [2, "plan"]], interrupts=[1, 2])
        m = wa_m_usage.practices_usage(ctx_of(s))["practices.usage"]
        self.assertEqual(m["plan_mode"], {"uses": 2, "sessions": 1})
        self.assertEqual(m["permission_modes"]["sessions_by_mode_seen"], {"auto": 1, "plan": 1})
        self.assertEqual((m["interrupts"], m["queued_messages"], m["worktree_sessions"]), (2, 1, 1))
        self.assertEqual(m["commands"], {"/clear": 1, "/rewind": 0, "/compact": 2})
        self.assertEqual(m["skills_used"], {"humanizer": 1})
        self.assertEqual(m["top_slash_commands"]["/compact"], 2)

    def test_shape(self):
        hs = [human("a"), human("b")]
        for h in hs:
            h["ts"] = 100.0
        s = session(humans=hs, compactions=[1, 2],
                    requests=[{"ts": 100.0}, {"ts": 400.0}, {"ts": 3100.0}, {"ts": 3160.0}])
        m = wa_m_usage.sessions_shape(ctx_of(s))["sessions.shape"]
        self.assertEqual(m["active_minutes_median"], 6.0)  # 5 min + 1 min; the 45 min gap is idle
        self.assertEqual(m["sessions_with_2plus_compactions"], 1)
        self.assertEqual(m["human_messages"]["median"], 2.0)


class ClaudeMd(unittest.TestCase):
    def test_line_counts_and_missing_files(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as proj, \
                tempfile.TemporaryDirectory() as bare:
            os.makedirs(os.path.join(home, ".claude"))
            os.makedirs(os.path.join(proj, ".claude"))
            for path, n in ((os.path.join(home, ".claude", "CLAUDE.md"), 100), (os.path.join(proj, "CLAUDE.md"), 60),
                            (os.path.join(proj, ".claude", "CLAUDE.md"), 30), (os.path.join(proj, "CLAUDE.local.md"), 20)):
                with open(path, "w") as f:
                    f.write("line\n" * n)
            a = session("a1111111", cwd=proj)
            b = session("b2222222", cwd=bare)
            c = session("c3333333", cwd=bare)
            m = wa_m_context.claude_md(ctx_of(a, b, c, home=home))["context.claude_md"]
            self.assertEqual(m["global"]["lines"], 100)
            row = m["projects"][a["project"]]
            self.assertEqual(row["project_lines"], 110)
            self.assertEqual(m["projects_over_200"], [a["project"]])
            self.assertEqual(len(m["paths"]), 4)  # 3 project files + global
            self.assertEqual(m["projects"][b["project"]]["project_lines"], 0)
            self.assertEqual(m["avg_lines_loaded"], round((210 + 100 + 100) / 3, 1))


class Redaction(unittest.TestCase):
    def test_redact(self):
        text = ("key sk-abcdefghijklmnopqrstuvwx and password=hunter2 and token: abc123 and "
                "hex " + "a1" * 20 + " and b64 Zm9vYmFy" * 1 + "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo0MTIz ok")
        out = redact(text)
        for leaked in ("sk-abcdef", "hunter2", "abc123", "a1a1a1a1", "QUJDREVG"):
            self.assertNotIn(leaked, out)
        self.assertIn("password=[redacted]", out)
        self.assertEqual(redact("plain text, a-long-readable-hyphenated-project-slug-name here"),
                         "plain text, a-long-readable-hyphenated-project-slug-name here")


class Samples(unittest.TestCase):
    def test_sample_files(self):
        secret = "sk-" + "x" * 30
        s = session("a1111111-0000", humans=[
            human("go"), human("no, wrong file", tail="I edited a.py " + secret),
            human("nope, " + "y" * 700, tail="Done."), human("fine")])
        weak = session("b2222222", humans=[human("go"), human("no")])
        with tempfile.TemporaryDirectory() as out:
            rows = wa_m_rework.samples(ctx_of(s, weak, out_dir=out))["samples"]
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual((r["session8"], r["corrections"], r["project"]), ("a1111111", 2, "p"))
            self.assertTrue(os.path.isabs(r["file"]))
            self.assertTrue(r["file"].endswith("01-a1111111.md"))
            with open(r["file"], encoding="utf8") as f:
                body = f.read()
            self.assertIn("human messages: 4", body)
            self.assertIn("flagged moments: 2 (tight pattern: 2)", body)
            self.assertIn("Claude (before): I edited a.py [redacted]", body)
            self.assertIn("Person: no, wrong file", body)
            self.assertNotIn(secret, body)
            person = [ln for ln in body.splitlines() if ln.startswith("Person: nope")][0]
            self.assertLessEqual(len(person), len("Person: ") + 600)

    def test_at_most_8(self):
        sess = [session("s%07d-0" % i, humans=[human("go"), human("no"), human("no")]) for i in range(11)]
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(len(wa_m_rework.samples(ctx_of(*sess, out_dir=out))["samples"]), 8)


class Followup(unittest.TestCase):
    METRICS = {"agents": {"explicit_model_rate": {"overall": 0.97}}, "cost": {"cache": {"waste_pct": {"total": 4.0},
               "x": {"insufficient": True, "reason": "none"}}}}

    def test_resolve_and_judge(self):
        exps = [
            {"id": "a", "metric": "agents.explicit_model_rate", "path": "overall", "baseline": 0.7, "target": 0.95,
             "direction": "up", "committed": "2026-10-01", "change": "c"},
            {"id": "b", "metric": "cost.cache.waste_pct", "path": "total", "baseline": 9, "target": 3,
             "direction": "down"},
            {"id": "c", "metric": "nope.metric", "path": "x", "target": 1, "direction": "up"},
            {"id": "d", "metric": "cost.cache.x", "path": "", "target": 1, "direction": "up"},
        ]
        with tempfile.TemporaryDirectory() as runs:
            old, new = os.path.join(runs, "20261001-000000"), os.path.join(runs, "20261006-000000")
            os.makedirs(old)
            os.makedirs(new)
            with open(os.path.join(old, "experiments.json"), "w") as f:
                json.dump(exps, f)
            self.assertEqual(wa_followup.find_previous([runs], new), old)
            self.assertIsNone(wa_followup.find_previous([runs], old))
            rows = wa_followup.followup(self.METRICS, old)
        by = {r["id"]: r for r in rows}
        self.assertEqual((by["a"]["now"], by["a"]["met"]), (0.97, True))
        self.assertEqual((by["b"]["now"], by["b"]["met"]), (4.0, False))
        self.assertIsNone(by["c"]["now"])
        self.assertIsNone(by["c"]["met"])
        self.assertIn("no value", by["c"]["reason"])
        self.assertIn("too little data", by["d"]["reason"])
        self.assertEqual(by["a"]["change"], "c")


class ProjectNames(unittest.TestCase):
    def test_last_part_both_separators(self):
        self.assertEqual(project_name("C:\\sw\\resume"), "resume")
        self.assertEqual(project_name("/home/abd/x/"), "x")
        self.assertEqual(project_name(None, "C--sw-foo"), "foo")

    def test_duplicates_get_parent(self):
        a = session("a1", cwd="C:\\sw\\app")
        b = session("b2", cwd="D:\\other\\app")
        c = session("c3", cwd="C:\\sw\\solo")
        wa_model.assign_project_names([a, b, c])
        self.assertEqual((a["project"], b["project"], c["project"]), ("app (sw)", "app (other)", "solo"))


if __name__ == "__main__":
    unittest.main()
