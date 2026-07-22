from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from live_bridge import (  # noqa: E402
    Attribution,
    GraphContract,
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
