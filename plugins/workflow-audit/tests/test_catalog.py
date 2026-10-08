"""catalog/practices.json: schema, references, and that every metric it names exists in a real run."""
import json
import os
import unittest

import helpers
import audit
import wa_registry
from test_metrics import build

CATALOG = os.path.join(helpers.HERE, "..", "catalog", "practices.json")
GRADES = {"measured", "anthropic-advice", "anthropic-staff", "opinion"}
STATUSES = {"current", "superseded", "contested"}
KINDS = {"docs", "staff-post", "research", "blog"}
SUGGEST_KINDS = {"command", "skill", "plugin"}


def resolves(metrics, dotted):
    """True when the path reaches a value, or an insufficient metric on the way."""
    node = metrics
    for part in dotted.split("."):
        if isinstance(node, dict) and node.get("insufficient"):
            return True
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


class Catalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CATALOG, encoding="utf8") as f:
            cls.practices = json.load(f)["practices"]

    def test_ids_are_unique_and_superseded_by_exists(self):
        ids = [p["id"] for p in self.practices]
        self.assertEqual(len(ids), len(set(ids)))
        for p in self.practices:
            self.assertIn(p.get("superseded_by"), set(ids) | {None}, p["id"])
            if p["status"] == "superseded":
                self.assertIsNotNone(p.get("superseded_by"), p["id"])

    def test_enums(self):
        for p in self.practices:
            self.assertIn(p["grade"], GRADES, p["id"])
            self.assertIn(p["status"], STATUSES, p["id"])
            self.assertIn(p["source"]["kind"], KINDS, p["id"])
            self.assertTrue(p["source"]["url"].startswith("https://"), p["id"])

    def test_suggest_items(self):
        for p in self.practices:
            for s in p.get("suggest") or []:
                self.assertEqual(set(s), {"name", "kind", "what", "url"}, p["id"])
                self.assertIn(s["kind"], SUGGEST_KINDS, p["id"])
                self.assertTrue(s["what"].strip(), p["id"])
                self.assertTrue(s["url"].startswith("https://"), p["id"])

    def test_every_metric_resolves_in_a_fixture_run(self):
        metrics = wa_registry.run_all(build(), audit.METRIC_MODULES)
        missing = [(p["id"], p["metric"]) for p in self.practices
                   if p.get("metric") and not resolves(metrics, p["metric"])]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
