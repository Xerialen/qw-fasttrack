"""qw-fasttrack core: owned experiment server + control client + session state.

Map-agnostic prototype. Every tool takes the map/coords as parameters; the
only baked-in facts are the port block, the runtime paths, and the pinned
forbidden cvars (permanent lab ban). Runs inside WSL (systemd --user).
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

# Own port block — never the deck's (8765/8767) or the orchestration's
# (27504/06/08/16/21) ports. Control = game + 450 by lab convention.
GAME_PORT, CONTROL_PORT, QTV_PORT = 27530, 27980, 29530
UNIT = "fasttrack-server"

RUNTIME = Path.home() / ".local" / "share" / "qw-fasttrack" / "runtime"
STATE_DIR = Path.home() / ".local" / "share" / "qw-fasttrack"
ACTIVE_PATCH = STATE_DIR / "active-patch.json"
SKELETON = Path.home() / ".local" / "share" / "route-lab" / "nav-ab"
DEFAULT_LIB = Path.home() / ".local" / "share" / "route-lab" / "rtx-main" / "qw" / "qwprogs.so"
DUMP_LIVE_GRAPH = Path("/mnt/c/Users/benya/projects/quakeworld/route-lab/ops/dump_live_graph.py")
VIEWER_OVERLAYS = Path("/mnt/c/Users/benya/projects/quakeworld/route-lab/qw-nav-viewer/overlays")

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


class Control:
    """Newline-JSON control client (single connection, request/reply + events)."""

    def __init__(self, host: str = "127.0.0.1", port: int = CONTROL_PORT, timeout: float = 30.0):
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

    def request(self, verb_and_args: str, timeout: float = 15.0) -> dict:
        rid = self._next_id
        self._next_id += 1
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
    ready = wait_ready()
    replant = replant_active_patch() if ACTIVE_PATCH.exists() else None
    return {"game": GAME_PORT, "control": CONTROL_PORT, "qtv": QTV_PORT,
            "map": map, "ready": ready, "replant": replant}


def wait_ready(timeout_s: int = 900) -> dict:
    """Poll the control socket until navmesh=ready and a live bot exists."""
    deadline = time.monotonic() + timeout_s
    last_err = None
    while time.monotonic() < deadline:
        try:
            ctl = Control(timeout=5.0)
            try:
                status = ctl.request("status")["data"]
                bots = [b for b in status.get("bots", []) if b.get("alive")]
                if status.get("navmesh") == "ready" and bots:
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
    return summary


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


def trial(start: list[float], target: list[float], attempts: int = 20,
          bot: int | None = None, settle_s: float = 0.6, timeout_s: float = 20.0,
          arrive_box: list[float] | None = None) -> dict:
    """Generic teleport->goto loop, map-agnostic. Success = `arrived` event
    (or final traj sample inside arrive_box [x0,y0,z0,x1,y1,z1] if given)."""
    c = Control()
    try:
        if bot is None:
            status = c.request("status")["data"]
            alive = [b for b in status.get("bots", []) if b.get("alive")]
            if not alive:
                raise RuntimeError("no live bot")
            bot = int(alive[0]["ent"])
        rows = []
        for i in range(attempts):
            c.request(f"teleport {bot} {start[0]:g} {start[1]:g} {start[2]:g}")
            time.sleep(settle_s)
            c.events.clear()
            c.request(f"goto {bot} {target[0]:g} {target[1]:g} {target[2]:g}")
            ev = c.wait_event(("arrived", "goto_stall"), timeout=timeout_s)
            outcome, final = "timeout", None
            if ev is not None:
                traj = ev.get("traj") or []
                final = traj[-1] if traj else None
                if ev.get("ev") == "arrived":
                    outcome = "arrived"
                elif final and arrive_box and len(final) >= 4 and (
                        arrive_box[0] <= final[1] <= arrive_box[3] and
                        arrive_box[1] <= final[2] <= arrive_box[4] and
                        arrive_box[2] <= final[3] <= arrive_box[5]):
                    outcome = "stall_in_box"
                else:
                    outcome = "stall"
            rows.append({"attempt": i + 1, "outcome": outcome,
                         "t": (ev or {}).get("t"), "dist": (ev or {}).get("dist"),
                         "final": final})
        ok = sum(1 for r in rows if r["outcome"] in ("arrived", "stall_in_box"))
        return {"bot": bot, "attempts": attempts, "ok": ok, "rows": rows}
    finally:
        c.close()


def graph_dump(map: str, seed: list[float], out_name: str = "fasttrack") -> dict:
    """Dump the live graph via route-lab's dump_live_graph.py and install it
    as a viewer overlay (<out_name>-graph.json). Seed = any walkable point on
    the map (crawl start) — map-agnostic, caller supplies it."""
    out = VIEWER_OVERLAYS / f"{out_name}-graph.json"
    _sh("python3", str(DUMP_LIVE_GRAPH), "--port", str(CONTROL_PORT),
        "--map", map, "--seed", *(f"{x:g}" for x in seed), "--out", str(out))
    return {"out": str(out), "viewer": f"http://127.0.0.1:8088/?graph={out_name}"}
