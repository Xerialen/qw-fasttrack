"""qw-fasttrack core: owned experiment server + control client + session state.

Map-agnostic prototype. Every tool takes the map/coords as parameters; the
only baked-in facts are the port block, the runtime paths, and the pinned
forbidden cvars (permanent lab ban). Runs inside WSL (systemd --user).
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

# Own port block — never the deck's (8765/8767) or the orchestration's
# (27504/06/08/16/21) ports. Control = game + 450 by lab convention.
GAME_PORT, CONTROL_PORT, QTV_PORT = 27530, 27980, 29530
UNIT = "fasttrack-server"
LIVE_UNIT = "fasttrack-live-bridge"
VIEWER_UNIT = "fasttrack-viewer"
REPLAY_UNIT = "fasttrack-replay"
REPLAY_WS_PORT = 8095

GAP_WORK_TIMEOUT_S = 3600.0
# The total reserves cleanup + evidence finalization after the work deadline;
# a work timeout therefore cannot consume the time needed for restoration.
GAP_TOTAL_TIMEOUT_S = 5430.0
GAP_PHASE_TIMEOUTS_S = {
    "baseline_boot": 1800.0,
    "graph_dump": 180.0,
    "demo_ingest": 300.0,
    "baseline_trial": 600.0,
    "patch_apply": 60.0,
    "patched_trial": 600.0,
    "cleanup_restart": 1800.0,
    "evidence_write": 30.0,
}

RUNTIME = Path.home() / ".local" / "share" / "qw-fasttrack" / "runtime"
STATE_DIR = Path.home() / ".local" / "share" / "qw-fasttrack"
ACTIVE_PATCH = STATE_DIR / "active-patch.json"
ACTIVE_GRAPH = STATE_DIR / "active-graph.json"
PATCHES_DIR = STATE_DIR / "patches"
EVIDENCE_DIR = STATE_DIR / "evidence"
LIVE_STATE = STATE_DIR / "live-bridge.json"
VIEWER_OWNERSHIP = STATE_DIR / "live-viewer-owned.json"
ROUTE_LAB = Path("/mnt/c/Users/benya/projects/quakeworld/route-lab")
PROMOTE_DIR = ROUTE_LAB / "artifacts" / "nav-patches"
SKELETON = Path.home() / ".local" / "share" / "route-lab" / "nav-ab"
DEFAULT_LIB = Path.home() / ".local" / "share" / "route-lab" / "rtx-main" / "qw" / "qwprogs.so"
DUMP_LIVE_GRAPH = Path("/mnt/c/Users/benya/projects/quakeworld/route-lab/ops/dump_live_graph.py")
# Canonical overlay store: this is what the 18089 sidecar and trunk proxy serve.
# VIEWER_WORKTREE remains the isolated viewer source/build directory only.
OVERLAYS_DIR = Path("/mnt/c/Users/benya/projects/quakeworld/route-lab/qw-nav-viewer/overlays")
VIEWER_WORKTREE = Path("/mnt/c/Users/benya/projects/quakeworld/route-lab-viewer-live/qw-nav-viewer")
FASTTRACK_DIR = Path(__file__).resolve().parent
LIVE_BRIDGE = FASTTRACK_DIR / "live_bridge.py"

# Forbidden cvars are pinned 0 (permanent lab ban) and bhop/curl stay on so
# speed-jump links are built. Map is a parameter — nothing map-specific here.
CFG = """// qw-fasttrack experiment server - generated, do not edit
hostname "RTXFAST"
serverinfo matchtag "fasttrack-proto"
sv_progtype 1
deathmatch 1
maxclients 8
maxspectators 4
set rtx_mode dm
set rtx_match ""
set rtx_grapple 0
set rtx_doublejump 0
set rtx_walljump 0
set rtx_elevator_jump 1
set rtx_shootable_grenades 0
set rtx_bot_bhop 1
set rtx_bot_curljump 1
set rtx_bot_rocketjump 0
set rtx_bot_ledgecap 0
set rtx_bot_count {bots}
set rtx_bot_alone 1
set rtx_bot_pacifist 1
set rtx_bot_skill 7
qtv_maxstreams 8
qtv_streamport {qtv}
set rtx_control_port {control}
set developer 1
map {map}
"""


class ControlError(RuntimeError):
    pass


def _read_live_state() -> dict | None:
    try:
        state = json.loads(LIVE_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    required = ("pid", "started_at", "nonce", "proxy", "ws")
    return state if all(key in state for key in required) else None


def _remove_live_state(expected_nonce: str | None = None) -> None:
    try:
        if expected_nonce is not None:
            current = json.loads(LIVE_STATE.read_text(encoding="utf-8"))
            if current.get("nonce") != expected_nonce:
                return
        LIVE_STATE.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError):
        pass


def _connect_live_proxy(state: dict, timeout: float) -> socket.socket:
    pid = int(state["pid"])
    os.kill(pid, 0)
    sock = socket.create_connection(("127.0.0.1", int(state["proxy"])), timeout=timeout)
    try:
        sock.settimeout(timeout)
        sock.sendall(b"0 __ping__\n")
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("live proxy closed during ping")
            buf += chunk
        reply = json.loads(buf.split(b"\n", 1)[0])
        if reply.get("ok") is not True or reply.get("nonce") != state["nonce"]:
            raise ValueError("live proxy nonce mismatch")
        return sock
    except Exception:
        sock.close()
        raise


class Control:
    """Newline-JSON control client (single connection, request/reply + events)."""

    def __init__(self, host: str = "127.0.0.1", port: int = CONTROL_PORT, timeout: float = 30.0):
        self._socket = None
        if host == "127.0.0.1" and port == CONTROL_PORT:
            state = _read_live_state()
            if state is not None:
                try:
                    self._socket = _connect_live_proxy(state, min(timeout, 1.0))
                except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                    _remove_live_state(state.get("nonce"))
                    print(
                        f"warning: stale live bridge state removed; using direct control: {exc}",
                        file=sys.stderr,
                    )
        if self._socket is None:
            self._socket = socket.create_connection((host, port), timeout=timeout)
        self._next_id = 1
        self._buf = b""
        self.events: list[dict] = []

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def _read(self, timeout: float):
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._socket.settimeout(max(remaining, 0.05))
            try:
                chunk = self._socket.recv(65536)
            except (TimeoutError, socket.timeout):
                return None
            if not chunk:
                raise ControlError("control connection closed")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8", "replace"))

    def request(self, verb_and_args: str, timeout: float = 15.0,
                before_send: Callable[[], None] | None = None) -> dict:
        rid = self._next_id
        self._next_id += 1
        if before_send is not None:
            before_send()
        self._socket.sendall(f"{rid} {verb_and_args}\n".encode("ascii"))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ControlError(f"request {verb_and_args!r} timed out")
            msg = self._read(remaining)
            if msg is None:
                continue
            if "ev" in msg:
                self.events.append(msg)
                continue
            if msg.get("id") == rid:
                if msg.get("ok") is not True:
                    raise ControlError(str(msg.get("error")))
                return msg

    def wait_event(self, names: tuple[str, ...], timeout: float):
        deadline = time.monotonic() + timeout
        while True:
            while self.events:
                ev = self.events.pop(0)
                if ev.get("ev") in names:
                    return ev
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            msg = self._read(remaining)
            if msg is not None and "ev" in msg:
                self.events.append(msg)


def _sh(*argv: str) -> str:
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, argv))}: {r.stderr.strip()[-400:]}")
    return r.stdout


def available_maps() -> list[str]:
    maps = SKELETON / "qw" / "maps"
    return sorted(p.stem for p in maps.glob("*.bsp")) if maps.exists() else []


def server_up(map: str, bots: int = 1, lib: str | None = None) -> dict:
    """Boot the experiment server on `map`, wait ready, auto-replant the
    active patch. Map-agnostic: any .bsp in the skeleton maps dir."""
    if map not in available_maps():
        raise ValueError(f"map {map!r} not in skeleton maps: {available_maps()}")
    (RUNTIME / "qw").mkdir(parents=True, exist_ok=True)
    for link, target in (("id1", SKELETON / "id1"), ("qw/maps", SKELETON / "qw" / "maps")):
        dst = RUNTIME / link
        if not dst.exists():
            dst.symlink_to(target)
    mvdsv = RUNTIME / "mvdsv"
    if not mvdsv.exists():
        shutil.copy2(SKELETON / "mvdsv", mvdsv)
        mvdsv.chmod(0o755)
    shutil.copy2(Path(lib) if lib else DEFAULT_LIB, RUNTIME / "qw" / "qwprogs.so")
    (RUNTIME / "qw" / "fasttrack.cfg").write_text(
        CFG.format(map=map, bots=bots, qtv=QTV_PORT, control=CONTROL_PORT), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "stop", UNIT], capture_output=True)
    _sh("systemd-run", "--user", "--collect", f"--unit={UNIT}",
        f"--working-directory={RUNTIME}", "--property=Nice=19", "--",
        str(RUNTIME / "mvdsv"), "-port", str(GAME_PORT), "+exec", "fasttrack.cfg")
    ready = wait_ready(expect_bots=bots > 0)
    replant = replant_active_patch() if ACTIVE_PATCH.exists() else None
    return {"game": GAME_PORT, "control": CONTROL_PORT, "qtv": QTV_PORT,
            "map": map, "ready": ready, "replant": replant}


def wait_ready(timeout_s: int = 1800, expect_bots: bool = True) -> dict:
    """Poll the control socket until navmesh=ready and, when the server was
    booted with bots, a live bot exists (expect_bots=False for a human-only
    movement-lab server)."""
    deadline = time.monotonic() + timeout_s
    last_err = None
    while time.monotonic() < deadline:
        try:
            ctl = Control(timeout=5.0)
            try:
                status = ctl.request("status")["data"]
                bots = [b for b in status.get("bots", []) if b.get("alive")]
                if status.get("navmesh") == "ready" and (bots or not expect_bots):
                    return {"navmesh": "ready", "bots": [b["ent"] for b in bots],
                            "cells": status.get("cells"), "links": status.get("links")}
            finally:
                ctl.close()
        except (OSError, ControlError) as exc:
            last_err = str(exc)
        time.sleep(5)
    raise RuntimeError(f"server never became ready ({last_err})")


def server_down() -> dict:
    subprocess.run(["systemctl", "--user", "stop", UNIT], capture_output=True)
    return {"stopped": True}


def server_status() -> dict:
    unit = subprocess.run(["systemctl", "--user", "is-active", UNIT],
                          capture_output=True, text=True).stdout.strip()
    out = {"unit": unit, "game": GAME_PORT, "control": CONTROL_PORT}
    if unit == "active":
        try:
            ctl = Control(timeout=5.0)
            try:
                out["status"] = ctl.request("status")["data"]
            finally:
                ctl.close()
        except (OSError, ControlError) as exc:
            out["control_error"] = str(exc)
    return out


def ctl(command: str, timeout: float = 15.0) -> dict:
    """Raw control-verb passthrough — the escape hatch (planlink, teleport,
    goto, set, cell, route, unlink, probe, ...)."""
    c = Control()
    try:
        return c.request(command, timeout=timeout)
    finally:
        c.close()


def patch_apply(patch: dict, store: bool = True) -> dict:
    """Apply a qw-nav-patch/1 object directly (adds: SpeedJump/JumpGap via
    planlink, RocketJump via planrjraw; removes: unlink by id). Stored as the
    active patch so server restarts auto-replant it."""
    if patch.get("schema") != "qw-nav-patch/1":
        raise ValueError(f"bad schema {patch.get('schema')!r}")
    c = Control()
    summary = {"adds_ok": 0, "adds_err": 0, "removes_ok": 0, "removes_err": 0, "detail": []}
    try:
        for add in patch.get("adds") or []:
            kind = add.get("kind")
            try:
                if kind == "Cell":
                    # Standable cell (edge strips the generator's clearance margin skips).
                    # Server-side plant_cell snaps z to the floor and wires Walk/Step links
                    # to reachable neighbours in both directions.
                    x, y, z = add["at"]
                    r = c.request(f"plancell {x:g} {y:g} {z:g}")
                    summary["adds_ok"] += 1
                    summary["detail"].append({"add": kind, "cell": (r.get("data") or {}).get("cell"),
                                              "links": (r.get("data") or {}).get("links_created")})
                    continue
                f, t = add["from"], add["to"]
                if kind in ("SpeedJump", "JumpGap"):
                    lip = add.get("takeoff") or f
                    v = float(add.get("v_req") or 320.0)
                    for name, val in (add.get("cvars") or {}).items():
                        c.request(f"set {name} {val}")
                    r = c.request("planlink " + " ".join(f"{x:g}" for x in (*f, *lip, *t, v)))
                    summary["adds_ok"] += 1
                    summary["detail"].append({"add": kind, "link": (r.get("data") or {}).get("link")})
                elif kind == "RocketJump":
                    r = c.request(
                        "planrjraw " + " ".join(f"{x:g}" for x in (*f, *t)) +
                        f" {float(add.get('pitch', 65.0)):g} {float(add.get('yaw', 0.0)):g} {float(add.get('delay', 0.3)):g}")
                    summary["adds_ok"] += 1
                    summary["detail"].append({"add": kind, "link": (r.get("data") or {}).get("link")})
                else:
                    raise ValueError(f"unsupported add kind {kind!r}")
            except (ControlError, KeyError, TypeError, ValueError) as exc:
                summary["adds_err"] += 1
                summary["detail"].append({"add": kind, "error": str(exc)})
        for rem in patch.get("removes") or []:
            li = rem.get("link")
            try:
                if not isinstance(li, int):
                    raise ValueError("remove needs integer link id (prototype)")
                c.request(f"unlink {li}")
                summary["removes_ok"] += 1
            except (ControlError, ValueError) as exc:
                if "already unlinked" in str(exc):
                    summary["removes_ok"] += 1
                else:
                    summary["removes_err"] += 1
                    summary["detail"].append({"remove": li, "error": str(exc)})
    finally:
        c.close()
    if store:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ACTIVE_PATCH.write_text(json.dumps(patch, indent=1), encoding="utf-8")
        if patch.get("name"):
            PATCHES_DIR.mkdir(parents=True, exist_ok=True)
            (PATCHES_DIR / f"{patch['name']}.json").write_text(
                json.dumps(patch, indent=1), encoding="utf-8")
    return summary


def _active_patch_name() -> str:
    try:
        return json.loads(ACTIVE_PATCH.read_text(encoding="utf-8")).get("name") or "nopatch"
    except (OSError, json.JSONDecodeError):
        return "nopatch"


def replant_active_patch() -> dict | None:
    try:
        patch = json.loads(ACTIVE_PATCH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return patch_apply(patch, store=False)


def patch_clear() -> dict:
    existed = ACTIVE_PATCH.exists()
    if existed:
        ACTIVE_PATCH.unlink()
    return {"cleared": existed}


TRIAL_POLL_HZ = 15.0
TRIAL_CVARS = (
    "rtx_bot_ledgecap", "rtx_walljump", "rtx_doublejump", "rtx_bot_bhop",
)


def _trial_bot(status: dict, bot: int) -> dict | None:
    return next((entry for entry in status.get("bots", [])
                 if int(entry.get("ent", -1)) == bot and entry.get("alive")), None)


def _trial_origin(status: dict, bot: int) -> list[float] | None:
    entry = _trial_bot(status, bot)
    origin = entry.get("origin") if entry is not None else None
    if not isinstance(origin, list) or len(origin) != 3:
        return None
    try:
        return [float(value) for value in origin]
    except (TypeError, ValueError):
        return None


def _inside_box(position: list[float], box: list[float]) -> bool:
    return (len(box) == 6
            and box[0] <= position[0] <= box[3]
            and box[1] <= position[1] <= box[4]
            and box[2] <= position[2] <= box[5])


def _trial_provenance(control: Control, status: dict, arrive_box: list[float] | None,
                      max_time_s: float, pass_time_s: float | None,
                      streak_target: int | None) -> dict:
    readback = {}
    for name in TRIAL_CVARS:
        data = control.request(f"get {name}")["data"]
        readback[name] = {
            "value": data.get("value"),
            "string": data.get("string"),
            "absent": data.get("string", "") == "",
        }
    matchtag = status.get("matchtag")
    if matchtag is None:
        data = control.request("get matchtag")["data"]
        matchtag = data.get("string")
    patch_sha = (hashlib.sha256(ACTIVE_PATCH.read_bytes()).hexdigest()
                 if ACTIVE_PATCH.exists() else None)
    graph_sha = status.get("graph_sha256") or status.get("graph_sha")
    if graph_sha is None:
        try:
            active_graph = json.loads(ACTIVE_GRAPH.read_text(encoding="utf-8"))
            # The active patch intentionally changes live link counts; its
            # separate SHA composes with this baseline graph fingerprint.
            if active_graph.get("map") == status.get("map"):
                graph_sha = active_graph["sha256"]
        except (OSError, KeyError, json.JSONDecodeError):
            graph_sha = None
    return {
        "arrive_box": arrive_box,
        "max_time_s": max_time_s,
        "pass_time_s": pass_time_s,
        "streak_target": streak_target,
        "poll_hz": TRIAL_POLL_HZ,
        "measurement_jitter_ms": round(1000.0 / TRIAL_POLL_HZ),
        "graph_sha": graph_sha,
        "patch_sha": patch_sha,
        "matchtag": matchtag,
        "cvar_readback": readback,
    }


def trial(start: list[float], target: list[float], attempts: int = 20,
          bot: int | None = None, settle_s: float = 0.6, timeout_s: float = 20.0,
          arrive_box: list[float] | None = None, *, pass_time_s: float | None = None,
          streak_target: int | None = None, max_time_s: float | None = None,
          attempts_cap: int | None = None) -> dict:
    """Measure teleport->goto attempts from received 15 Hz status positions.

    Supplying any v2-only argument enables streak mode (defaults: five passes,
    eight seconds, 30 attempts). Calls using only the old arguments retain the
    old fixed-attempt shape and optional-arrive-box requirement.
    """
    if len(start) != 3 or len(target) != 3:
        raise ValueError("start and target must each contain three coordinates")
    if arrive_box is not None and len(arrive_box) != 6:
        raise ValueError("arrive_box must contain six coordinates")
    v2 = any(value is not None for value in
             (pass_time_s, streak_target, max_time_s, attempts_cap))
    if v2 and arrive_box is None:
        raise ValueError("Trial v2 requires arrive_box; terminal events are evidence only")
    effective_target = (5 if streak_target is None else int(streak_target)) if v2 else None
    effective_max = 8.0 if v2 and max_time_s is None else float(
        timeout_s if max_time_s is None else max_time_s)
    cap = (30 if attempts_cap is None else int(attempts_cap)) if v2 else int(attempts)
    if effective_target is not None and effective_target < 1:
        raise ValueError("streak_target must be at least 1")
    if pass_time_s is not None and pass_time_s <= 0:
        raise ValueError("pass_time_s must be positive")
    if cap < 1 or effective_max <= 0:
        raise ValueError("attempts_cap and max_time_s must be positive")

    c = Control()
    try:
        status = c.request("status")["data"]
        if bot is None:
            alive = [b for b in status.get("bots", []) if b.get("alive")]
            if not alive:
                raise RuntimeError("no live bot")
            bot = int(alive[0]["ent"])
        provenance = _trial_provenance(
            c, status, arrive_box, effective_max, pass_time_s, effective_target)
        if v2 and provenance["graph_sha"] is None:
            raise RuntimeError(
                "Trial v2 requires graph provenance; run graph_dump for the active map first")
        rows = []
        streak = 0
        streak_max = 0
        for i in range(cap):
            c.request(f"stop {bot}")
            c.request(f"hold {bot}")
            c.request(f"teleport {bot} {start[0]:g} {start[1]:g} {start[2]:g}")
            time.sleep(settle_s)
            setup_status = c.request("status")["data"]
            setup_origin = _trial_origin(setup_status, bot)
            setup_error = (math.dist(start, setup_origin)
                           if setup_origin is not None else math.inf)
            c.events.clear()
            elapsed = None
            box_entry_pos = None
            terminal_events = []
            if setup_error > 24.0:
                outcome = "setup_failed"
            else:
                sent = [0.0]
                c.request(
                    f"goto {bot} {target[0]:g} {target[1]:g} {target[2]:g}",
                    before_send=lambda: sent.__setitem__(0, time.monotonic()),
                )
                deadline = sent[0] + effective_max
                outcome = "timeout"
                while time.monotonic() < deadline:
                    poll_started = time.monotonic()
                    try:
                        poll_status = c.request(
                            "status", timeout=max(
                                0.05, min(2.0, deadline - poll_started)))["data"]
                    except ControlError:
                        break
                    received = time.monotonic()
                    position = _trial_origin(poll_status, bot)
                    while c.events:
                        event = c.events.pop(0)
                        if event.get("ev") in ("arrived", "goto_stall"):
                            terminal_events.append({key: event.get(key)
                                                    for key in ("ev", "t", "dist")})
                    if arrive_box is not None and position is not None and _inside_box(position, arrive_box):
                        elapsed = received - sent[0]
                        box_entry_pos = position
                        outcome = ("passed" if pass_time_s is None or elapsed <= pass_time_s
                                   else "over_time")
                        break
                    if not v2 and arrive_box is None and terminal_events:
                        # Compatibility path: old callers did not require a box.
                        outcome = ("passed" if terminal_events[-1]["ev"] == "arrived" else "stall")
                        break
                    time.sleep(max(0.0, 1.0 / TRIAL_POLL_HZ - (time.monotonic() - poll_started)))
            attempt_passed = outcome == "passed"
            streak = streak + 1 if attempt_passed else 0
            streak_max = max(streak_max, streak)
            rows.append({
                "attempt": i + 1, "outcome": outcome, "elapsed": elapsed,
                "box_entry_pos": box_entry_pos, "setup_origin": setup_origin,
                "setup_error": None if not math.isfinite(setup_error) else setup_error,
                "terminal_events": terminal_events, "streak": streak,
            })
            if effective_target is not None and streak >= effective_target:
                break
        ok = sum(1 for row in rows if row["outcome"] == "passed")
        passed = streak >= effective_target if effective_target is not None else ok > 0
        result = {"bot": bot, "attempts": len(rows), "attempts_cap": cap, "ok": ok,
                  "rows": rows, "streak_max": streak_max, "passed": passed,
                  "provenance": provenance}
        # Evidence ledger keyed by the active patch: promote() refuses without it.
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        with (EVIDENCE_DIR / f"{_active_patch_name()}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "start": start, "target": target,
                                 "provenance": provenance, **result}) + "\n")
        return result
    finally:
        c.close()


def graph_dump(map: str, seed: list[float], out_name: str = "fasttrack") -> dict:
    """Dump the live graph via route-lab's dump_live_graph.py and install it
    as a viewer overlay (<out_name>-graph.json). Seed = any walkable point on
    the map (crawl start) — map-agnostic, caller supplies it."""
    if LIVE_STATE.exists():
        raise RuntimeError("stoppa live-bryggan först")
    OVERLAYS_DIR.mkdir(parents=True, exist_ok=True)
    out = OVERLAYS_DIR / f"{out_name}-graph.json"
    _sh("python3", str(DUMP_LIVE_GRAPH), "--port", str(CONTROL_PORT),
        "--map", map, "--seed", *(f"{x:g}" for x in seed), "--out", str(out))
    graph_bytes = out.read_bytes()
    graph = json.loads(graph_bytes)
    graph_sha = hashlib.sha256(graph_bytes).hexdigest()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_GRAPH.write_text(json.dumps({
        "map": map, "name": out_name, "path": str(out), "sha256": graph_sha,
        "cells": len(graph.get("cells") or []), "links": len(graph.get("links") or []),
    }, separators=(",", ":")), encoding="utf-8")
    return {"out": str(out), "graph_sha": graph_sha,
            "viewer": f"http://127.0.0.1:8088/?graph={out_name}"}


def _safe_overlay_name(name: str) -> bool:
    return bool(name) and all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in name)


def _http_ready(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def _unit_active(unit: str) -> bool:
    return subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", unit], capture_output=True
    ).returncode == 0


def _unit_status(unit: str) -> str:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", unit], capture_output=True, text=True)
    status = result.stdout.strip()
    if status:
        return status
    detail = result.stderr.strip() or "no status output"
    return f"error(rc={result.returncode}): {detail}"


def _wait_for_state(timeout_s: float = 45.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = _read_live_state()
        if state is not None:
            return state
        if not _unit_active(LIVE_UNIT):
            logs = subprocess.run(
                ["journalctl", "--user", "-u", LIVE_UNIT, "-n", "30", "--no-pager"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            raise RuntimeError(f"live bridge stopped before readiness: {logs[-2000:]}")
        time.sleep(0.2)
    raise TimeoutError("live bridge did not publish readiness state within 45s")


def live_start(map: str, graph_name: str, push: bool = False,
               record: str | None = None) -> dict:
    """Start the single-owner bridge, then ensure the isolated viewer is served.

    push=True: authoritative per-frame pmove stream (needs a telemetry-capable
    .so; falls back to poll mode after 5 s otherwise). record: append raw
    pmove rows as JSONL — the durable evidence that replaces owner qwd:s."""
    if not _safe_overlay_name(graph_name):
        raise ValueError("graph_name must contain only ASCII letters, digits, '-' or '_'")
    graph = OVERLAYS_DIR / f"{graph_name}-graph.json"
    if not graph.exists():
        raise FileNotFoundError(f"viewer graph not found: {graph}")
    if not (SKELETON / "qw" / "maps" / f"{map}.bsp").exists():
        raise ValueError(f"map {map!r} not in skeleton maps")

    _remove_live_state()
    subprocess.run(["systemctl", "--user", "stop", LIVE_UNIT], capture_output=True)
    argv = [
        "systemd-run", "--user", "--collect", f"--unit={LIVE_UNIT}",
        f"--working-directory={FASTTRACK_DIR.parent}", "--property=Nice=19", "--",
        "python3", "-u", str(LIVE_BRIDGE), "--control", str(CONTROL_PORT),
        "--graph", str(graph), "--ws-port", "8093", "--proxy-port", "27981",
    ]
    if push:
        argv.append("--push")
    if record is not None:
        argv += ["--record", str(record)]
    _sh(*argv)
    state = _wait_for_state()

    viewer_started = False
    if not _http_ready(8090):
        subprocess.run(["systemctl", "--user", "stop", VIEWER_UNIT], capture_output=True)
        trunk = Path.home() / ".cargo" / "bin" / "trunk"
        _sh(
            "systemd-run", "--user", "--collect", f"--unit={VIEWER_UNIT}",
            f"--working-directory={VIEWER_WORKTREE}", "--property=Nice=19", "--",
            "nice", "-n", "19", str(trunk), "serve", "--port", "8090", "--address", "127.0.0.1",
        )
        viewer_started = True
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        VIEWER_OWNERSHIP.write_text(json.dumps({"unit": VIEWER_UNIT}), encoding="utf-8")
        deadline = time.monotonic() + 180.0
        while time.monotonic() < deadline and not _http_ready(8090, timeout=2.0):
            if not _unit_active(VIEWER_UNIT):
                logs = subprocess.run(
                    ["journalctl", "--user", "-u", VIEWER_UNIT, "-n", "40", "--no-pager"],
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                raise RuntimeError(f"viewer stopped before readiness: {logs[-3000:]}")
            time.sleep(1.0)
        if not _http_ready(8090, timeout=2.0):
            raise TimeoutError("viewer did not answer on 8090 within 180s")
    else:
        VIEWER_OWNERSHIP.unlink(missing_ok=True)

    url = f"http://127.0.0.1:8090/?graph={graph_name}&live={state['ws']}"
    return {
        "map": map,
        "graph": graph_name,
        "url": url,
        "proxy": state["proxy"],
        "ws": state["ws"],
        "viewer_started": viewer_started,
    }


def live_stop() -> dict:
    """Remove routing state first, then stop units owned by live_start."""
    _remove_live_state()
    subprocess.run(["systemctl", "--user", "stop", LIVE_UNIT], capture_output=True)
    viewer_stopped = False
    if VIEWER_OWNERSHIP.exists():
        VIEWER_OWNERSHIP.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "stop", VIEWER_UNIT], capture_output=True)
        viewer_stopped = True
    if LIVE_STATE.exists():
        raise RuntimeError("live bridge state file remained after stop")
    return {
        "bridge_stopped": not _unit_active(LIVE_UNIT),
        "viewer_stopped": viewer_stopped and not _unit_active(VIEWER_UNIT),
        "state_removed": not LIVE_STATE.exists(),
    }


def _wsl_path(p: str) -> str:
    if len(p) > 2 and p[1] == ":" and (p[2] == "\\" or p[2] == "/"):
        return f"/mnt/{p[0].lower()}/" + p[3:].replace("\\", "/")
    return p


def _start_viewer_if_needed() -> bool:
    """Serve the worktree viewer on 8090 as a unit unless it already answers."""
    if _http_ready(8090):
        return False
    subprocess.run(["systemctl", "--user", "stop", VIEWER_UNIT], capture_output=True)
    trunk = Path.home() / ".cargo" / "bin" / "trunk"
    _sh("systemd-run", "--user", "--collect", f"--unit={VIEWER_UNIT}",
        f"--working-directory={VIEWER_WORKTREE}", "--property=Nice=19", "--",
        "nice", "-n", "19", str(trunk), "serve", "--port", "8090", "--address", "127.0.0.1")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    VIEWER_OWNERSHIP.write_text(json.dumps({"unit": VIEWER_UNIT}), encoding="utf-8")
    deadline = time.monotonic() + 180.0
    while time.monotonic() < deadline and not _http_ready(8090, timeout=2.0):
        if not _unit_active(VIEWER_UNIT):
            logs = subprocess.run(
                ["journalctl", "--user", "-u", VIEWER_UNIT, "-n", "40", "--no-pager"],
                capture_output=True, text=True).stdout.strip()
            raise RuntimeError(f"viewer stopped before readiness: {logs[-3000:]}")
        time.sleep(1.0)
    if not _http_ready(8090, timeout=2.0):
        raise TimeoutError("viewer did not answer on 8090 within 180s")
    return True


def demo_replay_start(demo: str, graph_name: str, speed: float = 1.0) -> dict:
    """Replay a qwd on the mesh in the viewer — the creation loop.

    Used elements highlight; mesh gaps glow red with exact geometry
    (unmeshed ground, linkless traversals). Needs NO game server and does
    not touch the control channel — safe alongside live_start."""
    demo_path = _wsl_path(demo)
    if not Path(demo_path).exists():
        raise FileNotFoundError(f"demo {demo_path} not found")
    # Same canonical main-tree overlay the 18089 sidecar/browser fetches.
    graph_path = OVERLAYS_DIR / f"{graph_name}-graph.json"
    if not graph_path.exists():
        raise FileNotFoundError(f"viewer graph not found: {graph_path}")
    subprocess.run(["systemctl", "--user", "stop", REPLAY_UNIT], capture_output=True)
    _sh("systemd-run", "--user", "--collect", f"--unit={REPLAY_UNIT}",
        "--property=Nice=19", "--",
        "python3", str(FASTTRACK_DIR / "demo_replay.py"),
        "--demo", demo_path, "--graph", str(graph_path),
        "--ws-port", str(REPLAY_WS_PORT), "--speed", f"{speed:g}", "--loop")
    _start_viewer_if_needed()
    if not _unit_active(REPLAY_UNIT):
        logs = subprocess.run(
            ["journalctl", "--user", "-u", REPLAY_UNIT, "-n", "30", "--no-pager"],
            capture_output=True, text=True).stdout.strip()
        raise RuntimeError(f"replay unit died on start: {logs[-2000:]}")
    return {"demo": Path(demo_path).name, "graph": graph_name, "ws": REPLAY_WS_PORT,
            "url": f"http://127.0.0.1:8090/?graph={graph_name}&live={REPLAY_WS_PORT}"}


def demo_replay_stop() -> dict:
    subprocess.run(["systemctl", "--user", "stop", REPLAY_UNIT], capture_output=True)
    return {"replay_stopped": not _unit_active(REPLAY_UNIT)}


def missing_spec(name: str, map: str, demo: str | None = None) -> dict:
    """Export the accumulated mesh-gap list as a navmesh-developer spec.

    Source: a demo (offline, exact — reruns the coverage diff) or, without
    `demo`, the running live bridge's accumulated gaps (__missing__). Writes
    route-lab artifacts/nav-patches/<map>-<name>-missing-spec.json."""
    if demo is not None:
        import demo_mesh
        graph_file = OVERLAYS_DIR / f"{map}-graph.json"
        result = demo_mesh.ingest(_wsl_path(demo), map, str(graph_file), name)
        payload = {"source": {"demo": Path(_wsl_path(demo)).name,
                              "grounding": result["evidence"]["grounding"]},
                   "summary": result["summary"],
                   "patch_for_missing_links": result["patch"]}
    else:
        c = Control()
        try:
            data = c.request("__missing__")["data"]
        finally:
            c.close()
        payload = {"source": {"live_bridge": True}, "missing_by_actor": data}
    PROMOTE_DIR.mkdir(parents=True, exist_ok=True)
    out = PROMOTE_DIR / f"{map}-{name}-missing-spec.json"
    out.write_text(json.dumps({
        "schema": "qw-missing-spec/1", "map": map, "name": name, **payload,
    }, indent=1), encoding="utf-8")
    return {"spec": str(out),
            "note": "spec till navmesh-utvecklaren; för länkar finns adds-formatet "
                    "redo att planteras/patchas (qw-nav-patch/1)"}


def demo_ingest(demo: str, map: str, name: str | None = None,
                graph: str | None = None, min_link_dist: float = 96.0,
                player: int | None = None) -> dict:
    """Demo -> required mesh: coverage diff + viewer overlay + ready patch.

    `graph` = qw-nav-graph/1 JSON to diff against — a path, or an overlay
    name in the viewer overlays dir. Default: <map>-graph.json there (run
    graph_dump first for a live one). qwd only for now."""
    demo_path = _wsl_path(demo)
    if demo_path.endswith(".mvd"):
        raise ValueError("mvd not supported yet — use the qwd (positions parser pending)")
    name = name or Path(demo_path).stem
    if graph is None:
        graph = str(OVERLAYS_DIR / f"{map}-graph.json")
    elif "/" not in graph and "\\" not in graph:
        graph = str(OVERLAYS_DIR / f"{graph}-graph.json")
    else:
        graph = _wsl_path(graph)
    if not Path(graph).exists():
        raise FileNotFoundError(f"graph {graph} not found — run graph_dump first "
                                f"or pass graph=<overlay name|path>")
    import demo_mesh
    result = demo_mesh.ingest(demo_path, map, graph, name, min_link_dist, player)
    OVERLAYS_DIR.mkdir(parents=True, exist_ok=True)
    overlay_path = OVERLAYS_DIR / f"{name}-graph.json"
    overlay_path.write_text(json.dumps(result["overlay"], separators=(",", ":")),
                            encoding="utf-8")
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    patch_path = PATCHES_DIR / f"{name}.json"
    patch_path.write_text(json.dumps(result["patch"], indent=1), encoding="utf-8")
    return {"summary": result["summary"], "duration_s": result["duration_s"],
            "evidence": result["evidence"],
            "diffed_against": graph,
            "overlay": str(overlay_path),
            "viewer": f"http://127.0.0.1:8088/?graph={name}",
            "patch": str(patch_path),
            "patch_adds": len(result["patch"]["adds"]),
            "next": f"patch_apply(<patch file content>) -> trial(...) -> promote({name!r})"}


def _gap_phase(name: str, started_at: float, operation: Callable[[], dict]) -> dict:
    """Run one synchronous phase under both its own and the workflow deadline.

    The production runtime is WSL/main-thread, where SIGALRM interrupts blocked
    Python/subprocess calls. Other runtimes fail closed before the operation;
    an after-the-fact elapsed check is not a timeout.
    """
    budget = (GAP_TOTAL_TIMEOUT_S if name in ("cleanup_restart", "evidence_write")
              else GAP_WORK_TIMEOUT_S)
    total_remaining = budget - (time.monotonic() - started_at)
    limit = min(GAP_PHASE_TIMEOUTS_S[name], total_remaining)
    if limit <= 0:
        raise TimeoutError(f"gap_to_proof total timeout before {name}")

    can_alarm = hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
    if not can_alarm:
        raise RuntimeError("bounded gap_to_proof phases require WSL/POSIX main-thread SIGALRM")
    old_handler = None
    old_timer = None
    phase_started = time.monotonic()
    def timed_out(_signum, _frame):
        raise TimeoutError(f"gap_to_proof phase {name} timed out after {limit:g}s")

    old_handler = signal.signal(signal.SIGALRM, timed_out)
    old_timer = signal.setitimer(signal.ITIMER_REAL, limit)
    try:
        result = operation()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer and old_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *old_timer)
    elapsed = time.monotonic() - phase_started
    if elapsed > limit:
        raise TimeoutError(f"gap_to_proof phase {name} timed out after {limit:g}s")
    return result


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")


def _proof_attempts(baseline: dict, patched: dict) -> list[dict]:
    rows = []
    before = baseline.get("rows") or []
    after = patched.get("rows") or []
    for index in range(max(len(before), len(after))):
        baseline_row = before[index] if index < len(before) else None
        patched_row = after[index] if index < len(after) else None
        baseline_elapsed = baseline_row.get("elapsed") if baseline_row else None
        patched_elapsed = patched_row.get("elapsed") if patched_row else None
        rows.append({
            "attempt": index + 1,
            "baseline": ({key: baseline_row.get(key)
                          for key in ("elapsed", "outcome", "streak")}
                         if baseline_row else None),
            "patched": ({key: patched_row.get(key)
                         for key in ("elapsed", "outcome", "streak")}
                        if patched_row else None),
            # Negative means the patch was faster. Unpaired/timeout rows have no delta.
            "delta_s": (round(float(patched_elapsed) - float(baseline_elapsed), 6)
                        if baseline_elapsed is not None and patched_elapsed is not None else None),
        })
    return rows


def gap_to_proof(demo: str, map: str, seed: list[float], route: dict,
                 name: str | None = None) -> dict:
    """Execute the ordered clean-baseline -> gap -> A/B proof workflow.

    Ownership is deliberately checked before the first mutation. Once this
    function boots the server, every exit (including cancellation) clears the
    patch and restarts the map into a clean state.
    """
    if not isinstance(route, dict):
        raise ValueError("route is required")
    missing = [key for key in ("start", "target", "arrive_box") if key not in route]
    if missing:
        raise ValueError(f"route is missing required fields: {', '.join(missing)}")
    if len(seed) != 3:
        raise ValueError("seed must contain three coordinates")
    if not all(isinstance(route[key], list) for key in ("start", "target", "arrive_box")):
        raise ValueError("route start, target and arrive_box must be arrays")

    # Unit status is the ownership authority. Never stop or inherit a server
    # or bridge started by somebody else.
    server_unit_status = _unit_status(UNIT)
    if server_unit_status != "inactive":
        raise RuntimeError(
            f"experimentservern {UNIT} är inte säkert inaktiv ({server_unit_status}); "
            "gap_to_proof tar aldrig över en körande eller oklar server")
    live_unit_status = _unit_status(LIVE_UNIT)
    if live_unit_status != "inactive":
        raise RuntimeError(
            f"live-bryggan {LIVE_UNIT} är inte säkert inaktiv ({live_unit_status}); "
            "stoppa eller återställ den innan gap_to_proof")

    run_name = name or Path(_wsl_path(demo)).stem
    if not _safe_overlay_name(run_name):
        raise ValueError("name may contain only ASCII letters, digits, '-' and '_'")
    bundle = EVIDENCE_DIR / run_name
    bundle.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    current_phase = "baseline_boot"
    phase_elapsed: dict[str, float] = {}
    ingest_result = None
    patch_value = None
    baseline = None
    patched = None
    graph_result = None
    failure: BaseException | None = None
    failure_tb = None
    cleanup_errors = []
    completed = False

    def phase(phase_name: str, operation: Callable[[], dict]) -> dict:
        nonlocal current_phase
        current_phase = phase_name
        phase_started = time.monotonic()
        try:
            return _gap_phase(phase_name, started, operation)
        finally:
            phase_elapsed[phase_name] = round(time.monotonic() - phase_started, 6)

    try:
        # A stale bridge state file is not ownership; the inactive unit status
        # above permits removing it before graph_dump's conservative interlock.
        _remove_live_state()

        def clean_boot() -> dict:
            patch_clear()
            return server_up(map)

        phase("baseline_boot", clean_boot)
        graph_result = phase(
            "graph_dump", lambda: graph_dump(map, seed, f"{run_name}-baseline"))
        ingest_result = phase(
            "demo_ingest", lambda: demo_ingest(
                demo, map, run_name, str(graph_result["out"])))
        patch_value = json.loads(Path(ingest_result["patch"]).read_text(encoding="utf-8"))

        trial_args = {
            "arrive_box": route["arrive_box"],
            "pass_time_s": (float(route["pass_time_s"])
                            if route.get("pass_time_s") is not None else None),
            # Supplying the default explicitly guarantees Trial v2 even when
            # the caller omits both optional route gates.
            "streak_target": int(route.get("streak_target", 5)),
        }
        baseline = phase(
            "baseline_trial", lambda: trial(route["start"], route["target"], **trial_args))
        phase("patch_apply", lambda: patch_apply(patch_value))
        patched = phase(
            "patched_trial", lambda: trial(route["start"], route["target"], **trial_args))
        completed = True
    except BaseException as exc:
        failure = exc
        failure_tb = exc.__traceback__
    finally:
        # Clear and restart are independent cleanup obligations: a failed clear
        # must not prevent the clean restart attempt.
        try:
            patch_clear()
        except BaseException as exc:
            cleanup_errors.append(f"patch_clear: {type(exc).__name__}: {exc}")
        try:
            _gap_phase("cleanup_restart", started, lambda: server_up(map))
        except BaseException as exc:
            cleanup_errors.append(f"server_restart: {type(exc).__name__}: {exc}")

        partial = not completed or bool(cleanup_errors)
        artifacts: dict[str, dict] = {}
        if ingest_result is not None and patch_value is not None:
            artifacts["gaps.json"] = {
                "schema": "qw-gap-evidence/1", "map": map, "name": run_name,
                "summary": ingest_result.get("summary"),
                "missing_cells": (ingest_result.get("summary") or {}).get("cells_missing_points"),
                "missing_links": patch_value.get("adds") or [],
                "grounding": (ingest_result.get("evidence") or {}).get("grounding"),
                "overlay": ingest_result.get("overlay"),
            }
            artifacts["patch.json"] = patch_value
        if baseline is not None and patched is not None:
            artifacts["ab.json"] = {
                "schema": "qw-gap-proof-ab/1", "route": route,
                "baseline": baseline, "patched": patched,
                "attempts": _proof_attempts(baseline, patched),
            }
        if graph_result is not None:
            grounding = ((ingest_result or {}).get("evidence") or {}).get("grounding") or {}
            patched_provenance = (patched or {}).get("provenance") or {}
            patch_file_sha = (hashlib.sha256(json.dumps(patch_value, indent=1).encode()).hexdigest()
                              if patch_value is not None else None)
            artifacts["provenance.json"] = {
                "schema": "qw-gap-proof-provenance/1",
                "graph_sha": graph_result.get("graph_sha"),
                "patch_sha": patched_provenance.get("patch_sha") or patch_file_sha,
                "bsp_sha": grounding.get("bsp_sha"),
                "probe_commit": grounding.get("probe_commit"),
                "cvar_readback": {
                    "baseline": (baseline or {}).get("provenance", {}).get("cvar_readback"),
                    "patched": patched_provenance.get("cvar_readback"),
                },
            }

        def write_bundle() -> dict:
            manifest_files = []
            for filename, payload in artifacts.items():
                path = bundle / filename
                _write_json(path, payload)
                manifest_files.append({
                    "file": filename,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
            manifest = {
                "schema": "qw-gap-proof-manifest/1", "name": run_name, "map": map,
                "partial": partial,
                "failed_phase": current_phase if failure is not None else None,
                "error": (f"{type(failure).__name__}: {failure}"
                          if failure is not None else None),
                "cleanup_errors": cleanup_errors,
                "phase_elapsed_s": phase_elapsed,
                "total_elapsed_s": round(time.monotonic() - started, 6),
                "files": manifest_files,
            }
            _write_json(bundle / "manifest.json", manifest)
            return manifest

        _gap_phase("evidence_write", started, write_bundle)

    if failure is not None:
        raise failure.with_traceback(failure_tb)
    if cleanup_errors:
        raise RuntimeError(
            f"gap_to_proof proof completed but cleanup failed; partial bundle: {bundle}: "
            + "; ".join(cleanup_errors))
    return {"bundle": str(bundle), "manifest": str(bundle / "manifest.json"),
            "partial": False, "passed": bool(patched and patched.get("passed")),
            "baseline_streak": baseline.get("streak_max"),
            "patched_streak": patched.get("streak_max")}


def promote(name: str, map: str) -> dict:
    """Promote a proven patch to production: route-lab artifact + hand-off.

    The v2 gate is a complete, SHA-verified gap_to_proof bundle whose patched
    Trial v2 reached its streak target. A legacy ledger with ok>0 is not proof.
    """
    patch_path = PATCHES_DIR / f"{name}.json"
    if not patch_path.exists():
        raise FileNotFoundError(f"no stored patch {name!r} — run gap_to_proof first")
    proof_dir = EVIDENCE_DIR / name
    manifest_path = proof_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"no gap_to_proof bundle for {name!r}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "qw-gap-proof-manifest/1" or manifest.get("partial") is not False:
        raise RuntimeError(f"gap_to_proof bundle for {name!r} is partial or invalid")
    required = {"gaps.json", "patch.json", "ab.json", "provenance.json"}
    listed = {entry.get("file"): entry.get("sha256") for entry in manifest.get("files") or []}
    missing = required - set(listed)
    if missing:
        raise RuntimeError(f"gap_to_proof bundle missing: {', '.join(sorted(missing))}")
    for filename in sorted(required):
        path = proof_dir / filename
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if actual != listed[filename]:
            raise RuntimeError(f"gap_to_proof bundle SHA mismatch: {filename}")

    ab = json.loads((proof_dir / "ab.json").read_text(encoding="utf-8"))
    attempts = ab.get("attempts")
    if (ab.get("schema") != "qw-gap-proof-ab/1" or not isinstance(attempts, list)
            or not attempts):
        raise RuntimeError("gap_to_proof A/B evidence is invalid")
    for row in attempts:
        before = row.get("baseline") if isinstance(row, dict) else None
        after = row.get("patched") if isinstance(row, dict) else None
        before_valid = (before is None
                        or (isinstance(before, dict)
                            and {"elapsed", "streak"} <= set(before)))
        after_valid = (after is None
                       or (isinstance(after, dict)
                           and {"elapsed", "streak"} <= set(after)))
        if (not isinstance(row, dict) or (before is None and after is None)
                or not before_valid or not after_valid or "delta_s" not in row):
            raise RuntimeError("gap_to_proof A/B evidence lacks per-attempt elapsed/streak/delta")

    proof_provenance = json.loads(
        (proof_dir / "provenance.json").read_text(encoding="utf-8"))
    if proof_provenance.get("schema") != "qw-gap-proof-provenance/1":
        raise RuntimeError("gap_to_proof provenance evidence is invalid")
    for key in ("graph_sha", "patch_sha", "bsp_sha"):
        value = proof_provenance.get(key)
        try:
            valid_sha = isinstance(value, str) and len(value) == 64 and int(value, 16) >= 0
        except ValueError:
            valid_sha = False
        if not valid_sha:
            raise RuntimeError(f"gap_to_proof provenance lacks valid {key}")
    readbacks = proof_provenance.get("cvar_readback") or {}
    for side in ("baseline", "patched"):
        if not set(TRIAL_CVARS) <= set(readbacks.get(side) or {}):
            raise RuntimeError(f"gap_to_proof provenance lacks {side} cvar readback")

    baseline = ab.get("baseline") or {}
    patched = ab.get("patched") or {}
    streak_target = int((ab.get("route") or {}).get("streak_target", 5))
    patched_streak = int(patched.get("streak_max", 0))
    if baseline.get("streak_max") is None:
        raise RuntimeError("gap_to_proof A/B evidence lacks baseline streak")
    if patched.get("passed") is not True or patched_streak < streak_target:
        raise RuntimeError(
            f"patched streak {patched_streak}/{streak_target} did not pass; not promotable")

    patch = json.loads(patch_path.read_text(encoding="utf-8"))
    proof_patch = json.loads((proof_dir / "patch.json").read_text(encoding="utf-8"))
    if patch != proof_patch:
        raise RuntimeError("stored patch differs from the SHA-verified proof patch")
    PROMOTE_DIR.mkdir(parents=True, exist_ok=True)
    artifact = PROMOTE_DIR / f"{map}-{name}.json"
    artifact.write_text(json.dumps({
        **patch,
        "provenance": {**(patch.get("provenance") or {}),
                       "promoted_by": "qw-fasttrack",
                       "evidence": {
                           "schema": "qw-gap-proof-manifest/1",
                           "bundle": f"{map}-{name}-proof",
                           "baseline_streak": baseline["streak_max"],
                           "patched_streak": patched_streak,
                           "streak_target": streak_target,
                       }},
    }, indent=1), encoding="utf-8")
    promoted_proof = PROMOTE_DIR / f"{map}-{name}-proof"
    shutil.copytree(proof_dir, promoted_proof, dirs_exist_ok=True)
    handoff = PROMOTE_DIR / f"{map}-{name}-handoff.md"
    handoff.write_text(f"""# Nav-patch hand-off: {map} / {name}

