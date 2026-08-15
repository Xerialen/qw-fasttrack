"""Determinism och native I-klasser mot utökad template."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from toolbox.dashadapter.convert import (  # noqa: E402
    I_KLASSER, TemplateIncompatible, convert, dumps, snapshots_from_obducera,
)
from toolbox.obduktion.pipeline import obducera  # noqa: E402

MINI = ROOT / "toolbox" / "obduktion" / "tests" / "fixtures" / "mini_serie"
NEW_TPL = Path.home() / "rtx-toolbox-dash/testsuite/dashboard/map-template.html"
OLD_TPL = Path.home() / "rtx-cost-exp/testsuite/dashboard/map-template.html"


class TestConvert(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = obducera(MINI, regim="kedjad")
        cls.tpl = NEW_TPL.read_text(encoding="utf-8") if NEW_TPL.is_file() else None
        if cls.tpl:
            cls.proposal = convert(cls.doc, map_dir=None, map_template=cls.tpl)

    def test_fail_without_template(self):
        with self.assertRaises(TemplateIncompatible):
            convert(self.doc, map_dir=None, map_template=None)

    def test_fail_old_template(self):
        if not OLD_TPL.is_file():
            self.skipTest("rtx-cost-exp template saknas")
        with self.assertRaises(TemplateIncompatible):
            convert(self.doc, map_dir=None, map_template=OLD_TPL)

    def test_determinism(self):
        if not self.tpl:
            self.skipTest("ny template saknas")
        a = dumps(convert(self.doc, map_dir=None, map_template=self.tpl))
        b = dumps(convert(self.doc, map_dir=None, map_template=self.tpl))
        self.assertEqual(a, b)

    def test_native_klass_keys(self):
        if not self.tpl:
            self.skipTest("ny template saknas")
        for s in self.proposal["snapshots"]:
            for c in s["cells"]:
                self.assertIn(c["reason"], I_KLASSER)
                self.assertEqual(set(c["reasons"].keys()), {c["reason"]})
                self.assertEqual(c["n"], sum(c["reasons"].values()))
                self.assertNotIn("air_commit_timeout", c["reasons"])
                self.assertNotIn("prestrafe_deficit", c["reasons"])
                self.assertNotIn("displacement", c["reasons"])


class TestEmptyPops(unittest.TestCase):
    def test_legacy_root_kluster(self):
        doc = {"schema": "verktygslada/obducera/3", "regim": "kedjad",
               "kluster": [{
                   "kluster_id": "K0001", "cell": "12", "lank": "unknown",
                   "klass": "fall", "n_forsok": 3, "centroid": [1.0, 2.0, 3.0],
                   "forsok_id": ["A/c001/in_ring"],
               }]}
        snaps = snapshots_from_obducera(doc)
        self.assertEqual(snaps[0]["cells"][0]["reason"], "fall")
        self.assertEqual(snaps[0]["cells"][0]["reasons"]["fall"], 3)


if __name__ == "__main__":
    unittest.main()
