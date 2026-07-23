#!/usr/bin/env python3
"""Ägarprotokollet hexagonhoppen: 5/5 per riktning, sen båda i sekvens, per skål.

Användning (WSL, cwd = qw-fasttrack):
    python3 -u scripts/hexagon_gate.py <bot> <mode> [n] [jsonl]

mode: sod_tur | sod_retur | sod_seq | nor_tur | nor_retur | nor_seq
n:    antal lyckade i rad som krävs (default 5); n=1 = snabb rök-koll.

Pass-kriteriet är HÅRDARE än arrive_box: varje ben måste dessutom
  1. ha minst ett luftburet sample över skålmynningen (bevisar korsning,
     utesluter omvägen runt skålen), och
  2. aldrig sjunka under z_floor-marginalen (utesluter fall ner i gropen).
Sekvensläget kör tur+retur i ETT försök utan teleport emellan; båda benen
måste klara båda kriterierna.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fasttrack.core as core  # noqa: E402

POLL_HZ = 15.0
SETTLE_S = 1.0
MAX_LEG_S = 7.0
PAUSE_S = 1.0
FALL_Z = 20.0          # golv-origin är 56; under detta = på väg ner i gropen
MOUTH_X = (500.0, 652.0)  # skålmynningen (ingen golvcell där)
MOUTH_HALF_Y = 130.0
AIR_MIN_Z = 40.0

# Per skål: crossline-y, väststart, öststart, boxhalvor
BOWLS = {
    "sod": {"y": -200.0, "west": [176.0, -192.0, 56.0], "east": [880.0, -200.0, 56.0]},
    "nor": {"y": 132.0, "west": [176.0, 132.0, 56.0], "east": [880.0, 132.0, 56.0]},
}
BOX_HALF = [90.0, 110.0, 60.0]


def box_around(p: list[float]) -> list[float]:
    return [p[0] - BOX_HALF[0], p[1] - BOX_HALF[1], p[2] - BOX_HALF[2],
            p[0] + BOX_HALF[0], p[1] + BOX_HALF[1], p[2] + BOX_HALF[2]]


def inside(p: list[float], b: list[float]) -> bool:
    return b[0] <= p[0] <= b[3] and b[1] <= p[1] <= b[4] and b[2] <= p[2] <= b[5]


def bot_state(status: dict, bot: int) -> dict | None:
    return next((e for e in status.get("bots", []) if int(e.get("ent", -1)) == bot), None)


def run_leg(c: core.Control, bot: int, target: list[float], bowl_y: float,
            max_s: float = MAX_LEG_S) -> dict:
    """goto target; följ 15 Hz-samples tills box/fall/timeout. Returnerar klassning."""
    box = box_around(target)
    sent = time.monotonic()
    c.request(f"goto {bot} {target[0]:g} {target[1]:g} {target[2]:g}")
    crossed_air = False
    min_z = 1e9
    samples = 0
    trace: list[tuple] = []
    while time.monotonic() - sent < max_s:
        t0 = time.monotonic()
        try:
            st = c.request("status", timeout=2.0)["data"]
        except core.ControlError:
            break
        e = bot_state(st, bot)
        if e is None or not e.get("alive"):
            return {"leg": "died", "elapsed": None, "crossed_air": crossed_air,
                    "min_z": min_z, "samples": samples, "trace": trace}
        p = [float(v) for v in e["origin"]]
        samples += 1
        trace.append((round(p[0]), round(p[1]), round(p[2]), round(e.get("speed", 0))))
        min_z = min(min_z, p[2])
        if (MOUTH_X[0] < p[0] < MOUTH_X[1] and abs(p[1] - bowl_y) < MOUTH_HALF_Y
                and p[2] > AIR_MIN_Z and not e.get("on_ground")):
            crossed_air = True
        if p[2] < FALL_Z and MOUTH_X[0] - 40 < p[0] < MOUTH_X[1] + 40:
            return {"leg": "fell", "elapsed": None, "crossed_air": crossed_air,
                    "min_z": min_z, "samples": samples, "trace": trace}
        if inside(p, box):
            el = time.monotonic() - sent
            verdict = "passed" if crossed_air else "detoured"
            return {"leg": verdict, "elapsed": round(el, 3), "crossed_air": crossed_air,
                    "min_z": round(min_z, 1), "samples": samples}
        time.sleep(max(0.0, 1.0 / POLL_HZ - (time.monotonic() - t0)))
    return {"leg": "timeout", "elapsed": None, "crossed_air": crossed_air,
            "min_z": round(min_z, 1), "samples": samples, "trace": trace}


def attempt(c: core.Control, bot: int, bowl: dict, legs: list[tuple[list[float], list[float]]]) -> dict:
    """legs = [(startteleport|None, target)]; teleport bara före första benet."""
    start = legs[0][0]
    c.request(f"stop {bot}")
    c.request(f"hold {bot}")
    c.request(f"teleport {bot} {start[0]:g} {start[1]:g} {start[2]:g}")
    time.sleep(SETTLE_S)
    # Straffhygien: starta aldrig ett försök med aktiva straff — routern skulle
    # välja omvägar/trasiga alternativ och mäta fel sak.
    for _ in range(24):
        pen = (c.request(f"penalties {bot}").get("data")) or []
        if not pen:
            break
        time.sleep(0.5)
    st = c.request("status")["data"]
    e = bot_state(st, bot)
    if e is None:
        return {"ok": False, "reason": "no_bot"}
    p = [float(v) for v in e["origin"]]
    if abs(p[0] - start[0]) > 24 or abs(p[1] - start[1]) > 24:
        return {"ok": False, "reason": "setup_failed", "at": p}
    results = []
    for i, (_, target) in enumerate(legs):
        if i > 0:
            # Fullstopp mellan benen: ben 2 ruttas från stillastående så
            # exekutorn engagerar returlänken från sin riktiga startbana
            # (het inrullning off-line triggar past-lip-commit mot gropen).
            c.request(f"stop {bot}")
            c.request(f"hold {bot}")
            time.sleep(0.7)
        r = run_leg(c, bot, target, bowl["y"])
        results.append(r)
        if r["leg"] != "passed":
            return {"ok": False, "reason": r["leg"], "legs": results}
    return {"ok": True, "reason": None, "legs": results,
            "elapsed": round(sum(r["elapsed"] for r in results), 3)}


def main() -> None:
    bot = int(sys.argv[1])
    mode = sys.argv[2]
    need = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    out = Path(sys.argv[4]) if len(sys.argv) > 4 else Path(
        f"~/.local/share/qw-fasttrack/evidence/hexagon-{mode}.jsonl").expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    side, kind = mode.split("_", 1)
    bowl = BOWLS[side]
    W, E = bowl["west"], bowl["east"]
    if kind == "tur":
        legs = [(W, E)]
    elif kind == "retur":
        legs = [(E, W)]
    elif kind == "seq":
        legs = [(W, E), (None, W)]
    else:
        raise SystemExit(f"okänt mode {mode}")

    c = core.Control()
    streak = 0
    attempt_no = 0
    cap = max(need * 12, 30)
    try:
        while streak < need and attempt_no < cap:
            attempt_no += 1
            r = attempt(c, bot, bowl, legs)
            streak = streak + 1 if r.get("ok") else 0
            row = {"ts": time.time(), "mode": mode, "attempt": attempt_no,
                   "streak": streak, **r}
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            print(json.dumps(row), flush=True)
            time.sleep(PAUSE_S)
        final = {"MODE": mode, "RESULT": "PASS" if streak >= need else "FAIL",
                 "attempts": attempt_no, "streak": streak, "need": need}
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(final) + "\n")
        print(json.dumps(final), flush=True)
        sys.exit(0 if streak >= need else 1)
    finally:
        c.close()


if __name__ == "__main__":
    main()
