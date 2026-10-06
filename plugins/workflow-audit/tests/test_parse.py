import json
import os
import unittest

from helpers import FIXTURES, MAIN_ID, PROJECTS, SELF_ID  # noqa: F401  (sets sys.path)
import wa_parse

MAIN = os.path.join(PROJECTS, "-proj-a", MAIN_ID + ".jsonl")


class ParseMain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = wa_parse.parse_file(MAIN, "main", MAIN_ID)

    def test_human_messages_are_classified(self):
        kinds = [(h["kind"], h["text"]) for h in self.p["humans"]]
        self.assertEqual(kinds, [
            ("typed", "fix the bug in a.py"),
            ("queued", "also check b.py"),       # from the queued_command attachment
            ("command", "keep tests"),
            ("typed", "no, that is wrong"),
        ])
        self.assertEqual(self.p["humans"][2]["cmd"], "/compact")

    def test_excluded_user_records(self):
        texts = " ".join(h["text"] for h in self.p["humans"])
        for banned in ("coordinator", "Another Claude", "task-notification", "meta text", "summary of earlier", "interrupted"):
            self.assertNotIn(banned, texts)

    def test_queued_text_typed_again_is_not_counted_twice(self):
        self.assertEqual(sum(1 for h in self.p["humans"] if h["text"] == "also check b.py"), 1)

    def test_system_queued_commands_are_ignored(self):
        self.assertFalse(any("background thing" in h["text"] for h in self.p["humans"]))

    def test_interrupt_rejection_malformed_line(self):
        self.assertEqual(len(self.p["interrupts"]), 1)
        self.assertEqual(len(self.p["rejections"]), 1)
        self.assertEqual(self.p["bad_lines"], 1)

    def test_usage_is_deduped_by_message_id(self):
        reqs = self.p["requests"]
        self.assertEqual(len(reqs), 3)             # m1 spans two records
        self.assertEqual(reqs[0]["out"], 40)        # the last record's usage wins
        self.assertEqual(reqs[0]["cc"], 100)

    def test_tools_agent_calls_and_modes(self):
        self.assertEqual([(c["id"], c["model"]) for c in self.p["agent_calls"]], [("tA", None), ("tB", "sonnet")])
        self.assertIn("pytest -q", [t.get("cmd") for t in self.p["tools"]])
        self.assertIn("C:/work/demo/a.py",[t.get("path") for t in self.p["tools"]])
        self.assertEqual([m for _, m in self.p["modes"]], ["plan"])
        self.assertEqual(self.p["agent_ids"], {"a1": "tA"})
        self.assertEqual(self.p["cwd"], "C:/work/demo")

    def test_preceding_assistant_text_tail(self):
        self.assertEqual(self.p["humans"][3]["tail"], "Working on it")


class ParseCache(unittest.TestCase):
    def test_cache_hit_then_miss_after_change(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "s.jsonl")
            shutil.copy(MAIN, f)
            cache = os.path.join(d, "cache")
            _, hit1 = wa_parse.load_cached(cache, f, "main", "s")
            data, hit2 = wa_parse.load_cached(cache, f, "main", "s")
            self.assertEqual((hit1, hit2), (False, True))
            self.assertEqual(len(data["requests"]), 3)
            with open(f, "a", encoding="utf8") as fh:
                fh.write(json.dumps({"type": "user", "timestamp": "2026-10-01T12:00:00Z",
                                     "message": {"role": "user", "content": "one more"}}) + "\n")
            data, hit3 = wa_parse.load_cached(cache, f, "main", "s")
            self.assertFalse(hit3)
            self.assertEqual(len(data["humans"]), 5)


if __name__ == "__main__":
    unittest.main()
