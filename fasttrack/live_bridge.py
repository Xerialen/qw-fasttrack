"""Single-owner RTX control proxy and live nav telemetry bridge.

The bridge is map-agnostic. It owns the one reliable connection to the game
control socket, proxies existing clients with a global request-ID namespace,
and broadcasts qw-live-frame/1 WebSocket text frames on loopback.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import math
import os
import secrets
import signal
import statistics
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import core as _ft  # verb->Cmd parsing and Msg->legacy-dict translation
import mpwire


LOG = logging.getLogger("fasttrack.live_bridge")
MISSING_GROUND_DZ_TOL = 2.0
# How long the msgpack handshake waits before concluding the control channel is
# legacy text. A real msgpack server answers a local Status in milliseconds, so
# this only ever runs to full length against a text server -- where it is dead
# time on every bridge start, and long enough to blow a caller's own timeout.
MSGPACK_PROBE_S = 1.0
PUSH_FALLBACK_S = 5.0
PUSH_BROADCAST_HZ = 15.0
STATE_FILE = Path.home() / ".local" / "share" / "qw-fasttrack" / "live-bridge.json"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TERMINAL_EVENTS = {"arrived", "goto_stall"}
INTERNAL = object()


def _next_unresolved_streak(streak: int, z: float, prev_z: float | None) -> int:
    """Advance only while consecutive unresolved ticks stay vertically still."""
    if prev_z is None:
        return 1
    if abs(z - prev_z) < MISSING_GROUND_DZ_TOL:
        return streak + 1
    return 0


def _json_line(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"


@dataclass
class GraphContract:
    path: Path
    name: str
    sha256: str
    cells: list[list[float]]
    links: list[list[Any]]
    cell_ids: list[int]
    link_ids: list[int]
    links_by_cells: dict[tuple[int, int], tuple[int, ...]]
    cell_z_by_id: dict[int, float]
    cell_by_id: dict[int, list[float]]

    def fuzzy_links(self, from_id: int, to_id: int,
                    xy_tol: float = 80.0, z_tol: float = 56.0) -> tuple[int, ...]:
        """Links whose endpoints lie within tolerance of the given cells.

        15 Hz sampling at speed-jump velocity (~30u/tick vs 32u cells) can
        miss the exact lip/landing cell, so a gap transition is matched
        geometrically instead of by exact cell pair."""
        a = self.cell_by_id.get(from_id)
        b = self.cell_by_id.get(to_id)
        if a is None or b is None:
            return ()

        def near(p, q):
            return (abs(p[0] - q[0]) <= xy_tol and abs(p[1] - q[1]) <= xy_tol
                    and abs(p[2] - q[2]) <= z_tol)

        hits = []
        for link_id, link in zip(self.link_ids, self.links):
            # Only traversal links: fuzzy-matching walk chains at 80u would
            # smear attribution over the whole neighbourhood.
            if str(link[2]).lower() not in ("speedjump", "jumpgap", "rocketjump", "drop"):
                continue
            src, dst = self.cells[int(link[0])], self.cells[int(link[1])]
            if near(src, a) and near(dst, b):
                hits.append(link_id)
        return tuple(sorted(hits))

    @classmethod
    def load(cls, path: str | Path) -> "GraphContract":
        graph_path = Path(path)
        raw = graph_path.read_bytes()
        document = json.loads(raw)
        if document.get("schema") != "qw-nav-graph/1":
            raise ValueError(f"unsupported graph schema {document.get('schema')!r}")
        cells = document.get("cells") or []
        links = document.get("links") or []
        cell_ids = document.get("cell_ids") or []
        link_ids = document.get("link_ids") or []
        if len(cell_ids) != len(cells) or len(link_ids) != len(links):
            raise ValueError("graph cell_ids/link_ids must match cells/links")
        if len(set(cell_ids)) != len(cell_ids) or len(set(link_ids)) != len(link_ids):
            raise ValueError("graph cell_ids/link_ids must be unique")
        by_pair: dict[tuple[int, int], list[int]] = {}
        for link_id, link in zip(link_ids, links, strict=True):
            source_index, target_index = int(link[0]), int(link[1])
            pair = (int(cell_ids[source_index]), int(cell_ids[target_index]))
            by_pair.setdefault(pair, []).append(int(link_id))
        stem = graph_path.stem
        name = stem[:-6] if stem.endswith("-graph") else stem
        return cls(
            path=graph_path,
            name=name,
            sha256=hashlib.sha256(raw).hexdigest()[:16],
            cells=cells,
            links=links,
            cell_ids=[int(value) for value in cell_ids],
            link_ids=[int(value) for value in link_ids],
            links_by_cells={key: tuple(sorted(value)) for key, value in by_pair.items()},
            cell_z_by_id={int(cid): float(cell[2]) for cid, cell in zip(cell_ids, cells, strict=True)},
            cell_by_id={int(cid): cell for cid, cell in zip(cell_ids, cells, strict=True)},
        )


class GraphMatcher:
    """Resolve world points against a graph file without control requests."""

    GRID = 32.0
    # A cell owns the grid square it sits in: half a pitch either way.
    CELL_XY = GRID / 2
    # Ground can sit up to a full pitch from the nearest cell centre and still be
    # the same continuous surface: the square that would cover it holds no cell
    # because a player hull cannot stand there (a wall is in the way), and no
    # rebuild at this pitch can ever produce one. Judging that "missing" reports
    # a hole where the carve is simply out of resolution -- and every wall-hugging
    # step a player takes then glows red, drowning the real gaps.
    NEAR_XY = GRID
    CELL_Z = 40.0

    COVERED = "covered"
    OFF_GRID = "off_grid"
    MISSING = "missing"

    def __init__(self, graph: GraphContract):
        self.graph = graph
        self.columns: dict[tuple[int, int], list[int]] = {}
        for index, cell in enumerate(graph.cells):
            key = (math.floor(cell[0] / self.GRID), math.floor(cell[1] / self.GRID))
            self.columns.setdefault(key, []).append(index)

    def classify(self, point) -> tuple[int | None, str]:
        """``(cell, verdict)`` for a grounded point.

        ``covered``  - inside a cell's own grid square; a bot can stand here.
        ``off_grid`` - no cell square covers it, but a cell within one pitch sits
                       at a compatible height. The bot cannot stand exactly here,
                       yet the ground is continuous with a cell it can stand on.
                       Resolution residue against an edge, not a gap to fill.
        ``missing``  - no cell within a pitch at a compatible height: a real hole,
                       ground the mesh does not represent at all.
        """
        cx, cy = math.floor(point[0] / self.GRID), math.floor(point[1] / self.GRID)
        best: int | None = None
        best_d: float | None = None
        best_dxy: tuple[float, float] = (0.0, 0.0)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for index in self.columns.get((cx + dx, cy + dy), ()):
                    cell = self.graph.cells[index]
                    ddx = abs(cell[0] - point[0])
                    ddy = abs(cell[1] - point[1])
                    if ddx > self.NEAR_XY or ddy > self.NEAR_XY:
                        continue
                    if abs(cell[2] - point[2]) > self.CELL_Z:
                        continue
                    distance = ddx * ddx + ddy * ddy
                    if best_d is None or distance < best_d:
                        best, best_d, best_dxy = self.graph.cell_ids[index], distance, (ddx, ddy)
        if best is None:
            return None, self.MISSING
        if best_dxy[0] <= self.CELL_XY and best_dxy[1] <= self.CELL_XY:
            return best, self.COVERED
        return best, self.OFF_GRID

    def resolve(self, point) -> int | None:
        """The cell a grounded point attributes to -- covered or off-grid alike.

        Off-grid ground must still attribute, or a player hugging a wall breaks
        the attribution chain and the next resolved cell is recorded as an
        unlinked traversal from wherever the chain last held: a phantom missing
        link hundreds of units long.
        """
        return self.classify(point)[0]


@dataclass
class Attribution:
    used_cells: set[int] = field(default_factory=set)
    used_links: set[int] = field(default_factory=set)
    last_cell: int | None = None
    pending_from: int | None = None
    pending_since: float | None = None
    # Mesh gaps this actor's movement REQUIRED but the graph lacks:
    # ground with no cell, traversals with no link. Rendered glowing red.
    missing_cells: dict = field(default_factory=dict)
    missing_links: list = field(default_factory=list)
    # Ground the actor used that is continuous with a cell but lies outside any
    # cell's own grid square -- the carve's resolution limit against an edge, not
    # a hole. Reported apart from `missing_cells` so the red layer stays a list
    # of things worth fixing.
    off_grid_cells: dict = field(default_factory=dict)

    def reset(self) -> None:
        self.used_cells.clear()
        self.used_links.clear()
        self.last_cell = None
        self.pending_from = None
        self.pending_since = None

    def note_missing_ground(self, position) -> None:
        key = (int(position[0] // 32), int(position[1] // 32), int(position[2] // 32))
        self.missing_cells.setdefault(
            key, [round(position[0], 1), round(position[1], 1), round(position[2], 1)])

    def note_off_grid(self, position) -> None:
        key = (int(position[0] // 32), int(position[1] // 32), int(position[2] // 32))
        self.off_grid_cells.setdefault(
            key, [round(position[0], 1), round(position[1], 1), round(position[2], 1)])

    def note_missing_traversal(self, from_point, to_point) -> None:
        entry = {"from": [round(v, 1) for v in from_point],
                 "to": [round(v, 1) for v in to_point]}
        if entry not in self.missing_links:
            self.missing_links.append(entry)

    def missing_payload(self) -> dict:
        return {"cells": [list(v) for v in self.missing_cells.values()],
                "links": [dict(m) for m in self.missing_links],
                "off_grid": [list(v) for v in self.off_grid_cells.values()]}

    def observe(self, cell: int, now: float, graph: GraphContract) -> None:
        self.used_cells.add(cell)
        if self.last_cell is None:
            self.last_cell = cell
            return
        if cell == self.last_cell:
            return

        if self.pending_from is not None:
            assert self.pending_since is not None
            if now - self.pending_since <= 1.0:
                hit = (graph.links_by_cells.get((self.pending_from, cell), ())
                       or graph.fuzzy_links(self.pending_from, cell))
                if hit:
                    self.used_links.update(hit)
                    self.pending_from = None
                    self.pending_since = None
            else:
                self.pending_from = None
                self.pending_since = None

        if self.pending_from is None:
            hit = (graph.links_by_cells.get((self.last_cell, cell), ())
                   or graph.fuzzy_links(self.last_cell, cell))
            if hit:
                self.used_links.update(hit)
            else:
                self.pending_from = self.last_cell
                self.pending_since = now
        self.last_cell = cell


@dataclass(eq=False)
class ProxyClient:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    pending_sids: set[int] = field(default_factory=set)
    connected: bool = True
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, message: dict[str, Any]) -> None:
        if not self.connected:
            return
        async with self.write_lock:
            self.writer.write(_json_line(message))
            await self.writer.drain()


@dataclass
class Pending:
    owner: ProxyClient | object
    client_id: int | None
    future: asyncio.Future[dict[str, Any]] | None = None


class LiveBridge:
    def __init__(
        self,
        graph: GraphContract,
        control_port: int = 27980,
        ws_port: int = 8093,
        proxy_port: int = 27981,
        control_host: str = "127.0.0.1",
        record_path: Path | None = None,
        push: bool = False,
    ) -> None:
        self.graph = graph
        self.graph_matcher = GraphMatcher(graph)
        self.record_path = record_path
        self.push_requested = push
        self.push_active = push
        self.control_host = control_host
        self.control_port = control_port
        self.requested_ws_port = ws_port
        self.requested_proxy_port = proxy_port
        self.ws_port = 0
        self.proxy_port = 0
        self.nonce = secrets.token_hex(16)
        self.started_at = time.time()
        self._mono_start = time.monotonic()
        self._upstream_reader: asyncio.StreamReader | None = None
        self._upstream_writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._telemetry_task: asyncio.Task[None] | None = None
        self._push_watchdog_task: asyncio.Task[None] | None = None
        self._proxy_server: asyncio.AbstractServer | None = None
        self._ws_server: asyncio.AbstractServer | None = None
        self._send_lock = asyncio.Lock()
        self._msgpack = False          # decided by the probe in connect_upstream
        self._next_sid = 1
        self.pending: dict[int, Pending] = {}
        self.proxy_clients: set[ProxyClient] = set()
        self.ws_clients: set[asyncio.StreamWriter] = set()
        self.goto_owner: dict[int, ProxyClient] = {}
        self.last_goto_owner: ProxyClient | None = None
        self.attribution: dict[int, Attribution] = {}
        self._actor_aux: dict[int, dict] = {}
        self.attempt_id = 0
        self.seq = 0
        self.latencies_ms: list[float] = []
        self.status_rtt_ms: list[float] = []
        self.tick_ms: list[float] = []
        self.ws_send_ms: list[float] = []
        self.last_frame: dict[str, Any] | None = None
        self._last_broadcast_seq = 0
        self._pmove_seen = asyncio.Event()
        self._player_names: dict[int, str] = {}
        self.stop_event = asyncio.Event()

    async def _open(self):
        # ra_trial_result-event bär upp till 4096 samples (~350 KB på EN rad) —
        # asyncios default-limit (64 KB) får readline att kasta ValueError och
        # döda bryggan mitt i en gate-körning (2026-07-23 em: live-vyn dog för
        # ägaren). 4 MiB rymmer värsta kända eventet med bred marginal.
        return await asyncio.open_connection(
            self.control_host, self.control_port, limit=4 * 1024 * 1024
        )

    async def connect_upstream(self) -> None:
        # The engine moved the control channel from newline-JSON to length-framed msgpack.
        # Probe msgpack first (a text server simply never answers an unterminated frame, so
        # the probe times out cleanly; a msgpack server resets a text line, which is not
        # recoverable) and keep the legacy path for older builds. `core` owns both the
        # verb->Cmd parsing and the Msg->legacy-dict translation, so everything downstream
        # of the reader keeps seeing exactly the dict shape it always saw.
        self._upstream_reader, self._upstream_writer = await self._open()
        self._msgpack = False
        try:
            self._upstream_writer.write(mpwire.pack_frame({"id": 0, "cmd": "Status"}))
            await self._upstream_writer.drain()
            head = await asyncio.wait_for(self._upstream_reader.readexactly(4), MSGPACK_PROBE_S)
            body = await asyncio.wait_for(
                self._upstream_reader.readexactly(int.from_bytes(head, "little")),
                MSGPACK_PROBE_S)
            _ft._translate_msg(mpwire.unpackb(body))
            self._msgpack = True
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError, TypeError,
                KeyError, OSError) as exc:
            LOG.info("control channel is legacy text (%s)", type(exc).__name__)
            self._upstream_writer.close()
            self._upstream_reader, self._upstream_writer = await self._open()
        LOG.info("control wire: %s", "msgpack" if self._msgpack else "text")
        self._reader_task = asyncio.create_task(self._upstream_loop(), name="control-reader")

    async def _read_upstream(self) -> dict[str, Any] | None:
        """One upstream message in the legacy dict shape, or None at end of stream."""
        assert self._upstream_reader is not None
        if not self._msgpack:
            line = await self._upstream_reader.readline()
            if not line:
                return None
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                LOG.warning("discarding invalid upstream JSON: %r", line[:200])
                return {}
        try:
            head = await self._upstream_reader.readexactly(4)
            body = await self._upstream_reader.readexactly(int.from_bytes(head, "little"))
        except asyncio.IncompleteReadError:
            return None
        try:
            return _ft._translate_msg(mpwire.unpackb(body))
        except (ValueError, TypeError, KeyError) as exc:
            LOG.warning("discarding undecodable upstream frame: %s", exc)
            return {}

    async def _upstream_loop(self) -> None:
        assert self._upstream_reader is not None
        try:
            while (message := await self._read_upstream()) is not None:
                if "id" in message:
                    await self._route_reply(message)
                elif "ev" in message:
                    await self._route_event(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("upstream reader failed")
        finally:
            error = ConnectionError("control connection closed")
            for pending in list(self.pending.values()):
                if pending.future is not None and not pending.future.done():
                    pending.future.set_exception(error)
            self.pending.clear()
            self.stop_event.set()

    async def _route_reply(self, message: dict[str, Any]) -> None:
        sid = int(message.get("id", -1))
        pending = self.pending.pop(sid, None)
        if pending is None:
            LOG.info("discarding late/unknown reply sid=%s", sid)
            return
        if pending.owner is INTERNAL:
            assert pending.future is not None
            if not pending.future.done():
                pending.future.set_result(message)
            return
        client = pending.owner
        assert isinstance(client, ProxyClient)
        client.pending_sids.discard(sid)
        if not client.connected:
            LOG.info("discarding reply sid=%s for disconnected client", sid)
            return
        outgoing = dict(message)
        outgoing["id"] = pending.client_id
        await client.send(outgoing)

    async def _route_event(self, message: dict[str, Any]) -> None:
        if message.get("ev") == "pmove":
            if self.push_active and self._consume_pmove(message):
                self._pmove_seen.set()
            return
        if message.get("ev") in TERMINAL_EVENTS:
            bot = message.get("bot")
            owner = self.goto_owner.pop(int(bot), None) if bot is not None else None
            owner = owner or self.last_goto_owner
            if owner is not None and owner.connected:
                await owner.send(message)
            return
        await asyncio.gather(
            *(client.send(message) for client in tuple(self.proxy_clients) if client.connected),
            return_exceptions=True,
        )

    def _consume_pmove(self, message: dict[str, Any]) -> bool:
        """Consume one authoritative server frame and build the latest viewer frame."""
        try:
            server_time = float(message["t"])
            players = message["players"]
            if not isinstance(players, list):
                raise TypeError("players is not a list")
        except (KeyError, TypeError, ValueError):
            LOG.warning("discarding malformed pmove event: %r", message)
            return False

        actors_out = []
        record_stream = (
            self.record_path.open("a", encoding="utf-8")
            if self.record_path is not None
            else None
        )
        try:
            for raw_player in players:
                try:
                    ent = int(raw_player["ent"])
                    position = [float(value) for value in raw_player["origin"]]
                    velocity = [float(value) for value in raw_player["vel"]]
                    on_ground = raw_player["on_ground"]
                    ground_ent = int(raw_player.get("ground_ent", -1))
                    if len(position) != 3 or len(velocity) != 3 or not isinstance(on_ground, bool):
                        raise ValueError("bad pmove player shape")
                except (KeyError, TypeError, ValueError):
                    LOG.warning("discarding malformed pmove player: %r", raw_player)
                    continue

                if record_stream is not None:
                    record_stream.write(json.dumps({
                        "t": server_time,
                        "ent": ent,
                        "origin": position,
                        "vel": velocity,
                        "on_ground": on_ground,
                        "ground_ent": ground_ent,
                    }, separators=(",", ":")) + "\n")

                state = self.attribution.setdefault(ent, Attribution())
                aux = self._actor_aux.setdefault(
                    ent,
                    {"last_ground_pos": None, "airborne_from": None, "airborne_point": None},
                )
                resolved, verdict = (
                    self.graph_matcher.classify(position) if on_ground else (None, None)
                )
                if on_ground:
                    if resolved is None:
                        state.note_missing_ground(position)
                    else:
                        if verdict == GraphMatcher.OFF_GRID:
                            state.note_off_grid(position)
                        if (
                            aux["airborne_from"] is not None
                            and aux["airborne_from"] != resolved
                            and not (
                                self.graph.links_by_cells.get((aux["airborne_from"], resolved), ())
                                or self.graph.fuzzy_links(aux["airborne_from"], resolved)
                            )
                        ):
                            state.note_missing_traversal(aux["airborne_point"], position)
                        state.observe(resolved, server_time, self.graph)
                    aux["airborne_from"] = None
                    aux["airborne_point"] = None
                    aux["last_ground_pos"] = list(position)
                elif aux["airborne_from"] is None and state.last_cell is not None:
                    aux["airborne_from"] = state.last_cell
                    aux["airborne_point"] = aux["last_ground_pos"] or list(position)

                actors_out.append({
                    "ent": ent,
                    "pos": position,
                    "speed": math.hypot(velocity[0], velocity[1]),
                    "cell_id": resolved if resolved is not None else state.last_cell,
                    "used": {
                        "cells": sorted(state.used_cells),
                        "links": sorted(state.used_links),
                    },
                    "missing": state.missing_payload(),
                    "human": True,
                    "name": self._player_names.get(ent),
                })
        finally:
            if record_stream is not None:
                record_stream.close()
        # An empty players array is the build's telemetry heartbeat (bridge
        # started before the human connected). Build the frame anyway so the
        # viewer/probes see the same steady empty frames poll mode always sent.
        self.last_frame = self._make_frame(actors_out)
        return True

    async def _allocate(self, pending: Pending, command: str) -> int:
        assert self._upstream_writer is not None
        async with self._send_lock:
            sid = self._next_sid
            self._next_sid += 1
            self.pending[sid] = pending
            if isinstance(pending.owner, ProxyClient):
                pending.owner.pending_sids.add(sid)
            if self._msgpack:
                self._upstream_writer.write(
                    mpwire.pack_frame({"id": sid, "cmd": _ft._parse_verb(command)}))
            else:
                self._upstream_writer.write(f"{sid} {command}\n".encode("ascii"))
            await self._upstream_writer.drain()
            return sid

    async def request(self, command: str, timeout: float = 15.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        pending = Pending(INTERNAL, None, future)
        sid = await self._allocate(pending, command)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(sid, None)

    async def _forward_client(self, client: ProxyClient, cid: int, command: str) -> None:
        await self._allocate(Pending(client, cid), command)

    def _begin_goto(self, client: ProxyClient, command: str) -> None:
        parts = command.split()
        if len(parts) < 2 or parts[0] != "goto":
            return
        try:
            bot = int(parts[1])
        except ValueError:
            return
        self.goto_owner[bot] = client
        self.last_goto_owner = client
        self.attempt_id += 1
        self.attribution.setdefault(bot, Attribution()).reset()

    async def _proxy_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = ProxyClient(reader, writer)
        self.proxy_clients.add(client)
        try:
            while line := await reader.readline():
                decoded = line.decode("utf-8", "replace").strip()
                cid_text, separator, command = decoded.partition(" ")
                try:
                    cid = int(cid_text)
                except ValueError:
                    await client.send({"id": 0, "ok": False, "error": "bad request id"})
                    continue
                if not separator or not command:
                    await client.send({"id": cid, "ok": False, "error": "missing command"})
                    continue
                if command == "__ping__":
                    await client.send({"id": cid, "ok": True, "nonce": self.nonce})
                    continue
                if command == "__latency__":
                    await client.send({"id": cid, "ok": True, "data": self.latency_summary()})
                    continue
                if command == "__missing__":
                    await client.send({"id": cid, "ok": True, "data": {
                        str(ent): state.missing_payload()
                        for ent, state in self.attribution.items()}})
                    continue
                self._begin_goto(client, command)
                await self._forward_client(client, cid, command)
        finally:
            await self._disconnect_client(client)

    async def _disconnect_client(self, client: ProxyClient) -> None:
        if not client.connected:
            return
        client.connected = False
        self.proxy_clients.discard(client)
        for sid in tuple(client.pending_sids):
            pending = self.pending.get(sid)
            if pending is not None and pending.owner is client:
                self.pending.pop(sid, None)
        client.pending_sids.clear()
        self.goto_owner = {bot: owner for bot, owner in self.goto_owner.items() if owner is not client}
        if self.last_goto_owner is client:
            self.last_goto_owner = None
        client.writer.close()
        try:
            await asyncio.wait_for(client.writer.wait_closed(), 1.0)
        except (OSError, TimeoutError):
            pass

    async def _bind_server(self, handler: Any, requested: int) -> tuple[asyncio.AbstractServer, int]:
        errors: list[str] = []
        for port in range(requested, requested + 10):
            try:
                server = await asyncio.start_server(handler, "127.0.0.1", port)
                return server, port
            except OSError as exc:
                errors.append(f"{port}: {exc}")
        raise OSError("no free loopback port in range: " + "; ".join(errors))

    async def _spot_check(self) -> None:
        if not self.graph.cells:
            raise RuntimeError("graph stale vs live server — kör graph_dump om (empty graph)")
        count = min(20, len(self.graph.cells))
        indices = secrets.SystemRandom().sample(range(len(self.graph.cells)), count)
        for index in indices:
            position = self.graph.cells[index]
            reply = await self.request("cell " + " ".join(f"{float(value):g}" for value in position))
            actual = (reply.get("data") or {}).get("cell")
            expected = self.graph.cell_ids[index]
            if reply.get("ok") is not True or actual != expected:
                raise RuntimeError(
                    "graph stale vs live server — kör graph_dump om "
                    f"(sample index {index}: expected {expected}, got {actual})"
                )

    async def readiness(self) -> dict[str, Any]:
        status = await self.request("status", timeout=30.0)
        data = status.get("data") or {}
        if status.get("ok") is not True or data.get("navmesh") != "ready":
            raise RuntimeError(f"live server not ready: {status}")
        # Counts legitimately drift from the file: auto-replanted/planted links
        # grow the live link count, and a dump only reaches cells connected to
        # its crawl seed. Identity comes from the cell-id spot check below;
        # live having FEWER elements than the file is the only count red flag.
        if (data.get("cells") or 0) < len(self.graph.cells) or (data.get("links") or 0) < len(self.graph.links):
            raise RuntimeError(
                "graph stale vs live server — kör graph_dump om "
                f"(live smaller than file: live={data.get('cells')}/{data.get('links')} "
                f"file={len(self.graph.cells)}/{len(self.graph.links)})"
            )
        await self._spot_check()
        return data

    def _remember_player_names(self, status: dict[str, Any]) -> None:
        self._player_names = {
            int(player["ent"]): str(player.get("name") or "")
            for player in (status.get("players") or [])
            if "ent" in player
        }

    async def _enable_push(self) -> None:
        try:
            reply = await self.request("set rtx_telemetry 1", timeout=3.0)
            if reply.get("ok") is not True:
                raise RuntimeError(str(reply))
        except (ConnectionError, RuntimeError, TimeoutError) as error:
            self.push_active = False
            LOG.warning("could not enable pmove push; falling back to poll mode: %s", error)
            return
        self.push_active = True
        self._push_watchdog_task = asyncio.create_task(
            self._push_watchdog(), name="pmove-push-watchdog"
        )

    async def _disable_push(self) -> None:
        self.push_active = False
        try:
            reply = await self.request("set rtx_telemetry 0", timeout=2.0)
            if reply.get("ok") is not True:
                LOG.warning("rtx_telemetry disable failed: %s", reply)
        except (ConnectionError, TimeoutError):
            LOG.warning("could not disable rtx_telemetry: control connection unavailable")

    async def _push_watchdog(self) -> None:
        try:
            await asyncio.wait_for(self._pmove_seen.wait(), PUSH_FALLBACK_S)
        except TimeoutError:
            if not self.push_active:
                return
            LOG.warning(
                "push mode requested but no pmove events arrived within %.0f s; "
                "falling back to poll mode (older .so build?)",
                PUSH_FALLBACK_S,
            )
            await self._disable_push()
        except asyncio.CancelledError:
            pass

    def _write_state(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "pid": os.getpid(),
            "started_at": self.started_at,
            "nonce": self.nonce,
            "proxy": self.proxy_port,
            "ws": self.ws_port,
        }
        temp = STATE_FILE.with_name(f".{STATE_FILE.name}.{self.nonce}.tmp")
        temp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        temp.replace(STATE_FILE)

    def _remove_own_state(self) -> None:
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if state.get("nonce") == self.nonce:
                STATE_FILE.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass

    async def start(self) -> dict[str, Any]:
        await self.connect_upstream()
        self._proxy_server, self.proxy_port = await self._bind_server(
            self._proxy_client, self.requested_proxy_port
        )
        self._ws_server, self.ws_port = await self._bind_server(
            self._ws_client, self.requested_ws_port
        )
        status = await self.readiness()
        self._remember_player_names(status)
        if self.push_requested:
            await self._enable_push()
        self._write_state()
        self._telemetry_task = asyncio.create_task(self._telemetry_loop(), name="telemetry")
        LOG.info(
            "ready control=%s proxy=%s ws=%s graph=%s sha256=%s",
            self.control_port,
            self.proxy_port,
            self.ws_port,
            self.graph.name,
            self.graph.sha256,
        )
        return status

    async def _resolve_cell(self, position: list[float]) -> int | None:
        command = "cell " + " ".join(f"{float(value):g}" for value in position)
        try:
            reply = await self.request(command, timeout=2.0)
        except (TimeoutError, ConnectionError):
            return None
        if reply.get("ok") is not True:
            return None
        value = (reply.get("data") or {}).get("cell")
        return int(value) if isinstance(value, int) else None

    async def collect_frame(self) -> tuple[dict[str, Any], float, float]:
        tick_started = time.monotonic()
        status_sent = time.monotonic()
        status = await self.request("status", timeout=3.0)
        status_reply = time.monotonic()
        if status.get("ok") is not True:
            raise RuntimeError(f"status failed: {status}")
        bots_out = []
        data = status.get("data") or {}
        # Human clients ride the same attribution pipeline as bots so a live
        # player lights up used cells/links and the red missing layer.
        actors = list(data.get("bots") or [])
        actors += [dict(p, human=True) for p in (data.get("players") or [])]
        for bot in actors:
            if not bot.get("alive"):
                continue
            ent = int(bot["ent"])
            position = [float(value) for value in bot["origin"]]
            state = self.attribution.setdefault(ent, Attribution())
            aux = self._actor_aux.setdefault(
                ent, {"last_ground_pos": None, "airborne_from": None,
                      "airborne_point": None, "unresolved_streak": 0,
                      "prev_z": None})
            resolved_raw = await self._resolve_cell(position)
            if self.record_path is not None:
                with self.record_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "t": round(time.monotonic() - self._mono_start, 3),
                        "ent": ent, "pos": position, "raw_cell": resolved_raw,
                        "last_cell": state.last_cell,
                    }, separators=(",", ":")) + "\n")
            # Airborne guard: a jump arc over a pit resolves to the cells UNDER
            # the arc, which would attribute a phantom walk chain instead of the
            # jump link. When the bot floats far above the resolved cell's
            # floor, hold the last ground cell so landing yields the direct
            # takeoff->landing transition. 40u > any step, < any real drop-off.
            resolved = resolved_raw
            airborne = False
            if resolved is not None:
                floor_z = self.graph.cell_z_by_id.get(resolved)
                if floor_z is not None and position[2] - floor_z > 40.0:
                    resolved = None
                    airborne = True
            if resolved is not None:
                if (aux["airborne_from"] is not None and aux["airborne_from"] != resolved
                        and not (self.graph.links_by_cells.get((aux["airborne_from"], resolved), ())
                                 or self.graph.fuzzy_links(aux["airborne_from"], resolved))):
                    state.note_missing_traversal(aux["airborne_point"], position)
                aux["airborne_from"] = None
                aux["unresolved_streak"] = 0
                aux["last_ground_pos"] = list(position)
                state.observe(resolved, time.monotonic(), self.graph)
            elif airborne:
                aux["unresolved_streak"] = 0
                if aux["airborne_from"] is None and state.last_cell is not None:
                    aux["airborne_from"] = state.last_cell
                    aux["airborne_point"] = aux["last_ground_pos"] or list(position)
            else:
                # No cell at all here. Sustained -> the actor is standing on
                # ground the mesh does not cover: a red missing cell. Require
                # vertical stability so a ballistic arc over an unmeshed area
                # cannot accumulate the same streak in mid-air.
                aux["unresolved_streak"] = _next_unresolved_streak(
                    aux["unresolved_streak"], position[2], aux["prev_z"]
                )
                if aux["unresolved_streak"] >= 3:
                    state.note_missing_ground(position)
            aux["prev_z"] = position[2]
            cell_id = resolved if resolved is not None else state.last_cell
            bots_out.append(
                {
                    "ent": ent,
                    "pos": position,
                    "speed": float(bot.get("speed") or 0.0),
                    "cell_id": cell_id,
                    "used": {
                        "cells": sorted(state.used_cells),
                        "links": sorted(state.used_links),
                    },
                    "missing": state.missing_payload(),
                    **({"human": True, "name": bot.get("name")} if bot.get("human") else {}),
                }
            )
        frame = self._make_frame(bots_out)
        status_rtt_ms = (status_reply - status_sent) * 1000.0
        bridge_tick_ms = (time.monotonic() - status_reply) * 1000.0
        _ = tick_started
        return frame, status_rtt_ms, bridge_tick_ms

    def _make_frame(self, actors: list[dict[str, Any]]) -> dict[str, Any]:
        self.seq += 1
        frame = {
            "schema": "qw-live-frame/1",
            "seq": self.seq,
            "t_mono": time.monotonic() - self._mono_start,
            "graph": {
                "name": self.graph.name,
                "cells": len(self.graph.cells),
                "links": len(self.graph.links),
                "sha256": self.graph.sha256,
            },
            "attempt_id": self.attempt_id,
            "bots": actors,
        }
        self.last_frame = frame
        return frame

    async def _telemetry_loop(self) -> None:
        interval = 1.0 / PUSH_BROADCAST_HZ
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                try:
                    if self.push_active:
                        if self.last_frame is not None and self.seq != self._last_broadcast_seq:
                            ws_started = time.monotonic()
                            await self._broadcast_ws(self.last_frame)
                            ws_ms = (time.monotonic() - ws_started) * 1000.0
                            self.ws_send_ms.append(ws_ms)
                            del self.ws_send_ms[:-2000]
                            self._last_broadcast_seq = self.seq
                        await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))
                        continue
                    frame, status_ms, tick_ms = await self.collect_frame()
                    ws_started = time.monotonic()
                    await self._broadcast_ws(frame)
                    ws_ms = (time.monotonic() - ws_started) * 1000.0
                    total = status_ms + tick_ms + ws_ms
                    for series, value in (
                        (self.status_rtt_ms, status_ms),
                        (self.tick_ms, tick_ms),
                        (self.ws_send_ms, ws_ms),
                        (self.latencies_ms, total),
                    ):
                        series.append(value)
                        del series[:-2000]
                    LOG.info(
                        "latency seq=%d status_rtt_ms=%.3f tick_ms=%.3f ws_send_ms=%.3f total_ms=%.3f",
                        self.seq,
                        status_ms,
                        tick_ms,
                        ws_ms,
                        total,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOG.exception("telemetry tick failed")
                await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))
        except asyncio.CancelledError:
            pass

    def latency_summary(self) -> dict[str, Any]:
        def percentile(values: list[float], fraction: float) -> float | None:
            if not values:
                return None
            ordered = sorted(values)
            index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
            return ordered[index]

        return {
            "samples": len(self.latencies_ms),
            "p50_ms": percentile(self.latencies_ms, 0.50),
            "p95_ms": percentile(self.latencies_ms, 0.95),
            "status_rtt_p50_ms": percentile(self.status_rtt_ms, 0.50),
            "status_rtt_p95_ms": percentile(self.status_rtt_ms, 0.95),
            "tick_p50_ms": percentile(self.tick_ms, 0.50),
            "tick_p95_ms": percentile(self.tick_ms, 0.95),
            "ws_send_p50_ms": percentile(self.ws_send_ms, 0.50),
            "ws_send_p95_ms": percentile(self.ws_send_ms, 0.95),
        }

    async def _ws_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2.0)
            headers: dict[str, str] = {}
            for line in request.decode("latin1").split("\r\n")[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            key = headers.get("sec-websocket-key")
            if not key:
                raise ValueError("missing Sec-WebSocket-Key")
            accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode()
            writer.write(
                ("HTTP/1.1 101 Switching Protocols\r\n"
                 "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                 f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode("ascii")
            )
            await writer.drain()
            self.ws_clients.add(writer)
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
            self.ws_clients.discard(writer)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1.0)
            except (OSError, TimeoutError):
                pass

    async def _broadcast_ws(self, frame: dict[str, Any]) -> None:
        encoded = _ws_frame(json.dumps(frame, separators=(",", ":")).encode("utf-8"))
        stale: list[asyncio.StreamWriter] = []
        for writer in tuple(self.ws_clients):
            try:
                writer.write(encoded)
                await writer.drain()
            except (ConnectionError, OSError):
                stale.append(writer)
        for writer in stale:
            self.ws_clients.discard(writer)
            writer.close()

    async def close(self) -> None:
        self._remove_own_state()
        self.stop_event.set()
        if self._telemetry_task is not None:
            self._telemetry_task.cancel()
            await asyncio.gather(self._telemetry_task, return_exceptions=True)
        if self._push_watchdog_task is not None:
            self._push_watchdog_task.cancel()
            await asyncio.gather(self._push_watchdog_task, return_exceptions=True)
        if (
            self.push_requested
            and self._upstream_writer is not None
            and (self._reader_task is None or not self._reader_task.done())
        ):
            await self._disable_push()
        for server in (self._proxy_server, self._ws_server):
            if server is not None:
                server.close()
                await server.wait_closed()
        for client in tuple(self.proxy_clients):
            await self._disconnect_client(client)
        for writer in tuple(self.ws_clients):
            writer.close()
        if self._upstream_writer is not None:
            self._upstream_writer.close()
            try:
                await asyncio.wait_for(self._upstream_writer.wait_closed(), 1.0)
            except (OSError, TimeoutError):
                pass
        if self._reader_task is not None:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)


def _ws_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    head = bytes([0x80 | opcode])
    length = len(payload)
    if length < 126:
        return head + bytes([length]) + payload
    if length < 65536:
        return head + bytes([126]) + struct.pack("!H", length) + payload
    return head + bytes([127]) + struct.pack("!Q", length) + payload


async def _read_ws_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first, second = await reader.readexactly(2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    mask = await reader.readexactly(4) if masked else b""
    payload = await reader.readexactly(length)
    if masked:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return opcode, payload


async def _run(args: argparse.Namespace) -> int:
    graph = GraphContract.load(args.graph)
    bridge = LiveBridge(graph, args.control, args.ws_port, args.proxy_port,
                        record_path=args.record, push=args.push)
    if args.once:
        try:
            await bridge.connect_upstream()
            status = await bridge.readiness()
            bridge._remember_player_names(status)
            if args.push:
                await bridge._enable_push()
                try:
                    await asyncio.wait_for(bridge._pmove_seen.wait(), PUSH_FALLBACK_S + 0.1)
                except TimeoutError:
                    pass
            if bridge.push_active and bridge.last_frame is not None:
                frame = bridge.last_frame
            else:
                frame, _, _ = await bridge.collect_frame()
            print(json.dumps(frame, separators=(",", ":")), flush=True)
            return 0
        finally:
            await bridge.close()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bridge.stop_event.set)
        except NotImplementedError:
            pass
    try:
        await bridge.start()
        await bridge.stop_event.wait()
        return 0
    finally:
        await bridge.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=int, default=27980)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--ws-port", type=int, default=8093)
    parser.add_argument("--proxy-port", type=int, default=27981)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--push", action="store_true",
                        help="consume authoritative per-frame pmove events (falls back after 5 s)")
    parser.add_argument("--record", type=Path, default=None,
                        help="append poll debug rows, or flattened raw pmove rows with --push")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
