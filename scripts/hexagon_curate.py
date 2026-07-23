#!/usr/bin/env python3
"""Geometri-baserad kuration av hexagonskålarna på dm3 — körs efter varje
serveromstart (länk-ID:n är INTE stabila över boots; numeriska removes i
patchen träffar fel länkar — bevisat 2026-07-23 kväll).

Tar bort, per skål (södra y[-352,-32], norra y[32,352], x[320,768]):
  1. Skål-drops: nativa speedjumps golvnivå (src z>0) -> grop (tgt z<0).
  2. Trasiga nativa korsningar: speedjumps golv->golv vars segment korsar
     mynningen (x 500-656) — utom våra planterade länkar (id >= plant_min).

Användning: python3 scripts/hexagon_curate.py [plant_min_id]
plant_min_id default 48000 (planterade länkar ligger i slutet av id-rymden;
verifiera mot replant-resultatets faktiska id:n).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fasttrack.core as core  # noqa: E402

BOWLS = ((-352, -31), (32, 353))
X0, X1 = 320, 768
MOUTH = (500.0, 656.0)


def crosses_mouth(o, t) -> bool:
    return min(o[0], t[0]) < MOUTH[0] and max(o[0], t[0]) > MOUTH[1]


def main() -> None:
    plant_min = int(sys.argv[1]) if len(sys.argv) > 1 else 48000
    c = core.Control()
    removed = []
    try:
        seen = set()
        for x in range(X0, X1 + 1, 32):
            for ys, ye in BOWLS:
                for y in range(ys, ye, 32):
                    try:
                        d = c.request(f"cell {x} {y} 56", timeout=5.0).get("data") or {}
                    except core.ControlError:
                        continue
                    cid = d.get("cell")
                    if cid is None or cid in seen:
                        continue
                    seen.add(cid)
                    o = d.get("origin") or [0, 0, 0]
                    if o[2] < 0:
                        continue
                    for link in d.get("out") or []:
                        if link.get("kind") != "speedjump":
                            continue
                        li = link["link"]
                        if li >= plant_min:
                            continue
                        t = link.get("to")
                        in_bowl_band = any(lo <= t[1] <= hi for lo, hi in ((-352, -32), (32, 352)))
                        drop = t[2] < 0 and X0 <= t[0] <= X1 and in_bowl_band
                        crossing = t[2] > 0 and crosses_mouth(o, t)
                        if drop or crossing:
                            try:
                                c.request(f"unlink {li}")
                                removed.append((li, "drop" if drop else "crossing",
                                                tuple(round(v) for v in o),
                                                tuple(round(v) for v in t)))
                            except core.ControlError as exc:
                                print(f"unlink {li} FEL: {exc}")
        for row in removed:
            print(row)
        print(f"KURERAT: {len(removed)} länkar bort "
              f"({sum(1 for r in removed if r[1] == 'drop')} drops, "
              f"{sum(1 for r in removed if r[1] == 'crossing')} korsningar)")
    finally:
        c.close()


if __name__ == "__main__":
    main()
