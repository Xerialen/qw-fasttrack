"""End-to-end smoke: up(dm3) -> patch_apply(proven SNG jump) -> trial(3) -> dump.

The patch is the 20/20-proven stairs->SNG link (human-calibrated, 2026-07-21).
Run inside WSL:  nice -n 19 python3 fasttrack/smoke.py
"""
import json

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

print("== server_up(dm3) ==", flush=True)
print(json.dumps(core.server_up("dm3"), indent=1), flush=True)
print("== patch_apply ==", flush=True)
print(json.dumps(core.patch_apply(PATCH), indent=1), flush=True)
print("== trial x3 ==", flush=True)
r = core.trial([-128, 832, 121], [-303, 526, 121], attempts=3)
print(json.dumps(r, indent=1), flush=True)
print("== graph_dump ==", flush=True)
print(json.dumps(core.graph_dump("dm3", [-128, 832, 120])), flush=True)
print(f"SMOKE: {r['ok']}/{r['attempts']} arrived", flush=True)
