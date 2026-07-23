#!/usr/bin/env python3
"""Ägarprotokollet SNG-spawns→mega via ra_trial-verbets sng_mega-scenarier.

Användning (WSL, cwd = qw-fasttrack):
    python3 -u scripts/mega_gate.py <bot> [jsonl]

Protokoll (ägarens ord 2026-07-23):
  1. INITIAL: nå megan 5 ggr i rad (completion, alternerande spawn W/S).
  2. CHASE: korta tiden — ett försök som slår spawnens baseline blir kandidat.
  3. CONFIRM: ta samma tid (kandidat + 0.05 s slack) 5 ggr i rad på den
     spawnen ⇒ ny baseline; tillbaka till CHASE.
  4. 30 misslyckade försök i rad (globalt, båda spawnsen) ⇒ stopp, senaste
     5/5-baseline per spawn är resultatet.

Spawnsen alternerar i CHASE (W,S,W,S,...); CONFIRM låser till sin spawn tills
5/5 eller tills globala failräknaren når 30. Baseline per spawn eftersom
rutterna har olika längd. Varje försök = JSONL-rad (utan samples).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fasttrack.core as core  # noqa: E402

MAX_SECS = 20.0
PAUSE_S = 1.0
CONFIRM_SLACK = 0.05
BEAT_EPS = 0.01
FAIL_LIMIT = 30
STREAK = 5
INITIAL_MAX_ATTEMPTS = 60
SCENARIOS = ("sng_mega_w", "sng_mega_s")


def run_one(c: core.Control, bot: int, scenario: str) -> dict:
    c.events.clear()
    ack = c.request(f"ra_trial {bot} {scenario} {MAX_SECS:g}", timeout=10.0)
    if not ack.get("ok"):
        return {"ok": False, "reason": f"ack_error: {ack.get('error')}"}
    deadline = time.monotonic() + MAX_SECS + 10.0
    while time.monotonic() < deadline:
        # Billig poll håller socketen läst; stora result-event kan blockera
        # kanalen i sekunder — generös timeout, svälj ControlError.
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


def log_row(out: Path, row: dict) -> None:
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)


def main() -> None:
    bot = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
        "~/.local/share/qw-fasttrack/evidence/mega-gate.jsonl").expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    c = core.Control()
    attempt = 0
    try:
        # --- Fas 1: completion 5/5, alternerande ---
        streak = 0
        streak_times: dict[str, list[float]] = {s: [] for s in SCENARIOS}
        while streak < STREAK:
            if attempt >= INITIAL_MAX_ATTEMPTS:
                log_row(out, {"PHASE1": "FAIL", "attempts": attempt})
                sys.exit(1)
            scen = SCENARIOS[attempt % 2]
            attempt += 1
            ev = run_one(c, bot, scen)
            ok = bool(ev.get("ok"))
            elapsed = ev.get("elapsed")
            if ok:
                streak += 1
                streak_times[scen].append(elapsed)
            else:
                streak = 0
                streak_times = {s: [] for s in SCENARIOS}
            log_row(out, {"ts": time.time(), "phase": "complete", "attempt": attempt,
                          "scenario": scen, "pass": ok, "elapsed": elapsed,
                          "reason": ev.get("reason"), "waypoint_done": ev.get("waypoint_done"),
                          "wall_contacts": ev.get("wall_contacts"),
                          "peak_speed": ev.get("peak_speed"), "streak": streak})
            time.sleep(PAUSE_S)

        # Baseline per spawn = långsammaste tiden i den lyckade streaken
        # (bevisat 5/5-bar nivå). Alternering garanterar >=2 per spawn.
        baseline = {s: (max(ts) if ts else MAX_SECS) for s, ts in streak_times.items()}
        log_row(out, {"PHASE1": "PASS", "attempts": attempt, "baseline": baseline})

        # --- Fas 2/3: chase + confirm tills 30 raka missar ---
        fails = 0
        confirm: dict | None = None  # {"scenario","target","streak"}
        alt = 0
        while fails < FAIL_LIMIT:
            if confirm is not None:
                scen = confirm["scenario"]
            else:
                scen = SCENARIOS[alt % 2]
                alt += 1
            attempt += 1
            ev = run_one(c, bot, scen)
            ok = bool(ev.get("ok"))
            elapsed = ev.get("elapsed")
            if confirm is not None:
                passed = ok and elapsed is not None and elapsed <= confirm["target"]
                mode = "confirm"
                target = confirm["target"]
            else:
                passed = ok and elapsed is not None and elapsed < baseline[scen] - BEAT_EPS
                mode = "chase"
                target = baseline[scen] - BEAT_EPS
            fails = 0 if passed else fails + 1
            row = {"ts": time.time(), "phase": mode, "attempt": attempt,
                   "scenario": scen, "pass": passed, "elapsed": elapsed,
                   "target": round(target, 3), "reason": ev.get("reason"),
                   "waypoint_done": ev.get("waypoint_done"),
                   "wall_contacts": ev.get("wall_contacts"),
                   "peak_speed": ev.get("peak_speed"), "fails_in_row": fails}
            if confirm is not None:
                confirm["streak"] = confirm["streak"] + 1 if passed else 0
                row["confirm_streak"] = confirm["streak"]
                if confirm["streak"] >= STREAK:
                    baseline[scen] = confirm["target"]
                    row["NEW_BASELINE"] = {scen: confirm["target"]}
                    confirm = None
            elif passed:
                confirm = {"scenario": scen,
                           "target": round(elapsed + CONFIRM_SLACK, 3), "streak": 0}
                row["CANDIDATE"] = confirm["target"]
            log_row(out, row)
            time.sleep(PAUSE_S)

        log_row(out, {"DONE": "30_fails_in_row", "attempts": attempt,
                      "final_baseline": baseline})
        sys.exit(0)
    finally:
        c.close()


if __name__ == "__main__":
    main()
