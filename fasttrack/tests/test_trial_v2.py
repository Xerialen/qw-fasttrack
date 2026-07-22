from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import core  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeControl:
    scripts: list[list[list[float]] | str] = []

    def __init__(self):
        self.events = []
        self.attempt = -1
        self.poll = 0
        self.commands = []

    def close(self):
        pass

    def request(self, command, timeout=15.0, before_send=None):
        self.commands.append(command)
        if command.startswith("get "):
            return {"data": {"string": "0", "value": 0.0}}
        if command.startswith("teleport "):
            self.attempt += 1
            self.poll = 0
            return {"data": {}}
        if command.startswith("goto "):
            if before_send:
                before_send()
            return {"data": {}}
        if command == "status":
            if self.attempt < 0:
                origin = [0.0, 0.0, 0.0]
            else:
                script = self.scripts[self.attempt]
                if script == "setup_failed":
                    origin = [100.0, 0.0, 0.0]
                else:
                    origin = script[min(self.poll, len(script) - 1)]
                    self.poll += 1
            return {"data": {"navmesh": "ready", "map": "test",
                              "cells": 2, "links": 1, "matchtag": "trial-test",
                              "bots": [{"ent": 7, "alive": True, "origin": origin}]}}
        return {"data": {}}


class TrialV2Tests(unittest.TestCase):
    def run_trial(self, scripts, **kwargs):
        clock = FakeClock()
        FakeControl.scripts = scripts
        with tempfile.TemporaryDirectory() as temp:
            active_graph = Path(temp) / "active-graph.json"
            active_graph.write_text(json.dumps({
                "map": "test", "cells": 2, "links": 1, "sha256": "graph-sha-test",
            }))
            with \
                patch.object(core, "Control", FakeControl), \
                patch.object(core.time, "monotonic", clock.monotonic), \
                patch.object(core.time, "sleep", clock.sleep), \
                patch.object(core, "EVIDENCE_DIR", Path(temp)), \
                patch.object(core, "ACTIVE_GRAPH", active_graph):
                result = core.trial(
                    [0, 0, 0], [100, 0, 0], arrive_box=[9, -1, -1, 11, 1, 1],
                    settle_s=0, pass_time_s=kwargs.pop("pass_time_s", 1.0),
                    streak_target=kwargs.pop("streak_target", 2),
                    max_time_s=kwargs.pop("max_time_s", 0.25),
                    attempts_cap=kwargs.pop("attempts_cap", len(scripts)), **kwargs,
                )
                ledger = json.loads(next(Path(temp).glob("*.jsonl")).read_text())
        return result, ledger

    def test_fail_resets_streak(self):
        success = [[0, 0, 0], [10, 0, 0]]
        timeout = [[0, 0, 0]]
        result, _ = self.run_trial([success, timeout, success, success])
        self.assertTrue(result["passed"])
        self.assertEqual([row["streak"] for row in result["rows"]], [1, 0, 1, 2])
        self.assertEqual(result["streak_max"], 2)

    def test_timeout_is_a_failed_attempt(self):
        result, _ = self.run_trial([[[0, 0, 0]]], streak_target=1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["rows"][0]["outcome"], "timeout")
        self.assertIsNone(result["rows"][0]["elapsed"])

    def test_setup_origin_error_over_24_units_fails_without_goto(self):
        result, _ = self.run_trial(["setup_failed"], streak_target=1)
        self.assertEqual(result["rows"][0]["outcome"], "setup_failed")
        self.assertIsNone(result["rows"][0]["elapsed"])

    def test_elapsed_uses_received_position_timestamp_and_ledger_has_provenance(self):
        result, ledger = self.run_trial(
            [[[0, 0, 0], [0, 0, 0], [10, 0, 0]]], streak_target=1)
        row = result["rows"][0]
        self.assertAlmostEqual(row["elapsed"], 1.0 / 15.0, places=6)
        self.assertEqual(row["box_entry_pos"], [10.0, 0.0, 0.0])
        for key in ("arrive_box", "max_time_s", "pass_time_s", "streak_target",
                    "graph_sha", "patch_sha", "matchtag", "cvar_readback"):
            self.assertIn(key, ledger["provenance"])
        self.assertEqual(set(ledger["provenance"]["cvar_readback"]), {
            "rtx_bot_ledgecap", "rtx_walljump", "rtx_doublejump", "rtx_bot_bhop",
        })
        self.assertEqual(ledger["provenance"]["graph_sha"], "graph-sha-test")

    def test_v2_requires_arrive_box_and_does_not_fall_back_to_events(self):
        with self.assertRaisesRegex(ValueError, "requires arrive_box"):
            core.trial([0, 0, 0], [1, 1, 1], streak_target=1)

    def test_v2_fails_closed_without_graph_provenance(self):
        clock = FakeClock()
        FakeControl.scripts = [[[0, 0, 0]]]
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(core, "Control", FakeControl), \
                patch.object(core.time, "monotonic", clock.monotonic), \
                patch.object(core.time, "sleep", clock.sleep), \
                patch.object(core, "ACTIVE_GRAPH", Path(temp) / "missing.json"):
            with self.assertRaisesRegex(RuntimeError, "run graph_dump"):
                core.trial([0, 0, 0], [1, 1, 1], arrive_box=[0, 0, 0, 1, 1, 1],
                           streak_target=1)


if __name__ == "__main__":
    unittest.main()
