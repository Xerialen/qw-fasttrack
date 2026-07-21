"""Demo -> required navmesh: "this player's qwd required this mesh".

Extracts, from a qwd (positions + velocities; usercmds untouched):
  - ground plateaus  -> required CELLS (32-grid clustered walk coverage)
  - airborne segments -> required LINKS (jump candidates: from/takeoff/to
    + measured takeoff speed, deduped across repeated traversals)
then diffs against a live qw-nav-graph/1 dump: which required elements the
mesh covers and which it lacks. Missing jumps come out as a ready
qw-nav-patch/1. Rule 11.2 holds by construction: the outputs carry
placement/target values only (points + a speed), never trajectories or
inputs.

MVD is not supported yet (position streams exist in match MVDs but need a
different parser); use qwd.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

QWD_TOOLS = Path("/mnt/c/Users/benya/projects/quakeworld/tools/qwd-corpus-pipeline")
sys.path.insert(0, str(QWD_TOOLS))
import qwd_dump  # noqa: E402

GRID = 32.0
GROUND_WINDOW = 2        # samples each side for plateau detection
GROUND_Z_TOL = 1.0       # max z spread inside the window to count as grounded
MIN_AIR_S = 0.15         # shorter airborne runs are stair steps, not jumps
APPROACH_S = 0.5         # how far before takeoff the patch "from" point sits
DEDUP_SNAP = 64.0        # jumps sharing takeoff+landing 64-buckets are one link
CELL_MATCH_XY = 24.0     # live-cell match tolerance around a required cell
CELL_MATCH_Z = 40.0
LINK_MATCH = 64.0        # live-link endpoint tolerance around a required jump


def load_samples(demo_path: str, player: int | None = None) -> list[tuple]:
    """[(t, x, y, z, speed_xy|None), ...] for one player, time-sorted."""
    parsed = qwd_dump.parse_demo(demo_path)
    slot = player if player is not None else (
        parsed.state.local_player if parsed.state.local_player is not None else 0)
    out = []
    for info in parsed.playerinfos:
        if info.player != slot:
            continue
        speed = None
        if info.velocity is not None:
            speed = math.hypot(info.velocity[0], info.velocity[1])
        out.append((info.time, *info.origin, speed))
    out.sort(key=lambda s: s[0])
    if not out:
        raise ValueError(f"no playerinfo samples for player slot {slot}")
    return out


def grounded_mask(samples: list[tuple]) -> list[bool]:
    z = [s[3] for s in samples]
    n = len(z)
    mask = []
    for i in range(n):
        lo = max(0, i - GROUND_WINDOW)
        hi = min(n, i + GROUND_WINDOW + 1)
        window = z[lo:hi]
        mask.append(max(window) - min(window) < GROUND_Z_TOL)
    return mask


def _speed_at(samples: list[tuple], i: int) -> float:
    if samples[i][4] is not None:
        return samples[i][4]
    j = i
    while j > 0 and samples[i][0] - samples[j][0] < 0.1:
        j -= 1
    dt = samples[i][0] - samples[j][0]
    if dt <= 0:
        return 0.0
    return math.hypot(samples[i][1] - samples[j][1], samples[i][2] - samples[j][2]) / dt


def _point_before(samples: list[tuple], i: int, mask: list[bool], back_s: float):
    j = i
    while j > 0 and samples[i][0] - samples[j][0] < back_s and mask[j - 1]:
        j -= 1
    return samples[j][1:4]


def extract(samples: list[tuple], min_link_dist: float = 96.0) -> dict:
    """Required cells (clustered ground points) + deduped jump events."""
    mask = grounded_mask(samples)

    cells: dict[tuple, list] = {}
    for s, g in zip(samples, mask):
        if not g:
            continue
        key = (math.floor(s[1] / GRID), math.floor(s[2] / GRID), math.floor(s[3] / GRID))
        acc = cells.setdefault(key, [0, 0.0, 0.0, 0.0])
        acc[0] += 1
        acc[1] += s[1]
        acc[2] += s[2]
        acc[3] += s[3]
    cell_points = {k: (a[1] / a[0], a[2] / a[0], a[3] / a[0]) for k, a in cells.items()}

    jumps: dict[tuple, dict] = {}
    i, n = 0, len(samples)
    while i < n:
        if mask[i]:
            i += 1
            continue
        start = i
        while i < n and not mask[i]:
            i += 1
        if start == 0 or i >= n:
            continue
        air_s = samples[i][0] - samples[start - 1][0]
        takeoff = samples[start - 1][1:4]
        landing = samples[i][1:4]
        hdist = math.hypot(landing[0] - takeoff[0], landing[1] - takeoff[1])
        if air_s < MIN_AIR_S or hdist < min_link_dist:
            continue
        key = (tuple(math.floor(c / DEDUP_SNAP) for c in takeoff[:2]),
               tuple(math.floor(c / DEDUP_SNAP) for c in landing[:2]))
        ev = jumps.setdefault(key, {
            "takeoff": takeoff, "landing": landing,
            "from": _point_before(samples, start - 1, mask, APPROACH_S),
            "count": 0, "speeds": [], "air_s": air_s, "hdist": round(hdist, 1)})
        ev["count"] += 1
        ev["speeds"].append(round(_speed_at(samples, start - 1), 1))

    for ev in jumps.values():
        speeds = sorted(ev.pop("speeds"))
        ev["speed_median"] = speeds[len(speeds) // 2]
    return {"cells": cell_points, "jumps": list(jumps.values()),
            "grounded_samples": sum(mask), "samples": len(samples)}


def diff_vs_graph(extracted: dict, graph: dict) -> dict:
    """Mark each required cell/jump covered or missing in the live graph."""
    live_cells = graph.get("cells") or []
    live_links = graph.get("links") or []
    by_col: dict[tuple, list] = {}
    for c in live_cells:
        by_col.setdefault((math.floor(c[0] / GRID), math.floor(c[1] / GRID)), []).append(c)

    def cell_covered(p) -> bool:
        cx, cy = math.floor(p[0] / GRID), math.floor(p[1] / GRID)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for c in by_col.get((cx + dx, cy + dy), ()):
                    if (abs(c[0] - p[0]) <= CELL_MATCH_XY and abs(c[1] - p[1]) <= CELL_MATCH_XY
                            and abs(c[2] - p[2]) <= CELL_MATCH_Z):
                        return True
        return False

    def near(a, b, tol):
        return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= CELL_MATCH_Z

    cells_missing = [p for p in extracted["cells"].values() if not cell_covered(p)]
    for jump in extracted["jumps"]:
        jump["covered"] = any(
            near(live_cells[l[0]], jump["takeoff"], LINK_MATCH)
            and near(live_cells[l[1]], jump["landing"], LINK_MATCH)
            for l in live_links)
    return {"cells_required": len(extracted["cells"]),
            "cells_missing": len(cells_missing),
            "cells_missing_points": [[round(v, 1) for v in p] for p in cells_missing[:200]],
            "jumps_required": len(extracted["jumps"]),
            "jumps_missing": sum(1 for j in extracted["jumps"] if not j["covered"])}


def to_overlay(extracted: dict, map_name: str) -> dict:
    """qw-nav-graph/1 doc of the DEMO-required mesh, viewable as an overlay.
    Covered jumps render as Jump, missing ones as SpeedJump (distinct color)."""
    points = list(extracted["cells"].values())
    index = {k: i for i, k in enumerate(extracted["cells"])}

    def nearest_idx(p):
        key = (math.floor(p[0] / GRID), math.floor(p[1] / GRID), math.floor(p[2] / GRID))
        if key in index:
            return index[key]
        return min(range(len(points)),
                   key=lambda i: (points[i][0] - p[0]) ** 2 + (points[i][1] - p[1]) ** 2
                   + (points[i][2] - p[2]) ** 2)

    links = [[nearest_idx(j["takeoff"]), nearest_idx(j["landing"]),
              ("Jump" if j.get("covered") else "SpeedJump"), round(j["air_s"], 2)]
             for j in extracted["jumps"]]
    return {"schema": "qw-nav-graph/1", "map": map_name, "grid": GRID,
            "cells": [[round(v, 1) for v in p] for p in points], "links": links}


def to_patch(extracted: dict, name: str, demo_path: str) -> dict:
    """qw-nav-patch/1 with one SpeedJump add per MISSING jump."""
    digest = hashlib.sha256(Path(demo_path).read_bytes()).hexdigest()
    adds = [{
        "kind": "SpeedJump",
        "from": [round(v, 1) for v in j["from"]],
        "takeoff": [round(v, 1) for v in j["takeoff"]],
        "to": [round(v, 1) for v in j["landing"]],
        "v_req": j["speed_median"],
        "observed": {"traversals": j["count"], "air_s": round(j["air_s"], 2),
                     "hdist": j["hdist"]},
    } for j in extracted["jumps"] if not j.get("covered")]
    return {"schema": "qw-nav-patch/1", "name": name, "adds": adds,
            "provenance": {"demo": Path(demo_path).name, "demo_sha256": digest,
                           "rule": "11.2: placement/target values only"}}


def ingest(demo_path: str, map_name: str, graph_path: str, name: str,
           min_link_dist: float = 96.0, player: int | None = None) -> dict:
    samples = load_samples(demo_path, player)
    extracted = extract(samples, min_link_dist)
    graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    summary = diff_vs_graph(extracted, graph)
    overlay = to_overlay(extracted, map_name)
    patch = to_patch(extracted, name, demo_path)
    return {"summary": summary, "overlay": overlay, "patch": patch,
            "duration_s": round(samples[-1][0] - samples[0][0], 1)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("demo")
    ap.add_argument("--map", required=True)
    ap.add_argument("--graph", required=True, help="live qw-nav-graph/1 JSON to diff against")
    ap.add_argument("--name", default=None)
    ap.add_argument("--min-link-dist", type=float, default=96.0)
    ap.add_argument("--player", type=int, default=None)
    args = ap.parse_args()
    result = ingest(args.demo, args.map, args.graph,
                    args.name or Path(args.demo).stem, args.min_link_dist, args.player)
    print(json.dumps({k: v for k, v in result.items() if k != "overlay"}, indent=1))
