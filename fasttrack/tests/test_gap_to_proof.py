from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import core  # noqa: E402


def trial_result(*, passed: bool, streak: int, elapsed: float) -> dict:
    return {
        "attempts": 1,
        "ok": int(passed),
        "passed": passed,
        "streak_max": streak,
        "rows": [{"attempt": 1, "elapsed": elapsed, "outcome": "passed",
                  "streak": streak}],
        "provenance": {
            "graph_sha": "graph-sha", "patch_sha": None,
            "cvar_readback": {"rtx_bot_bhop": {"value": 1}},
        },
    }


class GapToProofTests(unittest.TestCase):
    route = {
        "start": [1, 2, 3], "target": [4, 5, 6],
        "arrive_box": [0, 0, 0, 10, 10, 10],
        "pass_time_s": 3.82, "streak_target": 5,
    }

    def test_ownership_aborts_before_any_mutation_when_server_is_active(self):
        with patch.object(core, "_unit_status", side_effect=lambda unit: (
                "active" if unit == core.UNIT else "inactive")), \
                patch.object(core, "patch_clear") as clear, \
                patch.object(core, "server_up") as up:
            with self.assertRaisesRegex(RuntimeError, "inte säkert inaktiv"):
                core.gap_to_proof("demo.qwd", "test", [1, 2, 3], self.route)
        clear.assert_not_called()
        up.assert_not_called()

    def test_ownership_aborts_before_any_mutation_when_live_bridge_is_active(self):
        with patch.object(core, "_unit_status", side_effect=lambda unit: (
                "active" if unit == core.LIVE_UNIT else "inactive")), \
                patch.object(core, "patch_clear") as clear, \
                patch.object(core, "server_up") as up:
            with self.assertRaisesRegex(RuntimeError, "live-bryggan"):
                core.gap_to_proof("demo.qwd", "test", [1, 2, 3], self.route)
        clear.assert_not_called()
        up.assert_not_called()

    def test_ownership_fails_closed_on_ambiguous_unit_status(self):
        with patch.object(core, "_unit_status", return_value="activating"), \
                patch.object(core, "patch_clear") as clear:
            with self.assertRaisesRegex(RuntimeError, "activating"):
                core.gap_to_proof("demo.qwd", "test", [1, 2, 3], self.route)
        clear.assert_not_called()

    def test_exact_order_and_complete_bundle(self):
        events = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            graph = root / "proof-baseline-graph.json"
            graph.write_text('{"schema":"qw-nav-graph/1"}')
            overlay = root / "proof-graph.json"
            overlay.write_text('{"schema":"qw-nav-graph/1"}')
            patch_file = root / "proof.json"
            patch_file.write_text(json.dumps({
                "schema": "qw-nav-patch/1", "name": "proof", "adds": [],
                "provenance": {"grounding": {"bsp_sha": "bsp-sha"}},
            }))

            def clear():
                events.append("clear")
                return {"cleared": True}

            def up(map_name):
                events.append("up")
                return {"map": map_name}

            def dump(map_name, seed, out_name):
                events.append("graph")
                return {"out": str(graph), "graph_sha": "graph-sha"}

            def ingest(demo, map_name, name, graph_path):
                events.append("ingest")
                self.assertEqual(graph_path, str(graph))
                return {"summary": {"cells_missing": 1},
                        "evidence": {"grounding": {"bsp_sha": "bsp-sha"}},
                        "overlay": str(overlay), "patch": str(patch_file)}

            patched = [False]

            def apply(value):
                events.append("apply")
                patched[0] = True
                return {"adds_ok": 0}

            def run_trial(*args, **kwargs):
                events.append("trial-patched" if patched[0] else "trial-baseline")
                return trial_result(passed=patched[0], streak=5 if patched[0] else 0,
                                    elapsed=3.0 if patched[0] else 5.0)

            with patch.object(core, "EVIDENCE_DIR", root / "evidence"), \
                    patch.object(core, "_unit_status", return_value="inactive"), \
                    patch.object(core, "_remove_live_state"), \
                    patch.object(core, "patch_clear", side_effect=clear), \
                    patch.object(core, "server_up", side_effect=up), \
                    patch.object(core, "graph_dump", side_effect=dump), \
                    patch.object(core, "demo_ingest", side_effect=ingest), \
                    patch.object(core, "patch_apply", side_effect=apply), \
                    patch.object(core, "trial", side_effect=run_trial):
                result = core.gap_to_proof(
                    "demo.qwd", "test", [1, 2, 3], self.route, "proof")

            self.assertEqual(events, [
                "clear", "up", "graph", "ingest", "trial-baseline",
                "apply", "trial-patched", "clear", "up",
            ])
            manifest = json.loads(Path(result["manifest"]).read_text())
            self.assertFalse(manifest["partial"])
            self.assertEqual({entry["file"] for entry in manifest["files"]}, {
                "gaps.json", "patch.json", "ab.json", "provenance.json",
            })
            self.assertTrue(all(len(entry["sha256"]) == 64 for entry in manifest["files"]))
            ab = json.loads((Path(result["bundle"]) / "ab.json").read_text())
            self.assertEqual(ab["attempts"][0]["delta_s"], -2.0)
            self.assertEqual(ab["patched"]["streak_max"], 5)

    def test_mid_phase_failure_writes_partial_bundle_and_cleans(self):
        events = []
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(core, "EVIDENCE_DIR", Path(temp)), \
                patch.object(core, "_unit_status", return_value="inactive"), \
                patch.object(core, "_remove_live_state"), \
                patch.object(core, "patch_clear", side_effect=lambda: events.append("clear") or {}), \
                patch.object(core, "server_up", side_effect=lambda map_name: events.append("up") or {}), \
                patch.object(core, "graph_dump", side_effect=RuntimeError("dump failed")):
            with self.assertRaisesRegex(RuntimeError, "dump failed"):
                core.gap_to_proof("demo.qwd", "test", [1, 2, 3], self.route, "partial")
            manifest = json.loads((Path(temp) / "partial" / "manifest.json").read_text())
        self.assertTrue(manifest["partial"])
        self.assertEqual(manifest["failed_phase"], "graph_dump")
        self.assertEqual(events, ["clear", "up", "clear", "up"])

    def test_keyboard_interrupt_uses_the_same_cleanup_path(self):
        events = []
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(core, "EVIDENCE_DIR", Path(temp)), \
                patch.object(core, "_unit_status", return_value="inactive"), \
                patch.object(core, "_remove_live_state"), \
                patch.object(core, "patch_clear", side_effect=lambda: events.append("clear") or {}), \
                patch.object(core, "server_up", side_effect=lambda map_name: events.append("up") or {}), \
                patch.object(core, "graph_dump", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                core.gap_to_proof("demo.qwd", "test", [1, 2, 3], self.route, "cancelled")
            manifest = json.loads((Path(temp) / "cancelled" / "manifest.json").read_text())
        self.assertTrue(manifest["partial"])
        self.assertEqual(events, ["clear", "up", "clear", "up"])


class PromoteV2Tests(unittest.TestCase):
    def make_proof(self, root: Path, streak: int, passed: bool) -> None:
        proof = root / "evidence" / "proof"
        proof.mkdir(parents=True)
        payloads = {
            "gaps.json": {"schema": "qw-gap-evidence/1"},
            "patch.json": {"schema": "qw-nav-patch/1", "name": "proof", "adds": []},
            "ab.json": {
                "schema": "qw-gap-proof-ab/1",
                "route": {"streak_target": 5},
                "baseline": {"streak_max": 0},
                "patched": {"streak_max": streak, "passed": passed},
                "attempts": [{
                    "attempt": 1,
                    "baseline": {"elapsed": 5.0, "outcome": "over_time", "streak": 0},
                    "patched": {"elapsed": 3.0, "outcome": "passed", "streak": streak},
                    "delta_s": -2.0,
                }, {
                    "attempt": 2,
                    "baseline": {"elapsed": None, "outcome": "timeout", "streak": 0},
                    "patched": None,
                    "delta_s": None,
                }],
            },
            "provenance.json": {
                "schema": "qw-gap-proof-provenance/1",
                "graph_sha": "1" * 64, "patch_sha": "2" * 64, "bsp_sha": "3" * 64,
                "cvar_readback": {
                    side: {name: {"value": 0} for name in core.TRIAL_CVARS}
                    for side in ("baseline", "patched")
                },
            },
        }
        files = []
        for name, payload in payloads.items():
            path = proof / name
            path.write_text(json.dumps(payload))
            files.append({"file": name,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        (proof / "manifest.json").write_text(json.dumps({
            "schema": "qw-gap-proof-manifest/1", "partial": False, "files": files,
        }))
        patches = root / "patches"
        patches.mkdir()
        (patches / "proof.json").write_text(json.dumps(payloads["patch.json"]))

    def rewrite_manifest_sha(self, root: Path, filename: str) -> None:
        proof = root / "evidence" / "proof"
        manifest_path = proof / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["files"]:
            if entry["file"] == filename:
                entry["sha256"] = hashlib.sha256((proof / filename).read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))

    def test_promote_requires_patched_streak_not_legacy_ok_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_proof(root, streak=4, passed=True)
            with patch.object(core, "EVIDENCE_DIR", root / "evidence"), \
                    patch.object(core, "PATCHES_DIR", root / "patches"), \
                    patch.object(core, "PROMOTE_DIR", root / "promoted"):
                with self.assertRaisesRegex(RuntimeError, "streak"):
                    core.promote("proof", "test")

    def test_promote_copies_complete_proof_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_proof(root, streak=5, passed=True)
            with patch.object(core, "EVIDENCE_DIR", root / "evidence"), \
                    patch.object(core, "PATCHES_DIR", root / "patches"), \
                    patch.object(core, "PROMOTE_DIR", root / "promoted"):
                result = core.promote("proof", "test")
            self.assertEqual(result["evidence"]["patched_streak"], 5)
            copied = Path(result["proof_bundle"])
            self.assertTrue((copied / "manifest.json").exists())
            self.assertTrue((copied / "ab.json").exists())

    def test_promote_rejects_sha_valid_bundle_without_attempt_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_proof(root, streak=5, passed=True)
            ab_path = root / "evidence" / "proof" / "ab.json"
            ab = json.loads(ab_path.read_text())
            ab["attempts"] = []
            ab_path.write_text(json.dumps(ab))
            self.rewrite_manifest_sha(root, "ab.json")
            with patch.object(core, "EVIDENCE_DIR", root / "evidence"), \
                    patch.object(core, "PATCHES_DIR", root / "patches"), \
                    patch.object(core, "PROMOTE_DIR", root / "promoted"):
                with self.assertRaisesRegex(RuntimeError, "A/B evidence is invalid"):
                    core.promote("proof", "test")


if __name__ == "__main__":
    unittest.main()
