#!/usr/bin/env python3
"""hexagon_replant.py — plantera hexagon-korsningslänkarna i ett kört labb.

Länkarna är runtime-only (dör vid kartbyte/omstart) — kör detta efter varje
serverstart innan hexagon-mätning. Geometri från
route-lab/artifacts/nav-patches/dm3-sng-mega-plus-hexagon-20260724-patch.json,
med sod_tur-avstampet centrerat i mynningskorridoren y[-210,-172] (mätt
2026-07-26: spec-avstampet -201 gav sydlobsfall, -191 gav 10/10).

Mätläge 2026-07-26 (meganav+telemetri-bygget, 7s paus mellan försök):
  sod_tur   10/10  (fungerande receptet)
  sod_retur  0/6   fell  — 176u runway från öststart räcker inte till v_req 445
  nor_tur    0/6   detour — länk i rutt, avbryter vid avstampet; odiagnostiserad
  nor_retur  0/8   blandat
Straffcykeln: utan paus mellan försök alternerar pass/detour — vänta >=7 s.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fasttrack"))
import fasttrack.core as core  # noqa: E402

LINKS = [
    ("sod_tur",   "352 -192 56 440 -191 56 733 -215 56 445"),
    ("sod_retur", "768 -192 56 704 -209 56 407 -193 56 445"),
    ("nor_tur",   "352 128 56 440 133 56 733 150 56 445"),
    ("nor_retur", "832 128 56 750 139 56 444 144 56 450"),
]


def main() -> None:
    c = core.Control()
    for name, args in LINKS:
        r = c.request("planlink " + args)["data"]
        print(f'{name}: länk {r["link"]} cost {r["cost"]:.2f}')
    c.close()


if __name__ == "__main__":
    main()
