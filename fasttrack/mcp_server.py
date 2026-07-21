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
        "desc": "Loop teleport->goto attempts and return per-attempt outcomes + summary. Map-agnostic: start/target are [x,y,z]. Optional arrive_box [x0,y0,z0,x1,y1,z1] counts stalls inside it as success.",
        "schema": {"start": "array", "target": "array", "attempts": "integer",
                   "bot": "integer", "settle_s": "number", "timeout_s": "number",
                   "arrive_box": "array"},
        "required": ["start", "target"],
        "fn": lambda a: core.trial(a["start"], a["target"], int(a.get("attempts", 20)),
                                   a.get("bot"), float(a.get("settle_s", 0.6)),
                                   float(a.get("timeout_s", 20.0)), a.get("arrive_box")),
    },
    "graph_dump": {
        "desc": "Dump the live graph and install it as a Movement Lab overlay (<name>-graph.json). Args: map (string), seed [x,y,z] = any walkable point (crawl start), name (default 'fasttrack'). Returns the viewer URL.",
        "schema": {"map": "string", "seed": "array", "name": "string"},
        "required": ["map", "seed"],
        "fn": lambda a: core.graph_dump(a["map"], a["seed"], a.get("name", "fasttrack")),
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
