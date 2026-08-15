"""Slice-adaptern: A:s stämpelformat, grafvalidering, B:s genomsläppning.

Egen fil så att den inte krockar med spår I:s `test_obduktion.py` (groks
fall-fix bor där).
"""
import json
import tempfile
import unittest
from pathlib import Path

from toolbox.obduktion.adapter import (extract_stamp, iter_ticks, load_ticks,
                                       resolve_graph_stamp, stamp_id_str)

STAMP = "13090435456435551592"
OTHER = "9999999999999999999"


class ExtractStamp(unittest.TestCase):
    def test_reads_a_stamped_row(self):
        """A:s radformat: cell, schema som kontrakt, graph_stamp som identitet."""
        row = {"t": 1.0, "bot": 1, "cell": 530, "verdict": "covered",
               "schema": "qw-nav-graph/1", "graph_stamp": STAMP}
        s = extract_stamp(row, None, STAMP)
        self.assertEqual(s["cell"], "530")
        self.assertEqual(s["bind"], "stamped")
        self.assertEqual(s["graph_contract"], "qw-nav-graph/1")
        self.assertEqual(s["graph_stamp"], STAMP)
        self.assertFalse(s["stamp_avvik"])
        self.assertEqual(s["verdict"], "covered")

    def test_airborne_sentinel_is_not_a_cell(self):
        """En luftburen tick bär 4294967295 — boten står inte i någon cell.

        Det är något helt annat än att stämplingen missade, och `verdict` är det
        som låter domlagret skilja de två. Bindningen blir unknown i båda fallen
        — men bara det ena är ett problem.
        """
        row = {"t": 1.0, "cell": 4294967295, "verdict": "airborne",
               "schema": "qw-nav-graph/1", "graph_stamp": STAMP}
        s = extract_stamp(row, None, STAMP)
        self.assertEqual(s["cell"], "unknown")
        self.assertEqual(s["bind"], "unknown")
        self.assertEqual(s["verdict"], "airborne")
        self.assertFalse(s["stamp_avvik"], "sentinelen är inte en grafavvikelse")

    def test_a_row_from_another_graph_is_unbound_not_rebound(self):
        """Fel graf ⇒ ingen bindning alls. Vi gissar inte vilken som är rätt.

        Ett cell-id är bara ett namn på en cell INOM en graf. Att behålla
        bindningen vore att peka ut fel plats med full säkerhet, vilket är värre
        än att inte peka alls.
        """
        row = {"t": 1.0, "cell": 530, "verdict": "covered",
               "schema": "qw-nav-graph/1", "graph_stamp": OTHER}
        s = extract_stamp(row, None, STAMP)
        self.assertEqual(s["cell"], "unknown")
        self.assertEqual(s["lank"], "unknown")
        self.assertEqual(s["bind"], "unknown")
        self.assertTrue(s["stamp_avvik"])

    def test_no_reference_means_no_validation(self):
        """Utan referens valideras inget — frånvaro av facit är inte ett facit."""
        row = {"t": 1.0, "cell": 530, "graph_stamp": OTHER}
        s = extract_stamp(row, None, None)
        self.assertEqual(s["cell"], "530")
        self.assertFalse(s["stamp_avvik"])

    def test_stamp_id_normalises_to_decimal_string(self):
        """u64 skrivs som decimalsträng i JSONL; int och sträng ska mötas."""
        self.assertEqual(stamp_id_str(13090435456435551592), STAMP)
        self.assertEqual(stamp_id_str(STAMP), STAMP)
        self.assertIsNone(stamp_id_str(None))
        self.assertIsNone(stamp_id_str(""))


class PlanPassthrough(unittest.TestCase):
    def test_plan_is_passed_through_untouched(self):
        """B:s planerartelemetri släpps igenom RÅ — särskilt de signerade fälten.

        runway, sj_progress och first_air_vz är signerade och bär sin frånvaro i
        egna *_measured-flaggor, just därför att -1.0 och 0.0 är giltiga
        avläsningar. En adapter som "städar" dem till unknown återinför exakt
        den bugg B redan har rättat: en bot en enhet förbi läppen skulle bli en
        icke-mätning i just den zon V296 handlar om.
        """
        plan = {
            "seq": 918,
            "runway": -4.5, "runway_measured": True,
            "sj_progress": -4.5, "sj_progress_measured": True,
            "first_air_vz": 0.0, "first_air_vz_measured": True,
            "jump_cmd": False, "phase_prev": "Prestrafe", "phase": "Hop",
        }
        row = {"t": 1.0, "cell": 530, "graph_stamp": STAMP, "plan": dict(plan)}
        s = extract_stamp(row, None, STAMP)
        self.assertEqual(s["plan"], plan, "inga fält omtolkade, inga sentinels införda")
        self.assertEqual(s["plan"]["runway"], -4.5)
        self.assertEqual(s["plan"]["first_air_vz"], 0.0)
        self.assertTrue(s["plan"]["first_air_vz_measured"])

    def test_missing_plan_is_absent_not_invented(self):
        s = extract_stamp({"t": 1.0, "cell": 1, "graph_stamp": STAMP}, None, STAMP)
        self.assertIsNone(s["plan"])


