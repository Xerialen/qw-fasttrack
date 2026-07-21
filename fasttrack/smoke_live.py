"""v1 live-viewer E2E smoke (dm3 fixture; library code remains map-agnostic).

Run inside WSL with low priority:
  nice -n 19 python3 -u fasttrack/smoke_live.py
"""
from __future__ import annotations

import base64
import json
import os
import signal
import socket
import struct
import threading
import time

import core


PATCH = {
    "schema": "qw-nav-patch/1",
    "name": "sng-stairs-proven",
    "adds": [{
        "kind": "SpeedJump",
        "from": [-128, 832, 120],
        "takeoff": [-140, 780, 120],
        "to": [-303, 526, 120],
        "v_req": 460,
        "cvars": {
            "rtx_jump_curl_gain": 12,
            "rtx_jump_curl_entry_x": -235,
            "rtx_jump_curl_entry_y": 675,
            "rtx_jump_curl_switch_dist": 160,
            "rtx_jump_curl_landing_x": -303,
            "rtx_jump_curl_landing_y": 526,
        },
    }],
}
START = [-128, 832, 121]
TARGET = [-303, 526, 121]


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("WebSocket closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame(sock: socket.socket) -> dict:
    first, second = _recv_exact(sock, 2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    if second & 0x80:
        mask = _recv_exact(sock, 4)
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(_recv_exact(sock, length)))
    else:
        payload = _recv_exact(sock, length)
    if opcode == 0x8:
        raise ConnectionError("WebSocket close frame")
    if opcode != 0x1:
        return _recv_frame(sock)
    return json.loads(payload)


def _ws_connect(port: int) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(4096)
    if not response.startswith(b"HTTP/1.1 101"):
        raise RuntimeError(f"WebSocket handshake failed: {response[:200]!r}")
    sock.settimeout(1.0)
    return sock


def _collect_frames(port: int, stop: threading.Event, frames: list[dict], errors: list[str]) -> None:
    try:
        sock = _ws_connect(port)
        try:
            while not stop.is_set():
                try:
                    frames.append(_recv_frame(sock))
                except socket.timeout:
                    continue
        finally:
            sock.close()
    except Exception as exc:  # surfaced in the main smoke thread
        errors.append(str(exc))


def _latency() -> dict:
    control = core.Control(timeout=2.0)
    try:
        return control.request("__latency__", timeout=5.0)["data"]
    finally:
        control.close()


def main() -> int:
    frames: list[dict] = []
    ws_errors: list[str] = []
    stop = threading.Event()
    thread = None
    try:
        print("== server_up(dm3) ==", flush=True)
        up = core.server_up("dm3")
        print(json.dumps(up, indent=1), flush=True)

        # Plant ONCE: trust the auto-replant when it planted the same patch
        # (twin links share endpoints — the router oscillates between them
        # under penalties, and attribution reports file-side ids anyway).
        planted_ids = set()
        replant = up.get("replant") or {}
        if replant.get("adds_ok"):
            print("== plant via auto-replant (no second apply) ==", flush=True)
            planted_ids = {d["link"] for d in replant["detail"] if isinstance(d.get("link"), int)}
        else:
            print("== patch_apply(proven SNG jump) ==", flush=True)
            patch = core.patch_apply(PATCH)
            print(json.dumps(patch, indent=1), flush=True)
            planted_ids = {d["link"] for d in patch["detail"] if isinstance(d.get("link"), int)}
        if not planted_ids:
            raise AssertionError("no planted link id")

        # Attribution emits GRAPH-FILE link ids: resolve the jump's file-side
        # id(s) by endpoint proximity so the assertion is id-space-correct.
        graph = json.loads(
            (core.VIEWER_OVERLAYS / "fasttrack-graph.json").read_text(encoding="utf-8"))
        takeoff, landing = PATCH["adds"][0]["takeoff"], PATCH["adds"][0]["to"]

        def _near(cell, point, tol=64.0):
            return (abs(cell[0] - point[0]) <= tol and abs(cell[1] - point[1]) <= tol
                    and abs(cell[2] - point[2]) <= 48.0)

        file_ids = {
            graph["link_ids"][i]
            for i, (f, t, kind, _c) in enumerate(graph["links"])
            if kind.lower() == "speedjump"
            and _near(graph["cells"][f], takeoff) and _near(graph["cells"][t], landing)
        }
        expected = planted_ids | file_ids
        print(f"expected jump link ids: planted={sorted(planted_ids)} file={sorted(file_ids)}",
              flush=True)

        print("== live_start ==", flush=True)
        live = core.live_start("dm3", "fasttrack")
        print(json.dumps(live, indent=1), flush=True)

        print("== graph_dump interlock ==", flush=True)
        try:
            core.graph_dump("dm3", START)
        except RuntimeError as exc:
            if "stoppa live-bryggan först" not in str(exc):
                raise
            print(f"graph_dump blocked: {exc}", flush=True)
        else:
            raise AssertionError("graph_dump unexpectedly ran while live")

        thread = threading.Thread(
            target=_collect_frames, args=(live["ws"], stop, frames, ws_errors), daemon=True
        )
        thread.start()
        time.sleep(0.5)

        print("== trial x3 through proxy ==", flush=True)
        trial = core.trial(START, TARGET, attempts=3)
        print(json.dumps(trial, indent=1), flush=True)
        if trial["ok"] < 1:
            raise AssertionError(f"no successful proxied trial: {trial}")

        # App-property assertions (NOT bot-route judgments — which links the
        # bot uses is the router's choice; the recording of 2026-07-22 showed
        # it legitimately preferring the northern walk route from standstill):
        # frames must stream, used elements must accumulate, and attempts
        # must reset the accumulator (attempt_id advances per goto).
        time.sleep(1.0)
        if not frames:
            raise AssertionError(f"no WS frames received; errors={ws_errors}")
        with_links = [f for f in frames
                      if any(b["used"]["links"] for b in f.get("bots", []))]
        if not with_links:
            raise AssertionError(f"used.links never populated in {len(frames)} frames")
        attempts_seen = {f["attempt_id"] for f in frames}
        if len(attempts_seen) < 2:
            raise AssertionError(f"attempt_id never advanced: {sorted(attempts_seen)}")
        jump_frames = [f for f in frames
                       if any(expected & set(b["used"]["links"]) for b in f.get("bots", []))]
        print(f"WS: {len(frames)} frames, {len(with_links)} with links, "
              f"attempts {sorted(attempts_seen)}, jump-link frames {len(jump_frames)} "
              f"(informational — route choice is the bot's)", flush=True)

        recorded = []
        for frame in frames:
            if not frame.get("bots"):
                continue
            bot = frame["bots"][0]
            sample = {"t": round(frame["t_mono"], 3), "pos": bot["pos"], "cell": bot["cell_id"]}
            if not recorded or sample["cell"] != recorded[-1]["cell"]:
                recorded.append(sample)
        print("LIVE-SMOKE-FIXTURE: " + json.dumps(recorded, separators=(",", ":")), flush=True)

        latency = _latency()
        print("LATENCY: " + json.dumps(latency, sort_keys=True), flush=True)
        if latency["samples"] < 1 or latency["p95_ms"] is None or latency["p95_ms"] >= 200.0:
            raise AssertionError(f"latency criterion failed: {latency}")

        print("== hard-kill stale-state fallback ==", flush=True)
        state = json.loads(core.LIVE_STATE.read_text(encoding="utf-8"))
        os.kill(int(state["pid"]), signal.SIGKILL)
        time.sleep(0.5)
        direct = core.Control(timeout=5.0)
        try:
            fallback_status = direct.request("status", timeout=10.0)["data"]
        finally:
            direct.close()
        if core.LIVE_STATE.exists():
            raise AssertionError("stale state survived Control fallback")
        print(
            "fallback direct: " + json.dumps({
                "navmesh": fallback_status.get("navmesh"),
                "cells": fallback_status.get("cells"),
                "links": fallback_status.get("links"),
            }),
            flush=True,
        )

        print("== v0 direct regression: server_status + trial x1 ==", flush=True)
        print(json.dumps(core.server_status(), indent=1), flush=True)
        direct_trial = core.trial(START, TARGET, attempts=1)
        print(json.dumps(direct_trial, indent=1), flush=True)
        if direct_trial["ok"] < 1:
            raise AssertionError(f"direct v0 trial failed: {direct_trial}")

        print("LIVE-SMOKE: OK", flush=True)
        return 0
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=3.0)
        print("== finally: live_stop + server_down ==", flush=True)
        try:
            print(json.dumps(core.live_stop(), indent=1), flush=True)
        finally:
            print(json.dumps(core.server_down(), indent=1), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
