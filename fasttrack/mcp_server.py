"""qw-fasttrack MCP server (stdio JSON-RPC) — the second-scale mesh loop.

Register (Claude Code .claude.json mcpServers):
  "fasttrack": {"command": "wsl.exe", "args": ["-d", "Ubuntu-24.04", "-e",
    "python3", "/mnt/c/Users/benya/projects/quakeworld/qw-fasttrack/fasttrack/mcp_server.py"]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402

TOOLS = {
    "server_up": {
        "desc": "Boot the owned experiment server on a map (any .bsp in the skeleton), wait for navmesh+bot, auto-replant the active patch. Args: map (string, required), bots (int, default 1), lib (string path to qwprogs.so, optional).",
        "schema": {"map": "string", "bots": "integer", "lib": "string"},
        "required": ["map"],
        "fn": lambda a: core.server_up(a["map"], int(a.get("bots", 1)), a.get("lib")),
    },
    "server_down": {
        "desc": "Stop the experiment server.",
        "schema": {}, "required": [],
        "fn": lambda a: core.server_down(),
    },
    "server_status": {
        "desc": "Unit state + live control status (bots, navmesh, cells/links).",
        "schema": {}, "required": [],
        "fn": lambda a: core.server_status(),
    },
    "maps_list": {
        "desc": "List maps available in the skeleton (map-agnostic surface).",
        "schema": {}, "required": [],
        "fn": lambda a: {"maps": core.available_maps()},
    },
    "ctl": {
        "desc": "Raw control-verb passthrough (escape hatch): status, links, prep, teleport, goto, fly, hold, stop, ra_trial, set, get, cmd, cell, route, curls, probe, curl, planlink, planrj, planrjraw, unlink. Args: command (string), timeout_s (number, default 15).",
        "schema": {"command": "string", "timeout_s": "number"},
        "required": ["command"],
        "fn": lambda a: core.ctl(a["command"], float(a.get("timeout_s", 15.0))),
    },
    "patch_apply": {
        "desc": "Apply a qw-nav-patch/1 object live (adds via planlink/planrjraw, removes via unlink). Stored as active patch -> auto-replant on every server_up/restart. Add objects may carry a 'cvars' map set before planting (e.g. rtx_jump_curl_*).",
        "schema": {"patch": "object"}, "required": ["patch"],
        "fn": lambda a: core.patch_apply(a["patch"]),
    },
    "patch_clear": {
        "desc": "Forget the active patch (no auto-replant on next boot).",
        "schema": {}, "required": [],
        "fn": lambda a: core.patch_clear(),
    },
    "trial": {
        "desc": "Trial v2: stop+hold, teleport/verify, then measure first received 15 Hz status position inside arrive_box. Streak mode defaults to pass_time_s unset, streak_target 5, max_time_s 8, attempts_cap 30 when any v2 parameter is supplied; old calls remain fixed-attempt compatible.",
        "schema": {"start": "array", "target": "array", "attempts": "integer",
                   "bot": "integer", "settle_s": "number", "timeout_s": "number",
                   "arrive_box": "array", "pass_time_s": "number",
                   "streak_target": "integer", "max_time_s": "number",
                   "attempts_cap": "integer"},
        "required": ["start", "target"],
        "fn": lambda a: core.trial(
            a["start"], a["target"], int(a.get("attempts", 20)), a.get("bot"),
            float(a.get("settle_s", 0.6)), float(a.get("timeout_s", 20.0)),
            a.get("arrive_box"), pass_time_s=(float(a["pass_time_s"])
                                               if "pass_time_s" in a else None),
            streak_target=(int(a["streak_target"]) if "streak_target" in a else None),
            max_time_s=(float(a["max_time_s"]) if "max_time_s" in a else None),
            attempts_cap=(int(a["attempts_cap"]) if "attempts_cap" in a else None)),
    },
    "demo_ingest": {
        "desc": "Demo -> required mesh: extract ground coverage + jump links a player's qwd needed, diff vs a qw-nav-graph/1 dump, install the demo-mesh as a viewer overlay and emit a ready qw-nav-patch/1 for the missing jumps. Args: demo (qwd path, Windows or WSL), map, name (default demo stem), graph (overlay name or path to diff against; default <map>-graph.json — run graph_dump first for a live one), min_link_dist (default 96), player (slot; default demo's local player). Rule 11.2 safe: outputs carry placement/target values only.",
        "schema": {"demo": "string", "map": "string", "name": "string",
                   "graph": "string", "min_link_dist": "number", "player": "integer"},
        "required": ["demo", "map"],
        "fn": lambda a: core.demo_ingest(a["demo"], a["map"], a.get("name"),
                                         a.get("graph"), float(a.get("min_link_dist", 96.0)),
                                         a.get("player")),
    },
    "promote": {
        "desc": "Promote a proven patch to production: writes patch + provenance + trial evidence into route-lab artifacts/nav-patches/ and drafts a hand-off for the orchestrator PR lane. Refuses without recorded trial evidence (trial() writes the ledger). Args: name (stored patch name), map.",
        "schema": {"name": "string", "map": "string"},
        "required": ["name", "map"],
        "fn": lambda a: core.promote(a["name"], a["map"]),
    },
    "graph_dump": {
        "desc": "Dump the live graph and install it as a Movement Lab overlay (<name>-graph.json). Args: map (string), seed [x,y,z] = any walkable point (crawl start), name (default 'fasttrack'). Returns the viewer URL.",
        "schema": {"map": "string", "seed": "array", "name": "string"},
        "required": ["map", "seed"],
        "fn": lambda a: core.graph_dump(a["map"], a["seed"], a.get("name", "fasttrack")),
    },
    "live_start": {
        "desc": "Start the single-owner live bridge and isolated viewer. Args: map, graph_name. Returns the loopback viewer URL.",
        "schema": {"map": "string", "graph_name": "string"},
        "required": ["map", "graph_name"],
        "fn": lambda a: core.live_start(a["map"], a["graph_name"]),
    },
    "live_stop": {
        "desc": "Remove live routing state first, then stop bridge and any viewer unit started by live_start.",
        "schema": {}, "required": [],
        "fn": lambda a: core.live_stop(),
    },
    "demo_replay_start": {
        "desc": "Replay a qwd on the mesh in the Movement Lab viewer (creation loop): the player's movement plays back live; used mesh elements highlight, MISSING elements glow red with exact geometry (unmeshed ground, linkless traversals) — ready to become a patch via demo_ingest. Needs NO game server. Args: demo (qwd path), graph_name (overlay name), speed (default 1.0). Returns viewer URL.",
        "schema": {"demo": "string", "graph_name": "string", "speed": "number"},
        "required": ["demo", "graph_name"],
        "fn": lambda a: core.demo_replay_start(a["demo"], a["graph_name"],
                                               float(a.get("speed", 1.0))),
    },
    "demo_replay_stop": {
        "desc": "Stop the demo replay unit.",
        "schema": {}, "required": [],
        "fn": lambda a: core.demo_replay_stop(),
    },
    "missing_spec": {
        "desc": "Export ALL accumulated mesh gaps as a navmesh-developer spec (qw-missing-spec/1 JSON in route-lab artifacts/nav-patches/). Args: name, map, demo (optional qwd path — exact offline diff incl. ready qw-nav-patch/1 for missing links; omit to snapshot the running live bridge's gaps).",
        "schema": {"name": "string", "map": "string", "demo": "string"},
        "required": ["name", "map"],
        "fn": lambda a: core.missing_spec(a["name"], a["map"], a.get("demo")),
    },
}


def respond(req):
    method = req.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "qw-fasttrack", "version": "0.1.0"}}
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        result = {"tools": [
            {"name": name, "description": t["desc"],
             "inputSchema": {"type": "object",
                             "properties": {k: {"type": v} for k, v in t["schema"].items()},
                             "required": t["required"]}}
            for name, t in TOOLS.items()]}
    elif method == "tools/call":
        params = req.get("params") or {}
        tool = TOOLS.get(params.get("name"))
        if tool is None:
            raise ValueError(f"unknown tool {params.get('name')}")
        value = tool["fn"](params.get("arguments") or {})
        result = {"content": [{"type": "text",
                               "text": json.dumps(value, ensure_ascii=False, indent=1)}],
                  "isError": False}
    else:
        raise ValueError(f"unknown method {method}")
    return {"jsonrpc": "2.0", "id": req.get("id"), "result": result}


if __name__ == "__main__":
    for line in sys.stdin:
        try:
            req = json.loads(line)
            response = respond(req)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
        except Exception as exc:  # surface every failure as a JSON-RPC error
            rid = req.get("id") if isinstance(locals().get("req"), dict) else None
            print(json.dumps({"jsonrpc": "2.0", "id": rid,
                              "error": {"code": -32603, "message": str(exc)}}), flush=True)
