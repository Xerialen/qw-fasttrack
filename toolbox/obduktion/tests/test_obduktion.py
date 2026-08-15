"""Enhetstester mot KONTRAKT.md — syntetisk fixtur, inte T1h."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from toolbox.obduktion.adapter import extract_stamp  # noqa: E402
from toolbox.obduktion.dump import dumps  # noqa: E402
from toolbox.obduktion.pipeline import obducera  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_serie"


class TestAdapterAldrigGissa(unittest.TestCase):
    def test_saknad_stamp_ar_unknown(self):
        s = extract_stamp({"t": 1.0, "players": [
            {"ent": 1, "origin": [200.0, -700.0, 56.0]}]})
        self.assertEqual(s["cell"], "unknown")
        self.assertEqual(s["lank"], "unknown")
        self.assertEqual(s["bind"], "unknown")

    def test_xyz_blir_aldrig_cell(self):
        s = extract_stamp({"origin": [92.0, -588.0, 296.0], "t": 1})
        self.assertEqual(s["cell"], "unknown")

    def test_nolink_ar_unknown(self):
        s = extract_stamp({"cell_id": 12, "link": 4294967295})
        self.assertEqual(s["cell"], "12")
        self.assertEqual(s["lank"], "unknown")
        self.assertEqual(s["bind"], "stamped")

    def test_stamped_cell(self):
        s = extract_stamp({"cell_id": 1373, "graph_contract": "qw-nav-graph/1"})
        self.assertEqual(s["cell"], "1373")
        self.assertEqual(s["bind"], "stamped")
        self.assertEqual(s["graph_contract"], "qw-nav-graph/1")


class TestMiniSerie(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = obducera(FIXTURE, arm="AB", regim="kedjad")
        cls.text = dumps(cls.doc)

    def test_schema(self):
        self.assertEqual(self.doc["schema"], "verktygslada/obducera/1")
        self.assertEqual(self.doc["kommando"], "obducera")
        self.assertEqual(self.doc["serie"], "mini_serie")
        self.assertEqual(self.doc["regim"], "kedjad")

    def test_determinism_byteidentisk(self):
        again = dumps(obducera(FIXTURE, arm="AB", regim="kedjad"))
        self.assertEqual(self.text, again)
        self.assertTrue(self.text.endswith("\n"))
        json.loads(self.text)

    def test_sort_keys(self):
        parsed = json.loads(self.text)
        self.assertEqual(list(parsed.keys()), sorted(parsed.keys()))

    def test_regim_filtrerar_teleport(self):
        # c003 är teleport_efter_fel — får inte synas under kedjad
        ids = {h["forsok_id"] for h in self.doc["handelser"]}
        self.assertNotIn("A/c003/in_ring", ids)
        self.assertGreater(self.doc["filter"]["n_forsok_exkluderade"], 0)

    def test_regim_alla_tar_med_teleport(self):
        doc = obducera(FIXTURE, regim="alla")
        ids = {h["forsok_id"] for h in doc["handelser"]}
        self.assertIn("A/c003/in_ring", ids)

    def test_fall_inte_avsett_pa_in(self):
        klasser = {h["klass"] for h in self.doc["handelser"]
                   if h["forsok_id"] == "A/c001/in_ring"}
        self.assertIn("fall", klasser)
        self.assertNotIn("avsett_drop", klasser)

    def test_avsett_drop_pa_ut(self):
        klasser = {h["klass"] for h in self.doc["handelser"]
                   if h["forsok_id"] == "A/c001/ut_ring"}
        self.assertEqual(klasser, {"avsett_drop"})
        # avsett_drop är inte åtgärd
        self.assertTrue(all(a["klass"] != "avsett_drop"
                            for a in self.doc["atgarder"]))

    def test_fastnad(self):
        h = [x for x in self.doc["handelser"] if x["klass"] == "fastnad"]
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["forsok_id"], "A/c004/in_vast")

    def test_skilda_harader_hopslas_inte(self):
        fall = [k for k in self.doc["kluster"] if k["klass"] == "fall"
                and k["bind"] == "unknown"]
        # en härd vid ~[200,-700], en vid ~[-500,-700]
        self.assertGreaterEqual(len(fall), 2)
        cents = [k["centroid"] for k in fall]
        xs = [c[0] for c in cents]
        self.assertTrue(any(x > 0 for x in xs) and any(x < 0 for x in xs))

    def test_stamplad_cell_bevaras(self):
        stamped = [h for h in self.doc["handelser"] if h["bind"] == "stamped"]
        self.assertTrue(stamped)
        self.assertTrue(all(h["cell"] == "4242" for h in stamped))
        self.assertNotIn("unknown", {h["cell"] for h in stamped})

    def test_unstamped_cell_aldrig_numerisk_gissning(self):
        unknown = [h for h in self.doc["handelser"] if h["bind"] == "unknown"]
        self.assertTrue(unknown)
        self.assertTrue(all(h["cell"] == "unknown" for h in unknown))

    def test_atgarder_har_prio_och_forsok(self):
        self.assertTrue(self.doc["atgarder"])
        prios = [a["prio"] for a in self.doc["atgarder"]]
        self.assertEqual(prios, list(range(1, len(prios) + 1)))
        for a in self.doc["atgarder"]:
            self.assertTrue(a["forsok_id"])
            self.assertIn(a["klass"], ("fall", "fastnad", "timeout", "stall"))

    def test_forbjudna_falt(self):
        for k in ("generated_at", "host", "path", "request_id", "duration_ms"):
            self.assertNotIn(k, self.doc)

    def test_decimaler(self):
        for h in self.doc["handelser"]:
            self.assertEqual(h["origin"], [round(x, 2) for x in h["origin"]])
            if h["t"] is not None:
                self.assertEqual(h["t"], round(h["t"], 3))


class TestStallOchTimeout(unittest.TestCase):
    def test_stall_jsonl(self):
        # platt kuvert
        serie = Path(__file__).resolve().parent / "fixtures" / "stall_serie"
        doc = obducera(serie, regim="alla")
        self.assertTrue(any(h["klass"] == "stall" for h in doc["handelser"]))
        s = next(h for h in doc["handelser"] if h["klass"] == "stall")
        self.assertEqual(s["stall_reason"], "displacement")
        self.assertEqual(s["cell"], "77")

    def test_k_timeout(self):
        serie = Path(__file__).resolve().parent / "fixtures" / "k_serie"
        doc = obducera(serie, regim="alla")  # K är teleport
        self.assertTrue(any(h["klass"] == "timeout" for h in doc["handelser"]))
        kedjad = obducera(serie, regim="kedjad")
        self.assertEqual(kedjad["filter"]["n_forsok_behallna"], 0)
        self.assertEqual(kedjad["handelser"], [])


if __name__ == "__main__":
    unittest.main()
