"""Metrics version 7: denials, effort, review after long edit runs, rewinds after untracked edits, commands used."""
import unittest

import helpers  # noqa: F401  (puts scripts/ on sys.path)
import wa_m_effort
import wa_m_permissions
import wa_m_usage
from test_step1b import ctx_of, human, session


def tool(name, ts=1.0, **kw):
    return dict(ts=ts, name=name, **kw)


def at(h, ts):
    h["ts"] = ts
    return h


def edits(n, start=1):
    return [tool("Edit", ts=float(start + i), path="a.py") for i in range(n)]


class Shapes(unittest.TestCase):
    def test_each_shape(self):
        cases = {
            "cat a | head": "read_only",
            "git status": "read_only",
            "cd src && git diff": "read_only",
            "ls 2>&1": "read_only",
            "python bin/run.py && echo done": "chained",
            "python -c 'a; b'": "inline_interpreter",
            "node -e \"x\"": "inline_interpreter",
            "python C:/x/bin/a.py": "absolute_path",
            "C:/x/bin/tool.exe --go": "absolute_path",
            "npm run build": "other",
        }
        for cmd, shape in cases.items():
            self.assertEqual(wa_m_permissions.classify(cmd)[0], shape, cmd)

    def test_redirect_to_a_file_is_not_read_only(self):
        self.assertNotEqual(wa_m_permissions.classify("cat a > b")[0], "read_only")


class Denials(unittest.TestCase):
    def test_unattended_sessions_count_and_split(self):
        den = dict(ts=1.0, kind="permission-rule", tool="Bash", cmd="cat a | head")
        a = session("aaaaaaaa-1", denials=[den])
        b = session("bbbbbbbb-2", interactive=False, unattended=True, denials=[dict(den, cmd="python -c 'x'")],
                    subs=[{"denials": [dict(den, kind="automode-blocked", reason="Git Destructive")], "requests": []}])
        m = wa_m_permissions.permissions_denials(ctx_of(a, b))["permissions.denials"]
        self.assertEqual(m["n"], 3)
        self.assertEqual(m["by_session_kind"], {"interactive": 1, "unattended": 2})
        self.assertEqual(m["by_kind"], {"main": {"permission-rule": 2}, "subagent": {"automode-blocked": 1}})
        self.assertEqual((m["by_shape"]["read_only"], m["by_shape"]["inline_interpreter"]), (1, 1))
        self.assertEqual(m["classifier_reasons"], {"Git Destructive": 1})
        self.assertEqual(m["read_only_top"], {"cat": 1, "head": 1})

    def test_no_denials_is_insufficient(self):
        m = wa_m_permissions.permissions_denials(ctx_of(session(denials=[])))["permissions.denials"]
        self.assertTrue(m["insufficient"])


class Effort(unittest.TestCase):
    def test_most_common_effort_per_session_and_unknown(self):
        a = session("aaaaaaaa-1", requests=[dict(model="opus", eff="high"), dict(model="opus", eff="high"),
                                            dict(model="opus", eff="medium")],
                    humans=[human("ultrathink about it"), human("", kind="command", cmd="/effort")])
        b = session("bbbbbbbb-2", requests=[dict(model="opus")],
                    subs=[{"requests": [dict(model="sonnet", eff="low")]}])
        m = wa_m_effort.effort_by_model(ctx_of(a, b))["effort.by_model"]
        self.assertEqual(m["main"], {"opus": {"high": 1, "unknown": 1}})
        self.assertEqual(m["subagent"], {"sonnet": {"low": 1}})
        self.assertEqual((m["ultrathink_messages"], m["effort_commands"]), (1, 1))


class ReviewAfterEdits(unittest.TestCase):
    def run_metric(self, *sessions):
        return wa_m_usage.review_after_edits(ctx_of(*sessions))["verification.review_after_edits"]

    def test_reviewed_unreviewed_and_short_runs(self):
        hs = [at(human("build it"), 0.0), at(human("thanks"), 1000.0)]
        reviewed = session("aaaaaaaa-1", humans=hs, tools=edits(20) + [tool("Agent", ts=30.0, desc="Review the diff")])
        unreviewed = session("bbbbbbbb-2", humans=[dict(h) for h in hs], tools=edits(25))
        short = session("cccccccc-3", humans=[dict(h) for h in hs], tools=edits(19))
        m = self.run_metric(reviewed, unreviewed, short)
        self.assertEqual((m["long_runs"], m["reviewed_runs"], m["sessions_with_long_runs"]), (2, 1, 2))
        self.assertEqual(m["examples"][0]["session"], "bbbbbbbb-2")

    def test_subagent_edits_count_and_review_request_counts(self):
        hs = [at(human("build it"), 0.0), at(human("now review it"), 1000.0)]
        s = session("aaaaaaaa-1", humans=hs, tools=edits(5), subs=[{"tools": edits(15, start=100)}])
        m = self.run_metric(s)
        self.assertEqual((m["long_runs"], m["reviewed_runs"]), (1, 1))


class Rewinds(unittest.TestCase):
    def stats(self, *sessions):
        return wa_m_usage.practices_usage(ctx_of(*sessions))["practices.usage"]["rewinds_after_untracked_edits"]

    def rewind_session(self, sid, tools):
        hs = [at(human("go"), 0.0), at(human("", kind="command", cmd="/rewind"), 100.0)]
        return session(sid, humans=hs, tools=tools)

    def test_rewind_after_bash_rm_with_and_without_baseline(self):
        bare = self.rewind_session("aaaaaaaa-1", [tool("Bash", ts=50.0, cmd="rm -rf build")])
        based = self.rewind_session("bbbbbbbb-2", [tool("Bash", ts=-10.0, cmd="git commit -m wip"),
                                                   tool("Bash", ts=50.0, cmd="rm -rf build")])
        safe = self.rewind_session("cccccccc-3", [tool("Read", ts=50.0, path="a.py")])
        self.assertEqual(self.stats(bare, based, safe), {"rewinds": 3, "after_untracked_edits": 2, "with_git_baseline": 1})


class CommandsUsed(unittest.TestCase):
    def test_includes_commands_outside_the_top_ten(self):
        hs = [human("", kind="command", cmd="/c%02d" % i) for i in range(10) for _ in range(2)]
        hs.append(human("", kind="command", cmd="/rare"))
        s = session(humans=hs, tools=[tool("Skill", skill="code-review")])
        m = wa_m_usage.practices_usage(ctx_of(s))["practices.usage"]
        self.assertNotIn("/rare", m["top_slash_commands"])
        self.assertEqual((m["commands_used"]["/rare"], m["commands_used"]["code-review"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
