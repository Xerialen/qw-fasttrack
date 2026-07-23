#!/usr/bin/env python3
"""Kör ägargaten RA-tunnel→RA-topp via ra_trial-verbet på fasttrack-riggen.

Användning (WSL, cwd = qw-fasttrack):
    python3 -u scripts/ra_gate.py <bot> <threshold_s> <consecutive> [max_attempts] [jsonl]

Driver `ra_trial <bot> ra_spawn` genom core.Control (proxy-säkert: bryggan
behåller sin kanal, ägaren ser försöken live i viewern). Resultatet kommer
som ra_trial_result-event; vi pollar status tills det dyker upp. Varje
försök loggas som en JSONL-rad (utan samples — de är stora; råeventet
sparas separat vid behov). Exit 0 om streaken nås.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fasttrack.core as core  # noqa: E402

MAX_SECS = 15.0
PAUSE_S = 1.0


def run_one(c: core.Control, bot: int) -> dict:
    c.events.clear()
    ack = c.request(f"ra_trial {bot} ra_spawn {MAX_SECS:g}", timeout=10.0)
    if not ack.get("ok"):
        return {"ok": False, "reason": f"ack_error: {ack.get('error')}"}
    deadline = time.monotonic() + MAX_SECS + 10.0
    while time.monotonic() < deadline:
        # Billig poll håller socketen läst; eventet landar i c.events.
        # Generös timeout: ra_trial_result är stort (upp till 4096 samples)
        # och kan blockera kanalen i sekunder när det levereras.
        try:
            c.request("status", timeout=12.0)
        except core.ControlError:
            pass
        for ev in list(c.events):
            if ev.get("ev") == "ra_trial_result":
                c.events.remove(ev)
                return ev
        time.sleep(0.4)
    return {"ok": False, "reason": "result_event_timeout"}


def main() -> None:
    bot = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    consecutive = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    max_attempts = int(sys.argv[4]) if len(sys.argv) > 4 else 30
    out = Path(sys.argv[5]) if len(sys.argv) > 5 else Path(
        "~/.local/share/qw-fasttrack/evidence/ra-gate.jsonl").expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    c = core.Control()
    streak = 0
    best = None
    try:
        for attempt in range(1, max_attempts + 1):
            ev = run_one(c, bot)
            elapsed = ev.get("elapsed")
            ok = bool(ev.get("ok")) and elapsed is not None and elapsed <= threshold
            streak = streak + 1 if ok else 0
            if elapsed is not None and ev.get("ok"):
                best = elapsed if best is None else min(best, elapsed)
            row = {
                "ts": time.time(), "attempt": attempt, "pass": ok,
                "elapsed": elapsed, "trial_ok": ev.get("ok"),
                "reason": ev.get("reason"), "wall_contacts": ev.get("wall_contacts"),
                "wall_secs": ev.get("wall_secs"), "peak_speed": ev.get("peak_speed"),
                "terminal": ev.get("terminal"), "streak": streak,
                "threshold": threshold,
            }
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            print(json.dumps(row), flush=True)
            if streak >= consecutive:
                print(json.dumps({"GATE": "PASS", "streak": streak,
                                  "best": best, "attempts": attempt}), flush=True)
                sys.exit(0)
            time.sleep(PAUSE_S)
    finally:
        c.close()
    print(json.dumps({"GATE": "FAIL", "streak_needed": consecutive,
                      "best": best, "attempts": max_attempts}), flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
