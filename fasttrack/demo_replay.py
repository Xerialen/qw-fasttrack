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
import hashlib
import json
import math
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_mesh  # noqa: E402
from live_bridge import Attribution, GraphContract, _read_ws_frame, _ws_frame  # noqa: E402

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TICK_HZ = 20.0
CELL_XY = 24.0
CELL_Z = 40.0
MISS_SNAP = 32.0


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
    samples = demo_mesh.load_samples(demo_path, player)
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


class ReplayServer:
    def __init__(self, graph: GraphContract, timeline: list[dict],
                 ws_port: int, speed: float, loop_playback: bool):
        self.graph = graph
        self.timeline = timeline
        self.ws_port = ws_port
        self.speed = speed
        self.loop_playback = loop_playback
        self.clients: set[asyncio.StreamWriter] = set()
        self.seq = 0

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
            self.clients.add(writer)
            while True:
                opcode, payload = await _read_ws_frame(reader)
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    writer.write(_ws_frame(payload, opcode=0xA))
                    await writer.drain()
        except (asyncio.IncompleteReadError, TimeoutError, ValueError, OSError):
            pass
        finally:
            self.clients.discard(writer)
            writer.close()

    async def _broadcast(self, frame: dict) -> None:
        encoded = _ws_frame(json.dumps(frame, separators=(",", ":")).encode("utf-8"))
        for writer in tuple(self.clients):
            try:
                writer.write(encoded)
                await writer.drain()
            except (ConnectionError, OSError):
                self.clients.discard(writer)
                writer.close()

    def _frame(self, state: dict, attempt: int) -> dict:
        self.seq += 1
        return {
            "schema": "qw-live-frame/1",
            "seq": self.seq,
            "t_mono": state["t"],
            "graph": {"name": self.graph.name, "cells": len(self.graph.cells),
                      "links": len(self.graph.links), "sha256": self.graph.sha256},
            "attempt_id": attempt,
            "bots": [{"ent": 0, "pos": state["pos"], "speed": state["speed"],
                      "cell_id": state["cell_id"], "used": state["used"],
                      "missing": state["missing"]}],
        }

    async def run(self) -> None:
        server = await asyncio.start_server(self._ws_client, "127.0.0.1", self.ws_port)
        final = self.timeline[-1]
        summary = {"missing_cells": len(final["missing"]["cells"]),
                   "missing_links": len(final["missing"]["links"]),
                   "used_cells": len(final["used"]["cells"]),
                   "used_links": len(final["used"]["links"])}
        print(f"replay ready: ws={self.ws_port} duration={final['t']:.1f}s "
              f"{json.dumps(summary)}", flush=True)
        attempt = 0
        try:
            while True:
                attempt += 1
                start = time.monotonic()
                index = 0
                while index < len(self.timeline):
                    elapsed = (time.monotonic() - start) * self.speed
                    while index < len(self.timeline) and self.timeline[index]["t"] <= elapsed:
                        index += 1
                    state = self.timeline[min(index, len(self.timeline)) - 1]
                    await self._broadcast(self._frame(state, attempt))
                    await asyncio.sleep(1.0 / TICK_HZ)
                if not self.loop_playback:
                    break
            # Hold the final state so the missing layer stays visible.
            while True:
                await self._broadcast(self._frame(self.timeline[-1], attempt))
                await asyncio.sleep(1.0 / TICK_HZ)
        finally:
            server.close()
            await server.wait_closed()


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