Bevisad i qw-fasttrack med Trial v2 A/B: patchad streak
**{patched_streak}/{streak_target}** (baseline streak {baseline['streak_max']}).
Komplett SHA-verifierad evidens: `{promoted_proof.name}/manifest.json`.

- Patch: `{artifact.name}` (schema qw-nav-patch/1 — adds plantable via
  `planlink from takeoff to v_req` after setting any listed cvars).
- Rule 11.2 clean: placement/target values only, no trajectories/inputs.
- Planted links die on map restart: production servers need the plant in
their boot path (same replant pattern as fasttrack's server_up).

Suggested next step: PR into the rtx-main lane per the 7-step owner route
protocol (route -> corpus -> 20x zero-wall -> analyst -> nanos tests -> PR).
""", encoding="utf-8")
    return {"artifact": str(artifact),
            "evidence": {"baseline_streak": baseline["streak_max"],
                         "patched_streak": patched_streak,
                         "streak_target": streak_target},
            "proof_bundle": str(promoted_proof),
            "handoff": str(handoff),
            "commit_hint": f"git -C {ROUTE_LAB} add artifacts/nav-patches && "
                           f"git -C {ROUTE_LAB} commit -m 'nav-patch: {map}/{name} "
                           f"(streak {patched_streak}/{streak_target})'"}
