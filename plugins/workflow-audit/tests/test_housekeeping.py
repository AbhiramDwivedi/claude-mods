import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import wa_housekeeping as hk  # noqa: E402


class Housekeeping(unittest.TestCase):
    def test_retention_from_settings_or_default(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(hk.retention_days(home), 30)
            os.makedirs(os.path.join(home, ".claude"))
            with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
                json.dump({"cleanupPeriodDays": 90}, f)
            self.assertEqual(hk.retention_days(home), 90)

    def test_cache_entry_dropped_when_transcript_is_gone(self):
        with tempfile.TemporaryDirectory() as d:
            kept_src, gone_src = os.path.join(d, "a.jsonl"), os.path.join(d, "b.jsonl")
            open(kept_src, "w").close()
            cache = os.path.join(d, "cache")
            os.makedirs(cache)
            for name, src in (("k.json", kept_src), ("g.json", gone_src)):
                with open(os.path.join(cache, name), "w") as f:
                    json.dump({"key": [2, src, 0, 0], "data": {"humans": ["secret text"]}}, f)
            self.assertEqual(hk.prune_cache(cache), 1)
            self.assertEqual(os.listdir(cache), ["k.json"])

    def test_old_samples_expire_and_reports_stay(self):
        with tempfile.TemporaryDirectory() as runs:
            old, new = os.path.join(runs, "20200101-000000"), os.path.join(runs, time.strftime("%Y%m%d-%H%M%S"))
            for r in (old, new):
                os.makedirs(os.path.join(r, "samples"))
                for f in ("report.md", "metrics.json", "sample-verdicts.json"):
                    open(os.path.join(r, f), "w").close()
            self.assertEqual(hk.expire_samples(runs, 30, current_dir=None), 1)
            self.assertFalse(os.path.exists(os.path.join(old, "samples")))
            self.assertTrue(os.path.exists(os.path.join(old, "report.md")))
            self.assertTrue(os.path.exists(os.path.join(old, "sample-verdicts.json")))
            self.assertTrue(os.path.exists(os.path.join(new, "samples")))

    def test_folders_that_are_not_runs_are_left_alone(self):
        with tempfile.TemporaryDirectory() as runs:
            other = os.path.join(runs, "my-notes")
            os.makedirs(os.path.join(other, "samples"))
            os.utime(other, (0, 0))
            self.assertEqual(hk.expire_samples(runs, 30, current_dir=None), 0)
            self.assertTrue(os.path.exists(os.path.join(other, "samples")))


if __name__ == "__main__":
    unittest.main()
