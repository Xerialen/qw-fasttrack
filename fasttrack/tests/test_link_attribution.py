from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from live_bridge import (  # noqa: E402
    Attribution,
    GraphContract,
    GraphMatcher,
    LiveBridge,
    _next_unresolved_streak,
)


GRAPH = Path("/mnt/c/Users/benya/projects/quakeworld/route-lab/qw-nav-viewer/overlays/fasttrack-graph.json")


class LinkAttributionTests(unittest.TestCase):
    def test_recorded_sng_sequence_attributes_canonical_links_once_per_attempt(self):
        fixture = json.loads((HERE / "fixtures" / "sng_status_sequence.json").read_text())
        graph = GraphContract.load(GRAPH)
        state = Attribution()
        for sample in fixture["samples"]:
            if sample["cell"] is not None:
                state.observe(sample["cell"], sample["t"], graph)
        planted = set(fixture["planted_link_ids"])
        self.assertEqual(state.used_links, planted)
        self.assertTrue(all(list(sorted(state.used_links)).count(link_id) == 1
                            for link_id in planted))
        state.reset()
        self.assertEqual(state.used_links, set())

    def test_missing_ground_streak_requires_consecutive_z_stability(self):
        streak = 0
        prev_z = None
        stamped = False
        for z in (56.0, 56.0, 56.0):
            streak = _next_unresolved_streak(streak, z, prev_z)
            prev_z = z
            stamped |= streak >= 3
        self.assertTrue(stamped)

        streak = 0
        prev_z = None
        stamped = False
        for z in (100.0, 106.0, 109.0, 110.7, 109.0, 106.0):
            streak = _next_unresolved_streak(streak, z, prev_z)
            prev_z = z
            stamped |= streak >= 3
        self.assertFalse(stamped)


class PushPmoveTests(unittest.IsolatedAsyncioTestCase):
    async def test_authoritative_one_frame_contact_is_recorded_and_attributed_locally(self):
        graph = GraphContract(
            path=Path("fixture.json"),
            name="fixture",
            sha256="abc",
            cells=[[0, 0, 0], [100, 0, 0], [200, 0, 0]],
            links=[[0, 1, "JumpGap", 0.2], [1, 2, "JumpGap", 0.2]],
            cell_ids=[10, 20, 30],
            link_ids=[101, 102],
            links_by_cells={(10, 20): (101,), (20, 30): (102,)},
            cell_z_by_id={10: 0.0, 20: 0.0, 30: 0.0},
            cell_by_id={10: [0, 0, 0], 20: [100, 0, 0], 30: [200, 0, 0]},
        )
        self.assertEqual(GraphMatcher(graph).resolve([101, 1, 0]), 20)
        with tempfile.TemporaryDirectory() as td:
            record = Path(td) / "pmove.jsonl"
            bridge = LiveBridge(graph, record_path=record, push=True)
            bridge.request = mock.AsyncMock(side_effect=AssertionError("push must not poll"))
            events = [
                (0.000, [0, 0, 0], [320, 0, 0], True),
                (0.130, [50, 0, 40], [380, 0, 120], False),
                (0.260, [100, 0, 0], [450, 0, 0], True),
                (0.390, [150, 0, 40], [470, 0, 120], False),
                (0.520, [200, 0, 0], [480, 0, 0], True),
            ]
            for server_time, origin, velocity, on_ground in events:
                await bridge._route_event({
                    "ev": "pmove",
                    "t": server_time,
                    "players": [{
                        "ent": 1,
                        "origin": origin,
                        "vel": velocity,
                        "on_ground": on_ground,
                        "ground_ent": 0 if on_ground else -1,
                    }],
                })

            state = bridge.attribution[1]
            self.assertEqual(state.used_cells, {10, 20, 30})
            self.assertEqual(state.used_links, {101, 102})
            assert bridge.last_frame is not None
            self.assertEqual(bridge.last_frame["schema"], "qw-live-frame/1")
            self.assertEqual(bridge.last_frame["bots"][0]["cell_id"], 30)
            rows = [json.loads(line) for line in record.read_text().splitlines()]
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[2], {
                "t": 0.260,
                "ent": 1,
                "origin": [100.0, 0.0, 0.0],
                "vel": [450.0, 0.0, 0.0],
                "on_ground": True,
                "ground_ent": 0,
            })
            bridge.request.assert_not_awaited()

    async def test_empty_players_heartbeat_keeps_push_alive(self):
        # Bridge started before the human connects: the build's empty pmove
        # event is liveness proof — the watchdog must NOT fall back to poll.
        graph = GraphContract(
            path=Path("fixture.json"), name="fixture", sha256="abc", cells=[],
            links=[], cell_ids=[], link_ids=[], links_by_cells={},
            cell_z_by_id={}, cell_by_id={},
        )
        bridge = LiveBridge(graph, push=True)
        bridge.request = mock.AsyncMock(side_effect=AssertionError("no control traffic expected"))
        await bridge._route_event({"ev": "pmove", "t": 0.0, "players": []})
        self.assertTrue(bridge._pmove_seen.is_set())
        with mock.patch("live_bridge.PUSH_FALLBACK_S", 0.01):
            await bridge._push_watchdog()
        self.assertTrue(bridge.push_active)
        assert bridge.last_frame is not None
        self.assertEqual(bridge.last_frame["bots"], [])
        bridge.request.assert_not_awaited()

    async def test_missing_pmove_for_five_second_window_falls_back_to_poll(self):
        graph = GraphContract(
            path=Path("fixture.json"), name="fixture", sha256="abc", cells=[],
            links=[], cell_ids=[], link_ids=[], links_by_cells={},
            cell_z_by_id={}, cell_by_id={},
        )
        bridge = LiveBridge(graph, push=True)
        bridge.request = mock.AsyncMock(return_value={"ok": True})
        with (
            mock.patch("live_bridge.PUSH_FALLBACK_S", 0.01),
            self.assertLogs("fasttrack.live_bridge", level="WARNING") as logs,
        ):
            await bridge._push_watchdog()
        self.assertFalse(bridge.push_active)
        bridge.request.assert_awaited_once_with("set rtx_telemetry 0", timeout=2.0)
        self.assertTrue(any("falling back to poll mode" in line for line in logs.output))


class ProxyRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        self.server_writer = None

        async def fake_server(reader, writer):
            self.server_writer = writer
            try:
                while line := await reader.readline():
                    sid, command = line.decode().strip().split(" ", 1)
                    await self.received.put((int(sid), command))
            finally:
                writer.close()

        self.fake = await asyncio.start_server(fake_server, "127.0.0.1", 31990)
        port = 31990
        self.bridge = LiveBridge(GraphContract.load(GRAPH), control_port=port)
        await asyncio.wait_for(self.bridge.connect_upstream(), 3)
        self.proxy, self.bridge.proxy_port = await self.bridge._bind_server(
            self.bridge._proxy_client, 32000
        )

    async def asyncTearDown(self):
        self.proxy.close()
        await self.proxy.wait_closed()
        await self.bridge.close()
        self.fake.close()
        await self.fake.wait_closed()

    async def test_two_clients_share_global_sids_and_receive_original_ids(self):
        r1, w1 = await asyncio.open_connection("127.0.0.1", self.bridge.proxy_port)
        r2, w2 = await asyncio.open_connection("127.0.0.1", self.bridge.proxy_port)
        w1.write(b"7 status\n")
        w2.write(b"7 cell 0 0 0\n")
        await asyncio.gather(w1.drain(), w2.drain())
        first = await asyncio.wait_for(self.received.get(), 1)
        second = await asyncio.wait_for(self.received.get(), 1)
        self.assertNotEqual(first[0], second[0])
        assert self.server_writer is not None
        for sid, _ in (second, first):
            self.server_writer.write(
                json.dumps({"id": sid, "ok": True, "data": {"sid": sid}}).encode() + b"\n"
            )
        await self.server_writer.drain()
        replies = await asyncio.gather(r1.readline(), r2.readline())
        parsed = [json.loads(reply) for reply in replies]
        self.assertEqual([reply["id"] for reply in parsed], [7, 7])
        w1.close()
        w2.close()
        await asyncio.wait_for(asyncio.gather(w1.wait_closed(), w2.wait_closed()), 2)

    async def test_disconnect_cleans_pending_and_late_reply_is_discarded(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.bridge.proxy_port)
        _ = reader
        writer.write(b"9 status\n")
        await writer.drain()
        sid, _ = await asyncio.wait_for(self.received.get(), 1)
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), 2)
        for _ in range(50):
            if sid not in self.bridge.pending:
                break
            await asyncio.sleep(0.01)
        self.assertNotIn(sid, self.bridge.pending)
        assert self.server_writer is not None
        self.server_writer.write(json.dumps({"id": sid, "ok": True, "data": {}}).encode() + b"\n")
        await self.server_writer.drain()
        await asyncio.sleep(0.05)
        self.assertNotIn(sid, self.bridge.pending)


if __name__ == "__main__":
    unittest.main()