class ResolveGraphStamp(unittest.TestCase):
    def _serie(self, tmp, rows_by_file, manifest=None):
        serie = Path(tmp) / "serie"
        (serie / "A" / "c001").mkdir(parents=True)
        forsok = []
        for name, rows in rows_by_file.items():
            p = serie / "A" / "c001" / f"{name}.jsonl"
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            forsok.append({"jsonl": p, "ent": 1, "stamplar": None, "serie": serie})
        if manifest is not None:
            (serie / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return serie, forsok

    def _row(self, stamp):
        return {"t": 1.0, "cell": 5, "graph_stamp": stamp,
                "players": [{"ent": 1, "origin": [0, 0, 0], "on_ground": True}]}

    def test_manifest_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie, forsok = self._serie(
                tmp, {"in_ring": [self._row(OTHER)]},
                manifest={"graph_stamp": STAMP, "schema": "qw-nav-graph/1"})
            got = resolve_graph_stamp(forsok, None, serie)
            self.assertEqual(got["referens"], STAMP)
            self.assertEqual(got["kalla"], "manifest")

    def test_agreeing_rows_are_a_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie, forsok = self._serie(tmp, {"in_ring": [self._row(STAMP)] * 3})
            got = resolve_graph_stamp(forsok, None, serie)
            self.assertEqual(got["referens"], STAMP)
            self.assertEqual(got["kalla"], "rader")

    def test_disagreeing_rows_leave_no_reference(self):
        """Oeniga rader ⇒ ingen referens. Majoriteten vore en gissning.

        Att välja den vanligaste stämpeln hade bundit varje rad till en graf vi
        inte vet är rätt — och gjort det tyst.
        """
        with tempfile.TemporaryDirectory() as tmp:
            serie, forsok = self._serie(
                tmp, {"in_ring": [self._row(STAMP), self._row(OTHER)]})
            got = resolve_graph_stamp(forsok, None, serie)
            self.assertEqual(got["referens"], "unknown")
            self.assertEqual(got["kalla"], "konflikt")

    def test_no_stamps_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {"t": 1.0, "players": [{"ent": 1, "origin": [0, 0, 0]}]}
            serie, forsok = self._serie(tmp, {"in_ring": [row]})
            got = resolve_graph_stamp(forsok, None, serie)
            self.assertEqual(got["kalla"], "ingen")


class SidecarAlignment(unittest.TestCase):
    def test_stamps_align_by_t_when_index_slips(self):
        """Sidovagnen fogas på t avrundat till 3 decimaler, inte bara på index."""
        with tempfile.TemporaryDirectory() as tmp:
            serie = Path(tmp) / "s"
            stamplar = Path(tmp) / "st"
            (serie / "A" / "c001").mkdir(parents=True)
            (stamplar / "A" / "c001").mkdir(parents=True)
            raw = [{"t": 2521.49267578125,
                    "players": [{"ent": 1, "origin": [1, 2, 3], "on_ground": True}]}]
            (serie / "A" / "c001" / "in_ring.jsonl").write_text(
                json.dumps(raw[0]) + "\n", encoding="utf-8")
            # Stämpelraden bär t med 3 decimaler — samma tick, annan precision.
            (stamplar / "A" / "c001" / "in_ring.jsonl").write_text(
                json.dumps({"t": 2521.493, "cell": 530, "verdict": "covered",
                            "schema": "qw-nav-graph/1", "graph_stamp": STAMP}) + "\n",
                encoding="utf-8")
            ticks = list(iter_ticks(serie / "A" / "c001" / "in_ring.jsonl", 1,
                                    stamplar, serie, STAMP))
            self.assertEqual(len(ticks), 1)
            self.assertEqual(ticks[0]["cell"], "530")
            self.assertEqual(ticks[0]["bind"], "stamped")


class ResolveGraphStampPerArm(unittest.TestCase):
    """Per-arm-grafvalidering: A och B bär olika stamp efter omstämplingen."""
    STAMP_A = "13090435456435551592"
    STAMP_B = "906595427771298736"

    def _serie(self, tmp, rows_by_arm, manifest=None):
        serie = Path(tmp) / "serie"
        forsok = []
        for arm, files in rows_by_arm.items():
            d = serie / arm / "c001"
            d.mkdir(parents=True)
            for name, rows in files.items():
                p = d / f"{name}.jsonl"
                p.write_text("".join(json.dumps(r) + "\n" for r in rows),
                             encoding="utf-8")
                forsok.append({"jsonl": p, "ent": 1, "stamplar": None,
                               "serie": serie, "arm": arm})
        if manifest is not None:
            (serie / "manifest.json").write_text(json.dumps(manifest),
                                                 encoding="utf-8")
        return serie, forsok

    def _row(self, stamp, cell=5):
        return {"t": 1.0, "cell": cell, "graph_stamp": stamp,
                "players": [{"ent": 1, "origin": [0, 0, 0], "on_ground": True}]}

    def test_per_arm_manifest_sets_arm_stamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie, forsok = self._serie(
                tmp,
                {"A": {"in_ring": [self._row(self.STAMP_A)]},
                 "B": {"in_ring": [self._row(self.STAMP_B)]}},
                manifest={"per_arm": {
                    "A": {"graph_stamp": self.STAMP_A, "schema": "qw-nav-graph/1"},
                    "B": {"graph_stamp": self.STAMP_B, "schema": "qw-nav-graph/1"}}})
            got = resolve_graph_stamp(forsok, None, serie)
            self.assertEqual(got["kalla"], "manifest")
            self.assertEqual(got["referens"], "unknown")  # armar skiljer sig
            self.assertEqual(got["per_arm"], {"A": self.STAMP_A, "B": self.STAMP_B})
            self.assertEqual({f["arm"]: f["_arm_stamp"] for f in forsok},
                             {"A": self.STAMP_A, "B": self.STAMP_B})

    def test_load_ticks_validates_against_its_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie, forsok = self._serie(
                tmp,
                {"A": {"in_ring": [self._row(self.STAMP_A)]},
                 "B": {"in_ring": [self._row(self.STAMP_B)]}},
                manifest={"per_arm": {
                    "A": {"graph_stamp": self.STAMP_A},
                    "B": {"graph_stamp": self.STAMP_B}}})
            resolve_graph_stamp(forsok, None, serie)
            for f in forsok:
                ticks = load_ticks(f)
                self.assertEqual(len(ticks), 1)
                self.assertEqual(ticks[0]["bind"], "stamped")
                self.assertFalse(ticks[0]["stamp_avvik"],
                                 f"arm {f['arm']} felaktigt avvik")

    def test_wrong_arm_stamp_on_a_row_is_unbound(self):
        # En A-rad som bär B:s stamp, validerad mot A:s stamp => obunden.
        with tempfile.TemporaryDirectory() as tmp:
            serie, forsok = self._serie(
                tmp,
                {"A": {"in_ring": [self._row(self.STAMP_B)]}},
                manifest={"per_arm": {"A": {"graph_stamp": self.STAMP_A}}})
            resolve_graph_stamp(forsok, None, serie)
            ticks = load_ticks(forsok[0])
            self.assertEqual(ticks[0]["cell"], "unknown")
            self.assertTrue(ticks[0]["stamp_avvik"])

    def test_same_arm_conflict_is_kept(self):
        # Två olika stamp INOM samma arm = äkta konflikt, armen ovaliderad.
        with tempfile.TemporaryDirectory() as tmp:
            serie, forsok = self._serie(
                tmp,
                {"A": {"in_ring": [self._row(self.STAMP_A), self._row(self.STAMP_B)]}},
                manifest=None)
            got = resolve_graph_stamp(forsok, None, serie)
            self.assertEqual(got["kalla"], "konflikt")
            self.assertEqual(got["per_arm"], {"A": "unknown"})
            self.assertTrue(all(f["_arm_stamp"] is None for f in forsok))

    def test_legacy_top_level_manifest_applies_to_all_arms(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie, forsok = self._serie(
                tmp,
                {"A": {"in_ring": [self._row(self.STAMP_A)]},
                 "B": {"in_ring": [self._row(self.STAMP_A)]}},
                manifest={"graph_stamp": self.STAMP_A, "schema": "qw-nav-graph/1"})
            got = resolve_graph_stamp(forsok, None, serie)
            self.assertEqual(got["referens"], self.STAMP_A)
            self.assertEqual(got["kalla"], "manifest")
            self.assertTrue(all(f["_arm_stamp"] == self.STAMP_A for f in forsok))


if __name__ == "__main__":
    unittest.main()
