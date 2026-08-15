#!/usr/bin/env python3
"""match_snapshot.py — följ en labbmatch och skriv ett snapshot-underlag.

Pollar `status` @10 Hz (fart/positioner, 100 ms-upplösning) och `items` @2 Hz
(quad/pent-cykler), och fångar `bot_stall`-events som trillar in på samma
koppling. Efter `--secs` skrivs en JSON med:

  stats:  quad/pent tagna + medelliggtid (spawn -> taget), snittfart 1 s,
          snittfart 100 ms, stillastående s per bot (fart < 16, levande)
  stalls: per cell {n, reasons, phases:{freeplay}, speeds, links, samples}

Körs mot live-proxyn (27980). Bounded, single-connection, påverkar inte spelet.
"""
import argparse
import json
import math
import sys
import time

sys.path.insert(0, "/home/xerial/projects/quakeworld/qw-fasttrack")
sys.path.insert(0, "/home/xerial/projects/quakeworld/qw-fasttrack/fasttrack")
from fasttrack import core

QUAD = (952.0, 296.0, 56.0)
PENT = (1008.0, 800.0, -296.0)
NOLINK = 4294967295

ap = argparse.ArgumentParser()
ap.add_argument("--secs", type=int, default=600)
ap.add_argument("--out", required=True)
ap.add_argument("--label", required=True)
ap.add_argument("--branch", required=True)
ap.add_argument("--build", required=True)
ap.add_argument("--run", type=int, default=None,
                help="löpnummer; default: nästa ur evidence/snapshots/runseq")
args = ap.parse_args()

# Monotont löpnummer över alla runs, oavsett datum — så två körningar samma dag
# alltid går att ordna. Räknaren bor bredvid arkivet och stegas atomiskt nog
# för en-writer-bruket här (en följare per labb).
RUNSEQ = "/home/xerial/.local/share/qw-fasttrack/evidence/snapshots/runseq"
if args.run is None:
    try:
        current = int(open(RUNSEQ).read().strip())
    except (FileNotFoundError, ValueError):
        current = 0
    args.run = current + 1
    import os
    os.makedirs(os.path.dirname(RUNSEQ), exist_ok=True)
    open(RUNSEQ, "w").write(str(args.run))

c = core.Control("127.0.0.1", 27980, timeout=20)
c.request("set rtx_telemetry 1")
last_telemetry_assert = time.time()


def find_item(items, pos):
    for i in items:
        o = i["origin"]
        if abs(o[0] - pos[0]) < 8 and abs(o[1] - pos[1]) < 8:
            return i
    return None


speed_samples = []            # per 100 ms-poll: list of alive bot speeds
per_second = []               # per bot displacement per second
still_s = 0.0                 # summed alive-bot seconds under 16 ups
bot_prev = {}                 # ent -> (origin, wall)
sec_acc = {}                  # ent -> [dist, samples]
powerups = {"quad": {"pos": QUAD, "takes": [], "avail_since": None},
            "pent": {"pos": PENT, "takes": [], "avail_since": None}}
stalls = []

t0 = time.time()
last_items = 0.0
last_sec_flush = t0
n_polls = 0

