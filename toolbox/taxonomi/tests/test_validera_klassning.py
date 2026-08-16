"""Enhetstester: evidensplikt. Syntetiska kandidater, inte nyckeln."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from toolbox.taxonomi.validera_klassning import (  # noqa: E402
    dumps,
    las_jsonl,
    main,
    validera,
)

FIX = Path(__file__).resolve().parent / "fixtures"


def _kand(cid: str, kallor: list[str]) -> dict:
    return {
        "schema": "verktygslada/taxonomi-kandidat/3",
        "id": cid,
        "regim": "patrol",
        "roll": "positiv",
        "kallor": kallor,
        "fakta": {},
        "saknade_falt": [],
    }


def _pek(fil: str, falt: str = "x") -> dict:
    return {"fil": fil, "falt": falt}


CTRL = {
    "takeoff_cell": "1139",
    "runway": -4.5,
    "runway_measured": True,
    "sj_progress": -4.5,
    "sj_progress_measured": True,
    "phase": "Hop",
    "phase_prev": "Prestrafe",
    "on_ground": False,
    "jump_cmd": False,
    "first_air_vz": -9.6,
    "first_air_vz_measured": True,
}

KALLA = "WORK_LOGS/fixture-kalla.md"


class TestValideraKlassning(unittest.TestCase):
    def test_styre_utan_evidens_avvisas(self):
        """Negativkontrollmönster M3SH: styre antydd, controller saknas."""
        kands = [_kand("NEG-STYRE", [KALLA])]
        klassning = [{
            "id": "NEG-STYRE",
            "klass": "styre_sjband",
            "evidens": {"pekare": [_pek(KALLA, "phase")]},
        }]
        doc = validera(klassning, kands)
        r = doc["rader"][0]
        self.assertEqual(r["utfall"], "avvisad")
        self.assertEqual(r["forslag_klass"], "okand_ingen_fix")
        self.assertEqual(r["unknown_reason"], "missing_plan_fields")
        self.assertTrue(any("controllersekvens" in s for s in r["skal"]))

    def test_carve_utan_evidens_avvisas(self):
        """Negativkontrollmönster MEVS: carve antydd, cell/origin saknas."""
        kands = [_kand("NEG-CARVE", [KALLA])]
        klassning = [{
            "id": "NEG-CARVE",
            "klass": "carve_origin",
            "evidens": {"pekare": [_pek(KALLA)]},
        }]
        doc = validera(klassning, kands)
        r = doc["rader"][0]
        self.assertEqual(r["utfall"], "avvisad")
        self.assertEqual(r["forslag_klass"], "okand_ingen_fix")
        self.assertEqual(r["unknown_reason"], "missing_graph_inventory")
        self.assertTrue(any("cell" in s for s in r["skal"]))

    def test_pris_vreq_ocertifierad_avvisas(self):
        kands = [_kand("NEG-PRIS", [KALLA])]
        ev = {
            "pekare": [_pek(KALLA)],
            "controllersekvens": dict(CTRL),
            "mekanikbelagg": {
                "oberoende_av_vreq": True,
                "lank": "12",
                "forsok_id": "A/c1",
                "lufttick_t": 1.0,
            },
            "falt": {
                "selected_link": "12",
                "alt_link": "13",
                "v_req": 320,
                "speed": 300,
                "p_base": 1.0,
                "p_total": 1.2,
                "plan_fail": "priced_out",
            },
        }
        doc = validera([{"id": "NEG-PRIS", "klass": "pris_vreq", "evidens": ev}],
                       kands)
        r = doc["rader"][0]
        self.assertEqual(r["utfall"], "avvisad")
        self.assertEqual(r["forslag_klass"], "okand_ingen_fix")
        self.assertTrue(any("certifierad" in s for s in r["skal"]))

    def test_lagg_structural_utan_halvor_avvisas(self):
        kands = [_kand("NEG-LAGG", [KALLA])]
        klassning = [{
            "id": "NEG-LAGG",
            "klass": "lagg_lank",
            "evidens": {
                "pekare": [_pek(KALLA)],
                "struktur_dom": "structural_missing_link",
                "falt": {"foreslagen_kant": "Walk 1-2"},
            },
        }]
        doc = validera(klassning, kands)
        r = doc["rader"][0]
        self.assertEqual(r["utfall"], "avvisad")
        self.assertIn(r["unknown_reason"],
                      ("missing_graph_inventory", "missing_harness_predicate"))

    def test_kriterium_utan_predikat_avvisas(self):
        kands = [_kand("NEG-KRIT", [KALLA])]
        doc = validera([{
            "id": "NEG-KRIT",
            "klass": "kriterium_mal",
            "evidens": {"pekare": [_pek(KALLA)], "falt": {"ben": "in_ring"}},
        }], kands)
        r = doc["rader"][0]
        self.assertEqual(r["utfall"], "avvisad")
        self.assertEqual(r["unknown_reason"], "missing_harness_predicate")

    def test_slapp_utan_lank_avvisas(self):
        kands = [_kand("NEG-SLAPP", [KALLA])]
        doc = validera([{
            "id": "NEG-SLAPP",
            "klass": "slapp_lank",
            "evidens": {"pekare": [_pek(KALLA)], "falt": {"kind": "SpeedJump"}},
        }], kands)
        self.assertEqual(doc["rader"][0]["utfall"], "avvisad")

    def test_start_utan_regim_avvisas(self):
        kands = [_kand("NEG-START", [KALLA])]
        doc = validera([{
            "id": "NEG-START",
            "klass": "starttillstand_alofte",
            "evidens": {"pekare": [_pek(KALLA)], "falt": {}},
        }], kands)
        r = doc["rader"][0]
        self.assertEqual(r["utfall"], "avvisad")
        self.assertEqual(r["unknown_reason"], "regime_or_population_conflict")

    def test_ignorera_utan_avsett_avvisas(self):
        kands = [_kand("NEG-IGN", [KALLA])]
        doc = validera([{
            "id": "NEG-IGN",
            "klass": "ignorera_avsett",
            "evidens": {"pekare": [_pek(KALLA)], "falt": {}},
        }], kands)
        self.assertEqual(doc["rader"][0]["utfall"], "avvisad")

    def test_pekare_utanfor_kallor_avvisas(self):
        kands = [_kand("NEG-PEK", [KALLA])]
        doc = validera([{
            "id": "NEG-PEK",
            "klass": "carve_origin",
            "evidens": {
                "pekare": [_pek("WORK_LOGS/annan.md")],
                "falt": {
                    "cell": "2544",
                    "verdict": "covered",
                    "cell_origin": [960, 288, 56],
                },
            },
        }], kands)
        r = doc["rader"][0]
        self.assertEqual(r["utfall"], "avvisad")
        self.assertTrue(any("kallor" in s for s in r["skal"]))

    def test_saknad_evidens_avvisas(self):
        kands = [_kand("NEG-TOM", [KALLA])]
        doc = validera([{"id": "NEG-TOM", "klass": "styre_sjband"}], kands)
        r = doc["rader"][0]
        self.assertEqual(r["utfall"], "avvisad")
        self.assertEqual(r["unknown_reason"], "missing_plan_fields")

    def test_okand_med_reason_godkanns(self):
        kands = [_kand("OK-UNK", [KALLA])]
        doc = validera([{
            "id": "OK-UNK",
            "klass": "okand_ingen_fix",
            "unknown_reason": "missing_plan_fields",
            "evidens": {},
        }], kands)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["rader"][0]["utfall"], "godkand")

    def test_okand_utan_reason_avvisas(self):
        kands = [_kand("NEG-UNK", [KALLA])]
        doc = validera([{
            "id": "NEG-UNK",
            "klass": "okand_ingen_fix",
            "evidens": {},
        }], kands)
        self.assertEqual(doc["rader"][0]["utfall"], "avvisad")

    def test_styre_komplett_godkanns(self):
        kands = [_kand("OK-STYRE", [KALLA])]
        doc = validera([{
            "id": "OK-STYRE",
            "klass": "styre_sjband",
            "evidens": {
                "pekare": [_pek(KALLA, "phase_prev")],
                "controllersekvens": dict(CTRL),
            },
        }], kands)
        self.assertTrue(doc["ok"], doc["rader"])

    def test_carve_komplett_godkanns(self):
        kands = [_kand("OK-CARVE", [KALLA])]
        doc = validera([{
            "id": "OK-CARVE",
            "klass": "carve_origin",
            "evidens": {
                "pekare": [_pek(KALLA, "cell")],
                "falt": {
                    "cell": "2544",
                    "verdict": "covered",
                    "cell_origin": [960, 288, 56],
                },
            },
        }], kands)
        self.assertTrue(doc["ok"], doc["rader"])

    def test_determinism_tva_ganger(self):
        kands = [_kand("NEG-STYRE", [KALLA]), _kand("OK-UNK", [KALLA])]
        klassning = [
            {"id": "OK-UNK", "klass": "okand_ingen_fix",
             "unknown_reason": "missing_plan_fields", "evidens": {}},
            {"id": "NEG-STYRE", "klass": "styre_sjband",
             "evidens": {"pekare": [_pek(KALLA)]}},
        ]
        a = dumps(validera(klassning, kands))
        b = dumps(validera(klassning, kands))
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))
        json.loads(a)
        keys = list(json.loads(a).keys())
        self.assertEqual(keys, sorted(keys))

    def test_cli_exit_och_byteidentitet(self):
        kands = FIX / "kandidater.jsonl"
        bad = FIX / "klassning_negativ.jsonl"
        out1 = FIX / "_out1.json"
        out2 = FIX / "_out2.json"
        rc1 = main(["--klassning", str(bad), "--kandidater", str(kands),
                    "--out", str(out1)])
        rc2 = main(["--klassning", str(bad), "--kandidater", str(kands),
                    "--out", str(out2)])
        self.assertEqual(rc1, 1)
        self.assertEqual(rc2, 1)
        self.assertEqual(out1.read_text(encoding="utf-8"),
                         out2.read_text(encoding="utf-8"))
        out1.unlink(missing_ok=True)
        out2.unlink(missing_ok=True)

    def test_las_jsonl_hoppar_tomrader(self):
        p = FIX / "kandidater.jsonl"
        rader = las_jsonl(p)
        self.assertGreaterEqual(len(rader), 1)
        self.assertTrue(all("id" in r for r in rader))


if __name__ == "__main__":
    unittest.main()
