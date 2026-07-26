"""Event-översättningen på kontrollkanalen: nya rtx-events får rätt etikett,
och okända events får INTE fälla en lyssnare.

Den andra halvan är den viktiga: motorn får nya Event-varianter innan den här
tabellen får dem, och alla events broadcastas till alla anslutna. Ett verktyg
som väntar på `arrived` delar socket med telemetrin, så ett okänt event måste
passera som data — inte som ett undantag.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core  # noqa: E402


class EventTranslationTests(unittest.TestCase):
    def test_new_variants_have_snake_case_labels(self):
        self.assertEqual(core._EVENT_NAMES["Pmove"], "pmove")
        self.assertEqual(core._EVENT_NAMES["BotStall"], "bot_stall")
        self.assertEqual(core._EVENT_NAMES["SeatHeartbeat"], "seat_heartbeat")

    def test_bot_stall_fields_pass_through(self):
        ev = core._translate_msg({"Event": {"BotStall": {
            "bot": 3, "t": 91.25, "reason": "displacement",
            "origin": [1874.5, -32.6, -127.0], "cell": 412, "goal_cell": 77,
            "goal_dist": 638.5, "link": 1901, "kind": "SpeedJump", "speed": 118.0,
            "route_len": 9, "route_pos": 4, "action": "penalize+repath"}}})
        self.assertEqual(ev["ev"], "bot_stall")
        self.assertEqual(ev["bot"], 3)
        self.assertEqual(ev["reason"], "displacement")
        self.assertEqual(ev["kind"], "SpeedJump")

    def test_seat_heartbeat_and_pmove_translate(self):
        hb = core._translate_msg({"Event": {"SeatHeartbeat": {
            "seat": "rex", "t": 128.0, "travelled": 14203.5, "rtt_ms": 12.5,
            "chokes": 3, "snapshot_age": 0.013, "signon": "Active",
            "nav_ready": True, "alive": True}}})
        self.assertEqual(hb["ev"], "seat_heartbeat")
        self.assertEqual(hb["seat"], "rex")
        pm = core._translate_msg({"Event": {"Pmove": {"t": 12.5, "players": []}}})
        self.assertEqual(pm["ev"], "pmove")
        self.assertEqual(pm["players"], [])

    def test_unknown_event_is_ignored_not_fatal(self):
        ev = core._translate_msg({"Event": {"SomethingNewEntirely": {"x": 1}}})
        self.assertEqual(ev["ev"], "somethingnewentirely")
        self.assertEqual(ev["x"], 1)

    def test_unit_variant_event_survives(self):
        # A fieldless variant arrives as a bare string, not a one-key map.
        self.assertEqual(core._translate_msg({"Event": "Reloaded"}), {"ev": "reloaded"})

    def test_wait_event_skips_unknown_events(self):
        # The real failure mode: a listener waiting for one label must not be
        # derailed by an unrelated event sharing the socket.
        ctl = core.Control.__new__(core.Control)
        ctl.events = [
            core._translate_msg({"Event": {"Pmove": {"t": 1.0, "players": []}}}),
            core._translate_msg({"Event": {"Whatever": {}}}),
            core._translate_msg({"Event": {"BotStall": {"bot": 1, "reason": "progress"}}}),
        ]
        got = ctl.wait_event(("bot_stall",), timeout=0.0)
        self.assertIsNotNone(got)
        self.assertEqual(got["reason"], "progress")


if __name__ == "__main__":
    unittest.main()
