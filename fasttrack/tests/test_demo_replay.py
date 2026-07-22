from __future__ import annotations

import asyncio
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from demo_replay import PlaybackCoordinator, ReplayServer  # noqa: E402
from live_bridge import GraphContract, _read_ws_frame, _ws_frame  # noqa: E402


def graph_contract() -> GraphContract:
    return GraphContract(
        path=Path("fixture.json"), name="fixture", sha256="abc", cells=[[0, 0, 0]],
        links=[], cell_ids=[1], link_ids=[], links_by_cells={}, cell_z_by_id={1: 0.0},
        cell_by_id={1: [0, 0, 0]},
    )


def timeline():
    base = {"pos": [0, 0, 0], "speed": 0, "cell_id": 1,
            "used": {"cells": [1], "links": [9]},
            "missing": {"cells": [[3, 4, 5]], "links": [{"from": [0, 0, 0],
                                                            "to": [1, 1, 1]}]}}
    return [{**base, "t": value} for value in (0.0, 1.0, 2.0)]


class PlaybackCoordinatorTests(unittest.TestCase):
    def test_play_pause_stop_finished_and_clock_offset_without_time_jump(self):
        playback = PlaybackCoordinator(timeline(), speed=1.0, loop_playback=False, now=10.0)
        playback.advance(10.75)
        self.assertEqual(playback.state, "playing")
        self.assertAlmostEqual(playback.t, 0.75)
        playback.command("pause", 10.75)
        playback.advance(20.0)
        self.assertAlmostEqual(playback.t, 0.75)
        playback.command("play", 20.0)
        playback.advance(20.25)
        self.assertAlmostEqual(playback.t, 1.0)
        playback.advance(22.0)
        self.assertEqual(playback.state, "finished")
        self.assertEqual(playback.index, 2)
        playback.command("play", 30.0)
        self.assertEqual((playback.state, playback.index, playback.t), ("playing", 0, 0.0))
        attempt = playback.attempt_id
        playback.command("stop", 30.5)
        self.assertEqual((playback.state, playback.index, playback.t), ("stopped", 0, 0.0))
        self.assertEqual(playback.attempt_id, attempt + 1)
        stopped, _ = playback.snapshot()
        self.assertEqual(stopped["pos"], timeline()[0]["pos"])
        self.assertEqual(stopped["used"], {"cells": [], "links": []})
        self.assertEqual(stopped["missing"], {"cells": [], "links": []})
        stopped_attempt = playback.attempt_id
        playback.command("play", 31.0)
        self.assertEqual((playback.state, playback.index, playback.t), ("playing", 0, 0.0))
        self.assertEqual(playback.attempt_id, stopped_attempt)


class ReplayWebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.replay = ReplayServer(graph_contract(), timeline(), 0, 20.0, True)
        await self.replay.start()

    async def asyncTearDown(self):
        await self.replay.close()

    async def connect(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.replay.ws_port)
        writer.write(
            b"GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
        )
        await writer.drain()
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
        return reader, writer

    async def test_churn_and_slow_client_do_not_block_fresh_handshake_or_frames(self):
        dead = []
        for _ in range(5):
            _, writer = await self.connect()
            writer.close()
            dead.append(writer.wait_closed())
        await asyncio.gather(*dead)
        slow_reader, slow_writer = await self.connect()
        _ = slow_reader
        slow_port = slow_writer.get_extra_info("sockname")[1]
        slow_client = next(client for client in self.replay.clients
                           if client.writer.get_extra_info("peername")[1] == slow_port)
        never_drains = asyncio.Event()

        async def blocked_drain():
            await never_drains.wait()

        slow_client.writer.drain = blocked_drain
        await asyncio.sleep(0.1)  # let that client's sole writer enter blocked drain
        fresh_reader, fresh_writer = await asyncio.wait_for(self.connect(), 1)
        opcode, payload = await asyncio.wait_for(_read_ws_frame(fresh_reader), 1)
        self.assertEqual(opcode, 1)
        self.assertIn("playback", json.loads(payload))
        slow_writer.close()
        fresh_writer.close()
        await asyncio.gather(slow_writer.wait_closed(), fresh_writer.wait_closed())

    async def test_old_producer_frame_without_playback_remains_valid_json(self):
        old_frame = {"schema": "qw-live-frame/1", "seq": 1, "bots": []}
        decoded = json.loads(json.dumps(old_frame))
        self.assertNotIn("playback", decoded)
        self.assertIsNone(decoded.get("playback"))

    async def test_reader_queues_commands_and_logs_bad_or_oversized_messages(self):
        _, writer = await self.connect()
        writer.write(_ws_frame(json.dumps({"cmd": "pause"}).encode()))
        await writer.drain()
        for _ in range(20):
            if self.replay.playback.state == "paused":
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.replay.playback.state, "paused")
        with self.assertLogs("fasttrack.demo_replay", level="WARNING") as logs:
            writer.write(_ws_frame(b"not-json"))
            writer.write(_ws_frame(b"x" * 1025))
            await writer.drain()
            await asyncio.sleep(0.05)
        self.assertTrue(any("malformed" in line for line in logs.output))
        self.assertTrue(any("oversized" in line for line in logs.output))
        writer.close()
        await writer.wait_closed()


class OfflineDeterminismTests(unittest.TestCase):
    def test_timeline_and_missing_spec_match_across_hash_seeds(self):
        script = r'''
import hashlib, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "fasttrack")
import core, demo_mesh
from demo_replay import build_timeline
from live_bridge import GraphContract

samples = {"start": (0.0, 0.0, 0.0, 0.0, 0.0),
           "same-time-a": (0.1, 0.0, 0.0, 0.0, 0.0),
           "same-time-b": (0.1, 96.0, 0.0, 0.0, 300.0),
           "end": (0.3, 96.0, 0.0, 0.0, 0.0)}
demo_mesh.load_samples = lambda *_args, **_kwargs: [samples[key] for key in set(samples)]
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    graph_path = root / "test-graph.json"
    graph_path.write_text(json.dumps({"schema":"qw-nav-graph/1","map":"test","grid":32,
        "cells":[[0,0,0],[96,0,0]],"links":[[0,1,"Jump",1]],
        "cell_ids":[1,2],"link_ids":[9]}))
    core.PROMOTE_DIR = root
    core.VIEWER_WORKTREE = root
    core.OVERLAYS_DIR = root / "overlays"
    (root / "overlays").mkdir()
    (root / "overlays" / "test-graph.json").write_bytes(graph_path.read_bytes())
    core._wsl_path = lambda value: value
    demo = root / "fixture.qwd"
    demo.write_bytes(b"fixture")
    timeline = build_timeline(str(demo), GraphContract.load(graph_path))
    result = core.missing_spec("det", "test", str(demo))
    spec = json.loads(Path(result["spec"]).read_text())
    whole = json.dumps({"timeline": timeline, "spec": spec}, sort_keys=True,
                       separators=(",", ":"), allow_nan=False).encode()
    print(hashlib.sha256(whole).hexdigest())
'''
        hashes = []
        for seed in ("1", "2"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            run = subprocess.run([sys.executable, "-c", script], cwd=HERE.parents[1],
                                 env=env, capture_output=True, text=True, check=True)
            hashes.append(run.stdout.strip())
        self.assertEqual(hashes[0], hashes[1])


if __name__ == "__main__":
    unittest.main()
