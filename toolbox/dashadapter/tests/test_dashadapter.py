"""Determinism och mappning mot map-templatens REASONS."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from toolbox.dashadapter.convert import (  # noqa: E402
    REASONS, convert, dumps, snapshots_from_obducera,
)
from toolbox.obduktion.pipeline import obducera  # noqa: E402

MINI = ROOT / "toolbox" / "obduktion" / "tests" / "fixtures" / "mini_serie"


class TestConvert(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = obducera(MINI, regim="kedjad")
        cls.proposal = convert(cls.doc, map_dir=None)

    def test_determinism(self):
        a = dumps(convert(self.doc, map_dir=None))
        b = dumps(convert(self.doc, map_dir=None))
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))

    def test_en_snapshot_per_population(self):
        snaps = self.proposal["snapshots"]
        self.assertEqual(len(snaps), len(self.doc["populationer"]))
        ids = [s["id"] for s in snaps]
        self.assertEqual(ids, sorted(self.doc["populationer"]))
        for s in snaps:
            self.assertEqual(s["regime"], s["id"])
            self.assertIn("cells", s)

    def test_reasons_are_template_keys(self):
        for s in self.proposal["snapshots"]:
            for c in s["cells"]:
                self.assertIn(c["reason"], REASONS)
                self.assertTrue(c["reasons"])
                self.assertTrue(set(c["reasons"]) <= set(REASONS))
                self.assertGreater(c["n"], 0)
                self.assertEqual(c["n"], sum(c["reasons"].values()))
                self.assertIsInstance(c["pos"], list)
                self.assertEqual(len(c["pos"]), 3)

    def test_sort_keys(self):
        parsed = json.loads(dumps(self.proposal))
        self.assertEqual(list(parsed.keys()), sorted(parsed.keys()))


class TestEmptyPops(unittest.TestCase):
    def test_legacy_root_kluster(self):
        doc = {"schema": "verktygslada/obducera/1", "regim": "kedjad",
               "kluster": [{
                   "kluster_id": "K0001", "cell": "12", "lank": "unknown",
                   "klass": "fall", "n_forsok": 3, "centroid": [1.0, 2.0, 3.0],
                   "forsok_id": ["A/c001/in_ring"],
               }]}
        snaps = snapshots_from_obducera(doc)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["cells"][0]["cell"], 12)
        self.assertEqual(snaps[0]["cells"][0]["reasons"]["air_commit_timeout"], 3)


if __name__ == "__main__":
    unittest.main()
