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
from ground_oracle import GroundOracle, OracleUnavailable, heuristic_evidence  # noqa: E402

GRID = 32.0
GROUND_WINDOW_S = 0.10   # one-sided plateau window, independent of demo fps
GROUND_Z_TOL = 1.0       # max z spread inside the window to count as grounded
MIN_AIR_S = 0.15         # shorter airborne runs are stair steps, not jumps
APPROACH_S = 0.5         # how far before takeoff the patch "from" point sits
DEDUP_SNAP = 64.0        # jumps sharing takeoff+landing 64-buckets are one link
CELL_MATCH_XY = 24.0     # live-cell match tolerance around a required cell
CELL_MATCH_Z = 40.0
LINK_MATCH = 64.0        # live-link endpoint tolerance around a required jump


def sample_sort_key(sample: tuple) -> tuple:
    """Total ordering for demo samples, including equal-time parser output."""
    return (float(sample[0]), float(sample[1]), float(sample[2]), float(sample[3]),
            float(sample[4]) if sample[4] is not None else -math.inf)


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
    out.sort(key=sample_sort_key)
    if not out:
        raise ValueError(f"no playerinfo samples for player slot {slot}")
    return out


def _heuristic_grounded_mask(samples: list[tuple]) -> list[bool]:
    """Classify samples with stable time windows on either side.

    One-sided windows preserve the final ground sample before takeoff and the
    first one after landing. At a Quake jump apex, 0.10 s of gravity changes
    z by 0.5 * 800 * 0.10^2 = 4 units, four times the plateau tolerance, so a
    short low-velocity apex cannot masquerade as ground. Quantized QWD values
    can make a side straddle the apex and return to the same height with less
    than one unit of spread, so a stable side also rejects a pronounced peak
    between two lower endpoints. A near-landing airborne sample can similarly
    borrow a stable post-landing plateau, so its adjacent vertical step must
    also be flat. A side needs at least one neighbour; an isolated sample is
    not evidence of a surface.
    """
    def stable_side(values: list[float], *, current_at_start: bool) -> bool:
        if len(values) < 2 or max(values) - min(values) >= GROUND_Z_TOL:
            return False
        adjacent_step = (
            values[1] - values[0]
            if current_at_start
            else values[-1] - values[-2]
        )
        if abs(adjacent_step) >= GROUND_Z_TOL / 4.0:
            return False
        peak = max(values)
        turn_margin = GROUND_Z_TOL / 2.0
        return not (
            peak - values[0] >= turn_margin
            and peak - values[-1] >= turn_margin
        )

    times = [float(s[0]) for s in samples]
    z = [s[3] for s in samples]
    n = len(z)
    mask = []
    backward = 0
    forward = 0
    for i in range(n):
        while times[i] - times[backward] > GROUND_WINDOW_S:
            backward += 1
        forward = max(forward, i + 1)
        while forward < n and times[forward] - times[i] <= GROUND_WINDOW_S:
            forward += 1

        before = z[backward:i + 1]
        after = z[i:forward]
        mask.append(
            stable_side(before, current_at_start=False)
            or stable_side(after, current_at_start=True)
        )
    return mask


def grounded_mask(samples: list[tuple], oracle=None) -> list[bool]:
    """Classify ground through bsp-probe, with flagged per-point mover fallback."""
    heuristic = _heuristic_grounded_mask(samples)
    if oracle is None:
        return heuristic
    mask = []
    for index, sample in enumerate(samples):
        point = sample[1:4]
        response = oracle.probe(point)
        if response["status"] == "unknown":
            oracle.note_unknown(index, point, response)
            mask.append(heuristic[index])
        else:
            mask.append(bool(response["grounded"]))
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


def extract(samples: list[tuple], min_link_dist: float = 96.0, oracle=None) -> dict:
    """Required cells (clustered ground points) + deduped jump events."""
    samples = sorted(samples, key=sample_sort_key)
    mask = grounded_mask(samples, oracle)

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
    cell_points = {
        key: (cells[key][1] / cells[key][0], cells[key][2] / cells[key][0],
              cells[key][3] / cells[key][0])
        for key in sorted(cells)
    }

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

    for key in sorted(jumps):
        ev = jumps[key]
        speeds = sorted(ev.pop("speeds"))
        ev["speed_median"] = speeds[len(speeds) // 2]
    return {"cells": cell_points, "jumps": [jumps[key] for key in sorted(jumps)],
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

    cells_missing = sorted(
        (p for p in extracted["cells"].values() if not cell_covered(p)),
        key=lambda point: tuple(float(value) for value in point),
    )
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
    ordered_keys = sorted(extracted["cells"])
    points = [extracted["cells"][key] for key in ordered_keys]
    index = {key: i for i, key in enumerate(ordered_keys)}

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
           min_link_dist: float = 96.0, player: int | None = None,
           probe_path: str | None = None) -> dict:
    samples = load_samples(demo_path, player)
    oracle = None
    evidence = heuristic_evidence()
    try:
        oracle = GroundOracle(map_name, probe_path)
        try:
            extracted = extract(samples, min_link_dist, oracle)
            evidence = oracle.evidence()
        except OracleUnavailable as error:
            # Discard all partial oracle classifications: this run is now wholly heuristic.
            extracted = extract(samples, min_link_dist, None)
            evidence = heuristic_evidence(error.reason)
    except OracleUnavailable as error:
        extracted = extract(samples, min_link_dist, None)
        evidence = heuristic_evidence(error.reason)
    finally:
        if oracle is not None:
            oracle.close()
    graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    summary = diff_vs_graph(extracted, graph)
    overlay = to_overlay(extracted, map_name)
    patch = to_patch(extracted, name, demo_path)
    patch["provenance"]["grounding"] = evidence
    return {"summary": summary, "overlay": overlay, "patch": patch,
            "duration_s": round(samples[-1][0] - samples[0][0], 1),
            "evidence": {"grounding": evidence}}


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
