from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import demo_mesh  # noqa: E402
from ground_oracle import GroundOracle, OracleUnavailable  # noqa: E402

DM3_SHA256 = "aec9edbb727c0a206edc2c0688775ce8242c0d51e1ee7583c7126c76f7c3b2f1"
XERSNG = Path("/mnt/c/nQuake/qw/matchinfo/demos/xersng.qwd")
FASTTRACK_GRAPH = Path(
    "/mnt/c/Users/benya/projects/quakeworld/route-lab-viewer-live/"
    "qw-nav-viewer/overlays/fasttrack-graph.json"
)


class GroundOracleTests(unittest.TestCase):
    def test_real_probe_acceptance_points_and_apex(self):
        with GroundOracle("dm3") as oracle:
            for point in (
                (-292.6, 548.2, 120.0),
                (310.1, 670.4, 56.0),
                (336.2, 666.1, 56.0),
                (83.3, 670.0, 40.0),
            ):
                response = oracle.probe(point)
                self.assertTrue(response["grounded"], (point, response))
                self.assertAlmostEqual(response["floor_z"], point[2] - 24.0, delta=1.0)
            self.assertFalse(oracle.probe((313.0, 586.0, 99.8))["grounded"])
            self.assertEqual(oracle.bsp_sha, DM3_SHA256)

    def test_unknown_is_flagged_and_falls_back_per_point(self):
        class UnknownOracle:
            def __init__(self):
                self.flagged = []

            def probe(self, _point):
                return {"grounded": False, "status": "unknown"}

            def note_unknown(self, index, point, response):
                self.flagged.append((index, point, response["status"]))

        samples = [(0.0, 0.0, 0.0, 56.0, 0.0), (0.01, 0.0, 0.0, 56.0, 0.0)]
        oracle = UnknownOracle()
        self.assertEqual(demo_mesh.grounded_mask(samples, oracle), [True, True])
        self.assertEqual([entry[0] for entry in oracle.flagged], [0, 1])

    def test_midrun_crash_discards_partial_oracle_classification(self):
        class CrashingOracle:
            instances = []

            def __init__(self, *_args, **_kwargs):
                self.calls = 0
                self.closed = False
                self.instances.append(self)

            def probe(self, _point):
                self.calls += 1
                if self.calls == 2:
                    raise OracleUnavailable("probe_crashed", "fixture crash")
                return {"grounded": False, "status": "ok"}

            def close(self):
                self.closed = True

        samples = [(0.0, 0.0, 0.0, 56.0, 0.0), (0.01, 0.0, 0.0, 56.0, 0.0)]
        with tempfile.TemporaryDirectory() as td:
            demo = Path(td) / "fixture.qwd"
            demo.write_bytes(b"fixture")
            graph = Path(td) / "graph.json"
            graph.write_text(json.dumps({"cells": [], "links": []}), encoding="utf-8")
            with (mock.patch.object(demo_mesh, "GroundOracle", CrashingOracle),
                  mock.patch.object(demo_mesh, "load_samples", return_value=samples)):
                result = demo_mesh.ingest(str(demo), "dm3", str(graph), "fixture")
        grounding = result["evidence"]["grounding"]
        self.assertEqual(grounding["method"], "heuristic")
        self.assertEqual(grounding["fallback_reason"]["code"], "probe_crashed")
        self.assertEqual(result["summary"]["cells_required"], 1)
        self.assertTrue(CrashingOracle.instances[0].closed)

    def test_timeout_is_structured(self):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "slow-probe"
            script.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = --probe-commit ]; then\n"
                "  echo 0000000000000000000000000000000000000000\n"
                "  exit 0\n"
                "fi\n"
                "sleep 2\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            with self.assertRaises(OracleUnavailable) as raised:
                GroundOracle("dm3", script, timeout_s=0.05)
        self.assertEqual(raised.exception.reason["code"], "probe_timeout")


class XersngOracleGoldenTests(unittest.TestCase):
    def test_real_oracle_missing_flow_keeps_surfaces_and_removes_apex_class(self):
        observed = {}
        classify = demo_mesh.grounded_mask

        def recording_mask(samples, oracle=None):
            mask = classify(samples, oracle)
            if oracle is not None:
                observed.update(samples=samples, mask=mask)
            return mask

        with mock.patch.object(demo_mesh, "grounded_mask", side_effect=recording_mask):
            oracle = demo_mesh.ingest(str(XERSNG), "dm3", str(FASTTRACK_GRAPH), "xersng")
        heuristic = demo_mesh.ingest(
            str(XERSNG), "dm3", str(FASTTRACK_GRAPH), "xersng",
            probe_path="/definitely/missing/bsp-probe",
        )

        self.assertEqual(oracle["evidence"]["grounding"]["method"], "oracle")
        self.assertEqual(oracle["evidence"]["grounding"]["bsp_sha"], DM3_SHA256)
        self.assertEqual(oracle["summary"]["cells_missing"], 4)
        self.assertEqual(heuristic["summary"]["cells_missing"], 4)
        self.assertEqual(oracle["summary"]["cells_missing_points"], [
            [-292.6, 548.2, 120.0],
            [79.5, 670.5, 40.0],
            [310.1, 670.4, 56.0],
            [336.2, 666.1, 56.0],
        ])
        self.assertTrue(all(point[2] in {40.0, 56.0, 120.0}
                            for point in oracle["summary"]["cells_missing_points"]))
        self.assertEqual(oracle["summary"]["cells_required"], 189)
        self.assertEqual(heuristic["summary"]["cells_required"], 182)
        for point in (
            (-292.6, 548.2, 120.0),
            (310.1, 670.4, 56.0),
            (336.2, 666.1, 56.0),
            (83.3, 670.0, 40.0),
        ):
            index = min(
                range(len(observed["samples"])),
                key=lambda i: math.dist(observed["samples"][i][1:4], point),
            )
            self.assertLess(math.dist(observed["samples"][index][1:4], point), 3.0)
            self.assertTrue(observed["mask"][index], (point, observed["samples"][index]))


if __name__ == "__main__":
    unittest.main()