while time.time() - t0 < args.secs:
    loop_t = time.time()
    try:
        st = c.request("status", timeout=8)["data"]
    except Exception:
        time.sleep(0.5)
        continue
    n_polls += 1
    alive_speeds = []
    for b in st["bots"]:
        ent = b["ent"]
        o = b["origin"]
        prev = bot_prev.get(ent)
        if b.get("alive"):
            if prev is not None:
                dt = loop_t - prev[1]
                if 0.01 < dt < 0.6:
                    v = math.hypot(o[0] - prev[0][0], o[1] - prev[0][1]) / dt
                    if v < 1500:
                        alive_speeds.append(v)
                        acc = sec_acc.setdefault(ent, [0.0, 0])
                        acc[0] += v * dt
                        acc[1] += 1
                        if v < 16:
                            still_s += dt
        bot_prev[ent] = (o, loop_t)
    if alive_speeds:
        speed_samples.extend(alive_speeds)
    if loop_t - last_sec_flush >= 1.0:
        for ent, (dist, ns) in sec_acc.items():
            if ns:
                per_second.append(dist / (loop_t - last_sec_flush))
        sec_acc = {}
        last_sec_flush = loop_t

    if loop_t - last_items >= 0.5:
        last_items = loop_t
        try:
            items = c.request("items", timeout=8)["data"]
            for name, p in powerups.items():
                it = find_item(items, p["pos"])
                if it is None:
                    continue
                if it["available"]:
                    if p["avail_since"] is None:
                        p["avail_since"] = loop_t
                else:
                    if p["avail_since"] is not None:
                        p["takes"].append(round(loop_t - p["avail_since"], 1))
                        p["avail_since"] = None
        except Exception:
            pass

    # Live-bryggan stänger av rtx_telemetry när dess sista viewer kopplar ner
    # (live_bridge.py) — håll den på under hela fångsten, annars tystnar
    # bot_stall mitt i matchen och nollan ser ut som ett resultat.
    if loop_t - last_telemetry_assert >= 10.0:
        last_telemetry_assert = loop_t
        try:
            c.request("set rtx_telemetry 1", timeout=4)
        except Exception:
            pass

    # drain broadcast events collected on this connection
    for ev in c.events:
        if ev.get("ev") == "bot_stall":
            stalls.append(ev)
    c.events.clear()

    time.sleep(max(0.0, 0.1 - (time.time() - loop_t)))

c.close()

# ---- summarize ----
def mean(v):
    return round(sum(v) / len(v), 1) if v else None


elapsed = time.time() - t0
from collections import Counter, defaultdict
cells = defaultdict(lambda: {"n": 0, "reasons": Counter(), "speeds": [],
                             "links": Counter(), "samples": []})
for ev in stalls:
    cl = cells[ev["cell"]]
    cl["n"] += 1
    cl["reasons"][ev["reason"]] += 1
    cl["speeds"].append(ev["speed"])
    if ev["link"] != NOLINK:
        cl["links"][ev["link"]] += 1
    if len(cl["samples"]) < 3:
        cl["samples"].append({"t": round(ev["t"], 1), "reason": ev["reason"],
                              "speed": round(ev["speed"]), "kind": ev["kind"] or None,
                              "route": f'{ev["route_pos"]}/{ev["route_len"]}',
                              "action": ev["action"], "phase": "freeplay",
                              "bot": ev["bot"]})

out_cells = []
for cid, cl in sorted(cells.items(), key=lambda kv: -kv[1]["n"]):
    sp = sorted(cl["speeds"])
    out_cells.append({
        "cell": cid, "n": cl["n"],
        "reason": cl["reasons"].most_common(1)[0][0],
        "reasons": dict(cl["reasons"]),
        "phases": {"freeplay": cl["n"]},
        "speed_med": round(sp[len(sp) // 2], 1), "speed_max": round(sp[-1], 1),
        "links": dict(cl["links"].most_common(4)),
        "samples": cl["samples"], "before_med": None, "before_slow": None,
    })

nbots = 4
stats = {
    "quad_takes": len(powerups["quad"]["takes"]),
    "quad_lay_avg": mean(powerups["quad"]["takes"]),
    "pent_takes": len(powerups["pent"]["takes"]),
    "pent_lay_avg": mean(powerups["pent"]["takes"]),
    "speed_1s": mean(per_second),
    "speed_100ms": mean(speed_samples),
    "still_s_per_bot": round(still_s / nbots, 1),
    "stall_firings": len(stalls),
    "duration_s": round(elapsed),
    "polls": n_polls,
}

json.dump({"run": args.run, "label": args.label,
           "date": time.strftime("%Y-%m-%d"), "time": time.strftime("%H:%M"),
           "branch": args.branch, "build": args.build,
           "stats": stats, "cells": out_cells}, open(args.out, "w"),
          separators=(",", ":"))
print("run #", args.run)
print(json.dumps(stats, indent=1))
print("celler:", len(out_cells), "->", args.out)
