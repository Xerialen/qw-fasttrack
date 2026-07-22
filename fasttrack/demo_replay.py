"""Replay a qwd on the navmesh over WebSocket — the creation loop.

The owner hands over one or more qwds; the player's movement plays back on
the Movement Lab mesh in real time. Elements the movement USES are
highlighted; everything the movement needed that the mesh LACKS glows red
(unmeshed ground, linkless traversals) with exact geometry — ready to add
to the mesh (demo_ingest emits the matching qw-nav-patch/1).

Needs NO game server: qwd file + graph JSON -> WS frames -> viewer.

Run (WSL):
  nice -n 19 python3 demo_replay.py --demo xersng.qwd \
      --graph .../fasttrack-graph.json [--speed 1.0] [--loop] [--ws-port 8093]

Viewer: http://127.0.0.1:8090/?graph=<name>&live=<ws-port>
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import bisect
import hashlib
import json
import logging
import math
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_mesh  # noqa: E402
from live_bridge import Attribution, GraphContract, _ws_frame  # noqa: E402

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TICK_HZ = 20.0
CELL_XY = 24.0
CELL_Z = 40.0
MISS_SNAP = 32.0
MAX_CLIENT_MESSAGE = 1024
LOG = logging.getLogger("fasttrack.demo_replay")


class GraphMatcher:
    """Offline point->cell resolution against the graph file (no server)."""

    def __init__(self, graph: GraphContract):
        self.graph = graph
        self.columns: dict[tuple[int, int], list[int]] = {}
        for index, cell in enumerate(graph.cells):
            key = (math.floor(cell[0] / 32.0), math.floor(cell[1] / 32.0))
            self.columns.setdefault(key, []).append(index)

    def resolve(self, point) -> int | None:
        cx, cy = math.floor(point[0] / 32.0), math.floor(point[1] / 32.0)
        best, best_d = None, None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for index in self.columns.get((cx + dx, cy + dy), ()):
                    cell = self.graph.cells[index]
                    if (abs(cell[0] - point[0]) <= CELL_XY and abs(cell[1] - point[1]) <= CELL_XY
                            and abs(cell[2] - point[2]) <= CELL_Z):
                        d = (cell[0] - point[0]) ** 2 + (cell[1] - point[1]) ** 2
                        if best_d is None or d < best_d:
                            best, best_d = self.graph.cell_ids[index], d
        return best


def build_timeline(demo_path: str, graph: GraphContract, player: int | None = None) -> list[dict]:
    """Precompute per-sample playback state: pos, cell, used/missing sets."""
    # This public boundary also accepts alternate/test loaders; do not inherit
    # their iteration order even though the standard loader already sorts.
    samples = sorted(demo_mesh.load_samples(demo_path, player), key=demo_mesh.sample_sort_key)
    mask = demo_mesh.grounded_mask(samples)
    matcher = GraphMatcher(graph)
    attribution = Attribution()
    t0 = samples[0][0]

    used_cells: set[int] = set()
    used_links: set[int] = set()
    missing_cells: dict[tuple, list[float]] = {}
    missing_links: list[dict] = []

    timeline = []
    airborne_from: int | None = None
    airborne_point = None
    for i, (t, x, y, z, speed) in enumerate(samples):
        grounded = mask[i]
        cell = matcher.resolve((x, y, z)) if grounded else None
        if grounded:
            if cell is None:
                key = (math.floor(x / MISS_SNAP), math.floor(y / MISS_SNAP), math.floor(z / MISS_SNAP))
                missing_cells.setdefault(key, [round(x, 1), round(y, 1), round(z, 1)])
            else:
                if airborne_from is not None and airborne_from != cell:
                    hit = (graph.links_by_cells.get((airborne_from, cell), ())
                           or graph.fuzzy_links(airborne_from, cell))
                    if hit:
                        used_links.update(hit)
                    else:
                        missing_links.append({
                            "from": [round(v, 1) for v in airborne_point],
                            "to": [round(x, 1), round(y, 1), round(z, 1)],
                        })
                airborne_from = None
                attribution.observe(cell, t, graph)
                used_cells.add(cell)
                used_links |= attribution.used_links
        else:
            if airborne_from is None and attribution.last_cell is not None:
                airborne_from = attribution.last_cell
                prev = samples[i - 1] if i else samples[i]
                airborne_point = [prev[1], prev[2], prev[3]]
        timeline.append({
            "t": t - t0,
            "pos": [round(x, 2), round(y, 2), round(z, 2)],
            "speed": round(speed if speed is not None else 0.0, 1),
            "cell_id": cell,
            "used": {"cells": sorted(used_cells), "links": sorted(used_links)},
            "missing": {"cells": [list(v) for v in missing_cells.values()],
                        "links": [dict(m) for m in missing_links]},
        })
    return timeline


class PlaybackCoordinator:
    """Single owner of the replay playhead, clock offset, and state."""

    VALID_COMMANDS = {"play", "pause", "stop"}

    def __init__(self, timeline: list[dict], speed: float, loop_playback: bool,
                 now: float | None = None):
        if not timeline:
            raise ValueError("timeline must not be empty")
        if speed <= 0:
            raise ValueError("speed must be positive")
        self.timeline = timeline
        self.times = [float(frame["t"]) for frame in timeline]
        self.speed = speed
        self.loop_playback = loop_playback
        self.state = "playing"
        self.index = 0
        self.t = 0.0
        self.attempt_id = 1
        self.clock_offset = time.monotonic() if now is None else now

    def _restart(self, now: float, *, increment_attempt: bool) -> None:
        if increment_attempt:
            self.attempt_id += 1
        self.state = "playing"
        self.index = 0
        self.t = 0.0
        self.clock_offset = now

    def advance(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self.state != "playing":
            return
        duration = self.times[-1]
        candidate = max(0.0, (now - self.clock_offset) * self.speed)
        if candidate >= duration:
            if self.loop_playback and duration > 0:
                loops = max(1, int(candidate // duration))
                self.attempt_id += loops
                candidate %= duration
                self.clock_offset = now - candidate / self.speed
            else:
                self.t = duration
                self.index = len(self.timeline) - 1
                self.state = "finished"
                return
        self.t = candidate
        self.index = max(0, bisect.bisect_right(self.times, self.t) - 1)

    def command(self, command: str, now: float | None = None) -> None:
        if command not in self.VALID_COMMANDS:
            raise ValueError(f"unknown playback command {command!r}")
        now = time.monotonic() if now is None else now
        self.advance(now)
        if command == "pause":
            if self.state == "playing":
                self.state = "paused"
        elif command == "stop":
            self.state = "stopped"
            self.index = 0
            self.t = 0.0
            self.attempt_id += 1
            self.clock_offset = now
        elif self.state == "paused":
            self.state = "playing"
            self.clock_offset = now - self.t / self.speed
        elif self.state in ("stopped", "finished"):
            self._restart(now, increment_attempt=self.state == "finished")

    def snapshot(self) -> tuple[dict, dict]:
        state = self.timeline[self.index]
        if self.state == "stopped":
            state = {**state, "used": {"cells": [], "links": []},
                     "missing": {"cells": [], "links": []}}
        return state, {"state": self.state, "t": self.t}


@dataclass(eq=False)
class ReplayClient:
    writer: asyncio.StreamWriter
    outgoing: asyncio.Queue[bytes]
    writer_task: asyncio.Task | None = None


class ReplayServer:
    def __init__(self, graph: GraphContract, timeline: list[dict],
                 ws_port: int, speed: float, loop_playback: bool):
        self.graph = graph
        self.timeline = timeline
        self.ws_port = ws_port
        self.speed = speed
        self.loop_playback = loop_playback
        self.playback = PlaybackCoordinator(timeline, speed, loop_playback)
        self.clients: set[ReplayClient] = set()
        self.commands: asyncio.Queue[dict] = asyncio.Queue()
        self.seq = 0
        self._server: asyncio.Server | None = None
        self._tick_task: asyncio.Task | None = None
        self._command_task: asyncio.Task | None = None
        self._closed = asyncio.Event()

    @staticmethod
    async def _read_client_frame(
            reader: asyncio.StreamReader) -> tuple[int, bytes | None, int]:
        first, second = await reader.readexactly(2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", await reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await reader.readexactly(8))[0]
        mask = await reader.readexactly(4) if masked else b""
        if length > MAX_CLIENT_MESSAGE:
            remaining = length
            while remaining:
                chunk = await reader.readexactly(min(remaining, 65536))
                remaining -= len(chunk)
            return opcode, None, length
        payload = await reader.readexactly(length)
        if masked:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return opcode, payload, length

    @staticmethod
    def _enqueue(client: ReplayClient, encoded: bytes) -> None:
        if client.outgoing.full():
            try:
                client.outgoing.get_nowait()
            except asyncio.QueueEmpty:
                pass
        client.outgoing.put_nowait(encoded)

    async def _writer(self, client: ReplayClient) -> None:
        try:
            while True:
                encoded = await client.outgoing.get()
                client.writer.write(encoded)
                await client.writer.drain()
        except (asyncio.CancelledError, ConnectionError, OSError):
            pass
        finally:
            self.clients.discard(client)
            client.writer.close()

    async def _disconnect(self, client: ReplayClient) -> None:
        self.clients.discard(client)
        if client.writer_task is not None and client.writer_task is not asyncio.current_task():
            client.writer_task.cancel()
            await asyncio.gather(client.writer_task, return_exceptions=True)
        client.writer.close()
        try:
            await asyncio.wait_for(client.writer.wait_closed(), 1.0)
        except (OSError, TimeoutError):
            pass

    async def _ws_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2.0)
            headers = {}
            for line in request.decode("latin1").split("\r\n")[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            key = headers.get("sec-websocket-key")
            if not key:
                raise ValueError("missing Sec-WebSocket-Key")
            accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode()
            writer.write(("HTTP/1.1 101 Switching Protocols\r\n"
                          "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode("ascii"))
            await writer.drain()
            client = ReplayClient(writer, asyncio.Queue(maxsize=1))
            client.writer_task = asyncio.create_task(self._writer(client), name="replay-client-writer")
            self.clients.add(client)
            while True:
                opcode, payload, length = await self._read_client_frame(reader)
                if payload is None:
                    LOG.warning("ignored oversized websocket message bytes=%d", length)
                    continue
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._enqueue(client, _ws_frame(payload, opcode=0xA))
                    continue
                if opcode != 0x1:
                    LOG.warning("ignored non-text websocket message opcode=%s", opcode)
                    continue
                try:
                    message = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    LOG.warning("ignored malformed websocket command")
                    continue
                if (not isinstance(message, dict)
                        or message.get("cmd") not in PlaybackCoordinator.VALID_COMMANDS):
                    LOG.warning("ignored unknown websocket command: %r", message)
                    continue
                await self.commands.put({"cmd": message["cmd"]})
        except (asyncio.IncompleteReadError, TimeoutError, ValueError, OSError) as exc:
            LOG.debug("websocket client disconnected: %s", exc)
        finally:
            if "client" in locals():
                await self._disconnect(client)
            else:
                writer.close()

    async def _broadcast(self, frame: dict) -> None:
        encoded = _ws_frame(json.dumps(frame, separators=(",", ":")).encode("utf-8"))
        for client in tuple(self.clients):
            self._enqueue(client, encoded)

    def _frame(self, state: dict, playback: dict, attempt: int) -> dict:
        self.seq += 1
        return {
            "schema": "qw-live-frame/1",
            "seq": self.seq,
            "t_mono": state["t"],
            "graph": {"name": self.graph.name, "cells": len(self.graph.cells),
                      "links": len(self.graph.links), "sha256": self.graph.sha256},
            "attempt_id": attempt,
            "playback": playback,
            "bots": [{"ent": 0, "pos": state["pos"], "speed": state["speed"],
                      "cell_id": state["cell_id"], "used": state["used"],
                      "missing": state["missing"]}],
        }

    async def _command_loop(self) -> None:
        try:
            while True:
                message = await self.commands.get()
                self.playback.command(message["cmd"])
        except asyncio.CancelledError:
            pass

    async def _tick_loop(self) -> None:
        try:
            while True:
                started = time.monotonic()
                self.playback.advance(started)
                state, playback = self.playback.snapshot()
                await self._broadcast(self._frame(state, playback, self.playback.attempt_id))
                await asyncio.sleep(max(0.0, 1.0 / TICK_HZ - (time.monotonic() - started)))
        except asyncio.CancelledError:
            pass

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._ws_client, "127.0.0.1", self.ws_port)
        self.ws_port = int(self._server.sockets[0].getsockname()[1])
        self.playback.clock_offset = time.monotonic() - self.playback.t / self.playback.speed
        self._command_task = asyncio.create_task(self._command_loop(), name="replay-commands")
        self._tick_task = asyncio.create_task(self._tick_loop(), name="replay-ticks")

    async def close(self) -> None:
        for task in (self._tick_task, self._command_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in (self._tick_task, self._command_task)
                               if task is not None), return_exceptions=True)
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        await asyncio.gather(*(self._disconnect(client) for client in tuple(self.clients)),
                             return_exceptions=True)
        self._closed.set()

    async def run(self) -> None:
        await self.start()
        final = self.timeline[-1]
        summary = {"missing_cells": len(final["missing"]["cells"]),
                   "missing_links": len(final["missing"]["links"]),
                   "used_cells": len(final["used"]["cells"]),
                   "used_links": len(final["used"]["links"])}
        print(f"replay ready: ws={self.ws_port} duration={final['t']:.1f}s "
              f"{json.dumps(summary)}", flush=True)
        try:
            await self._closed.wait()
        finally:
            await self.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", required=True)
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--ws-port", type=int, default=8093)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--player", type=int, default=None)
    parser.add_argument("--summary-only", action="store_true",
                        help="print the coverage summary and exit (no WS)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    graph = GraphContract.load(args.graph)
    timeline = build_timeline(args.demo, graph, args.player)
    if args.summary_only:
        final = timeline[-1]
        print(json.dumps({"duration_s": round(final["t"], 1),
                          "used": {k: len(v) for k, v in final["used"].items()},
                          "missing": final["missing"]}, indent=1))
        return 0
    asyncio.run(ReplayServer(graph, timeline, args.ws_port, args.speed, args.loop).run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
