#!/usr/bin/env python3
"""goal_drills.py — mätdrillar för ägarmålen RA-klättring och SNG-mega.

Användning (cwd = qw-fasttrack):
    python3 -u scripts/goal_drills.py ra   <n> [jsonl]
    python3 -u scripts/goal_drills.py mega <n> [jsonl]

RA:   teleport golvstart [464,-488,56] -> goto RA-topp [256,-704,304].
      PASS = framme i boxen UTAN fall. Fall = z < 70 efter att ha nått >= 140
      (dvs. trillat av ledge-kedjan tillbaka till golvet). Timeout 30 s.
MEGA: teleport SNG-däck [-473,514,120] -> goto megan [-720,80,160].
      PASS = megan tagen (items-cykel) ELLER framme i boxen. Timeout 20 s.

Klassning per försök: passed | fell | timeout | stall | died | setup_failed.
Varje försök = JSONL-rad (trace utelämnas ur PASS-rader, behålls vid fail).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fasttrack"))
import fasttrack.core as core  # noqa: E402

POLL_HZ = 15.0
SETTLE_S = 1.0
PAUSE_S = 1.0

DRILLS = {
    "ra": {
        "start": [464.0, -488.0, 56.0],
        "target": [256.0, -704.0, 328.0],
        "box_half": [70.0, 70.0, 60.0],
        "max_s": 30.0,
        "fall_after_z": 140.0,   # väl uppe på ledgekedjan ...
        "fall_below_z": 70.0,    # ... räknas retur till golvnivå som fall
        "item": None,
    },
    "mega": {
        "start": [-473.0, 514.0, 120.0],
        "target": [-720.0, 80.0, 160.0],
        "box_half": [90.0, 90.0, 70.0],
        "max_s": 20.0,
        "fall_after_z": None,    # rutten får gå lågt (raketdetouren) — inget z-krav
        "fall_below_z": None,
        "item": [-720.0, 80.0, 160.0],
    },
}


def bot_state(status: dict, bot: int) -> dict | None:
    return next((e for e in status.get("bots", []) if int(e.get("ent", -1)) == bot), None)


def item_available(c: core.Control, pos) -> bool | None:
    try:
        items = c.request("items", timeout=4.0)["data"]
    except core.ControlError:
        return None
    for i in items:
        o = i["origin"]
        if abs(o[0] - pos[0]) < 12 and abs(o[1] - pos[1]) < 12:
            return bool(i["available"])
    return None


def attempt(c: core.Control, bot: int, d: dict) -> dict:
    s, t = d["start"], d["target"]
    c.request(f"stop {bot}")
    c.request(f"hold {bot}")
    c.request(f"teleport {bot} {s[0]:g} {s[1]:g} {s[2]:g}")
    time.sleep(SETTLE_S)
    st = c.request("status")["data"]
    e = bot_state(st, bot)
    if e is None:
        return {"result": "no_bot"}
    p = [float(v) for v in e["origin"]]
    if abs(p[0] - s[0]) > 24 or abs(p[1] - s[1]) > 24:
        return {"result": "setup_failed", "at": p}

    item_was_up = item_available(c, d["item"]) if d["item"] else None
    c.events.clear()
    box = [t[0] - d["box_half"][0], t[1] - d["box_half"][1], t[2] - d["box_half"][2],
           t[0] + d["box_half"][0], t[1] + d["box_half"][1], t[2] + d["box_half"][2]]
    sent = time.monotonic()
    c.request(f"goto {bot} {t[0]:g} {t[1]:g} {t[2]:g}")
    regotos = 0
    z_max = -1e9
    min_z = 1e9
    fell = False
    stalled = False
    trace = []
    last_item_poll = 0.0
    item_taken = False
    while time.monotonic() - sent < d["max_s"]:
        t0 = time.monotonic()
        try:
            st = c.request("status", timeout=3.0)["data"]
        except core.ControlError:
            break
        arrived_ev = False
        for ev in list(c.events):
            if ev.get("ev") == "goto_stall" and ev.get("bot") == bot:
                stalled = True
            if ev.get("ev") == "arrived" and ev.get("bot") == bot:
                arrived_ev = True
        c.events.clear()
        e = bot_state(st, bot)
        if e is None or not e.get("alive"):
            return {"result": "died", "elapsed": None, "min_z": round(min_z, 1),
                    "trace": trace[-40:]}
        p = [float(v) for v in e["origin"]]
        trace.append((round(p[0]), round(p[1]), round(p[2]), round(e.get("speed", 0))))
        z_max = max(z_max, p[2])
        min_z = min(min_z, p[2])
        if (d["fall_after_z"] is not None and z_max >= d["fall_after_z"]
                and p[2] < d["fall_below_z"]):
            fell = True  # notera men fortsätt inte — fall är terminalt fail
            return {"result": "fell", "elapsed": None, "z_max": round(z_max, 1),
                    "at": [round(v) for v in p], "trace": trace[-60:]}
        if d["item"] and t0 - last_item_poll >= 0.5:
            last_item_poll = t0
            up = item_available(c, d["item"])
            if item_was_up and up is False:
                # megan försvann medan vår bot är enda spelaren -> tagen av botten
                item_taken = True
        in_box = (box[0] <= p[0] <= box[3] and box[1] <= p[1] <= box[4]
                  and box[2] <= p[2] <= box[5])
        if in_box or item_taken:
            el = time.monotonic() - sent
            return {"result": "passed", "elapsed": round(el, 2),
                    "item_taken": item_taken, "z_max": round(z_max, 1),
                    "min_z": round(min_z, 1), "regotos": regotos}
        if stalled:
            return {"result": "stall", "elapsed": None, "min_z": round(min_z, 1),
                    "at": [round(v) for v in p], "trace": trace[-60:]}
        if arrived_ev:
            # goto:s finish-plane beviljar arrival för tidigt (t.ex. 128u väster om
            # RA på 328-hyllan) — utanför boxen betyder det "inte framme": kör igen.
            if regotos >= 6:
                return {"result": "regoto_loop", "elapsed": None,
                        "at": [round(v) for v in p], "trace": trace[-60:]}
            regotos += 1
            c.request(f"goto {bot} {t[0]:g} {t[1]:g} {t[2]:g}")
        time.sleep(max(0.0, 1.0 / POLL_HZ - (time.monotonic() - t0)))
    return {"result": "timeout", "elapsed": None, "min_z": round(min_z, 1),
            "z_max": round(z_max, 1), "at": [round(v) for v in p] if trace else None,
            "trace": trace[-60:]}


def main() -> None:
    drill = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(
        f"~/.local/share/qw-fasttrack/evidence/goal-drill-{drill}.jsonl").expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    d = DRILLS[drill]

    c = core.Control()
    st = c.request("status")["data"]
    bots = st.get("bots", [])
    if not bots:
        raise SystemExit("ingen bot på servern")
    bot = int(bots[0]["ent"])

    passed = 0
    for i in range(1, n + 1):
        r = attempt(c, bot, d)
        if r["result"] == "passed":
            passed += 1
            r.pop("trace", None)
        row = {"ts": time.time(), "drill": drill, "attempt": i, "passed_so_far": passed, **r}
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        slim = {k: v for k, v in row.items() if k != "trace"}
        print(json.dumps(slim), flush=True)
        time.sleep(PAUSE_S)
    print(json.dumps({"DRILL": drill, "passed": passed, "of": n}), flush=True)
    c.close()


if __name__ == "__main__":
    main()
