#!/usr/bin/env python3
"""Bygg syntetiska miniserier (inte T1h). Körs en gång, output committas."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def tick(t, origin, **extra):
    row = {"t": t, "wall": t, "players": [
        {"ent": 1, "origin": origin, "on_ground": origin[2] < 60}]}
    row.update(extra)
    return row


def drop_traj(t0, xy, z_hi=328.0, z_lo=56.0, extra=None):
    extra = extra or {}
    return [
        tick(t0, [xy[0], xy[1], z_hi], **extra),
        tick(t0 + 0.02, [xy[0] + 1, xy[1], z_hi - 10], **extra),
        tick(t0 + 0.08, [xy[0] + 2, xy[1], z_lo], **extra),  # Δz > 150
    ]


def meta(cykel, ben, start, utfall, falls=0, tid=1.0):
    return {"start": start, "utfall": utfall, "tid": tid, "falls": falls,
            "skal": None, "tic_drift_pct": 0.0, "t_hit": 10.0, "n_rader": 3,
            "max_steg_u": 10.0, "game_dt_s": 1.0, "wall_dt_s": 1.0,
            "cykel": cykel, "ben": ben}


def build_mini():
    root = HERE / "mini_serie" / "A"
    # c001 in_ring: fall vid [200,-700]
    write_jsonl(root / "c001" / "in_ring.jsonl",
                drop_traj(1.0, [200.0, -700.0]))
    (root / "c001" / "in_ring_meta.json").write_text(
        json.dumps(meta(1, "in_ring", "kedjad", "fall_efter_framme", 1)))
    # c001 ut_ring: avsett drop
    write_jsonl(root / "c001" / "ut_ring.jsonl",
                drop_traj(2.0, [180.0, -680.0]))
    (root / "c001" / "ut_ring_meta.json").write_text(
        json.dumps(meta(1, "ut_ring", "kedjad", "framme", 0)))
    # c002 in_ring: fall nära c001 (ska klustras ihop)
    write_jsonl(root / "c002" / "in_ring.jsonl",
                drop_traj(3.0, [210.0, -690.0]))
    (root / "c002" / "in_ring_meta.json").write_text(
        json.dumps(meta(2, "in_ring", "kedjad", "fall_efter_framme", 1)))
    # c003 teleport — filtreras bort under kedjad
    write_jsonl(root / "c003" / "in_ring.jsonl",
                drop_traj(4.0, [205.0, -695.0]))
    (root / "c003" / "in_ring_meta.json").write_text(
        json.dumps(meta(3, "in_ring", "teleport_efter_fel", "fall_efter_framme", 1)))
    # c004 fastnad långt västerut
    write_jsonl(root / "c004" / "in_vast.jsonl", [
        tick(5.0, [-500.0, -700.0, -16.0]),
        tick(5.5, [-501.0, -700.0, -16.0]),
        tick(30.0, [-502.0, -701.0, -16.0]),
    ])
    (root / "c004" / "in_vast_meta.json").write_text(
        json.dumps(meta(4, "in_vast", "kedjad", "fastnad", 0, tid=None)))
    # c005 stämplad fall-cell
    write_jsonl(root / "c005" / "in_ring.jsonl", drop_traj(
        6.0, [50.0, -50.0], extra={"cell_id": 4242,
                                   "graph_contract": "qw-nav-graph/1",
                                   "navmesh_stamp": {"map": "dm3", "cells": 1}}))
    (root / "c005" / "in_ring_meta.json").write_text(
        json.dumps(meta(5, "in_ring", "kedjad", "fall_efter_framme", 1)))
    # extra fall långt bort (okänd cell) så två unknown-härdar finns
    write_jsonl(root / "c006" / "in_tunnel.jsonl",
                drop_traj(7.0, [-480.0, -690.0]))
    (root / "c006" / "in_tunnel_meta.json").write_text(
        json.dumps(meta(6, "in_tunnel", "kedjad", "fall_efter_framme", 1)))
    # c007 in_tunnel: fall NÄRA c001 in_ring — annan rutt, får inte slås ihop
    write_jsonl(root / "c007" / "in_tunnel.jsonl",
                drop_traj(8.0, [205.0, -695.0]))
    (root / "c007" / "in_tunnel_meta.json").write_text(
        json.dumps(meta(7, "in_tunnel", "kedjad", "fall_efter_framme", 1)))
    # B-sida: samma xyz som A/c001/in_ring — annan sida, får inte slås ihop
    broot = HERE / "mini_serie" / "B"
    write_jsonl(broot / "c001" / "in_ring.jsonl",
                drop_traj(9.0, [200.0, -700.0]))
    (broot / "c001" / "in_ring_meta.json").write_text(
        json.dumps(meta(1, "in_ring", "kedjad", "fall_efter_framme", 1)))


def build_stall():
    root = HERE / "stall_serie"
    write_jsonl(root / "stalls.jsonl", [{
        "recorded_at": 1.0,
        "stall": {
            "ev": "bot_stall", "t": 12.5, "cell": 77, "link": 9,
            "reason": "displacement", "origin": [10.0, 20.0, 56.0],
        },
        "audit_tail": [],
    }])


def build_k():
    root = HERE / "k_serie" / "A" / "in_vast"
    write_jsonl(root / "attempt_01.jsonl", [
        tick(1.0, [-593.0, -677.0, -16.0]),
        tick(26.0, [-590.0, -670.0, 40.0]),
    ])
    (root / "summary.json").write_text(json.dumps({
        "fas": "in_vast",
        "forsok": [{"fil": "attempt_01.jsonl", "nr": 1,
                    "utfall": "timeout", "falls": 0, "klipp_s": None}],
    }))


if __name__ == "__main__":
    build_mini()
    build_stall()
    build_k()
    print("fixtures ok")
