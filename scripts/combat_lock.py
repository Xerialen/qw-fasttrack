#!/usr/bin/env python3
"""combat_lock.py — sekunder en spelare är beskjuten inom sitt POV utan att skjuta tillbaka.

Definition (100 ms-grid, per spelare B):
  1. BESKJUTEN: minst ett damage-event med victim=B, attacker=fiende E, inom
     de senaste WINDOW_MS (skada är den observerbara signalen för "beskjuten").
  2. INOM POV: vinkeln mellan B:s view-yaw och bäringen B->E (senaste angriparen)
     är <= POV_DEG/2 vid tickens tidpunkt (positioner/yaw interpolerade ur
     qw-analyze-strömmen).
  3. SKJUTER INTE TILLBAKA: B har inget eget skott (shots-strömmen) inom
     [t - WINDOW_MS, t + GRACE_MS].
Alla tre uppfyllda => ticken räknas som combat lock (0.1 s).

Indata: qw-analyze -view full -include positions,view <demo> (JSON på stdin
eller --json path). Ut: per spelare {lock_s, under_fire_s, share, episodes>=1s}.
"""
import argparse
import bisect
import json
import math
import sys

WINDOW_MS = 1200
GRACE_MS = 300
POV_DEG = 120.0     # totalt synfält; halva på var sida om yaw
TICK_MS = 100

ap = argparse.ArgumentParser()
ap.add_argument("--json", help="qw-analyze full-JSON (annars stdin)")
ap.add_argument("--out", help="skriv resultat-JSON hit")
args = ap.parse_args()

data = json.load(open(args.json)) if args.json else json.load(sys.stdin)

players = {}
for p in data["streams"]["players"]:
    s = p["pos"]
    players[p["name"]] = {
        "team": p["team"], "t": s["t"], "x": s["x"], "y": s["y"],
        "yaw": s["vya"],
    }

def sample(name, t_ms):
    """Interpolerad (x, y, yaw) vid t_ms, eller None utanför strömmen."""
    p = players[name]
    ts = p["t"]
    i = bisect.bisect_right(ts, t_ms)
    if i <= 0 or i >= len(ts):
        return None
    t0, t1 = ts[i - 1], ts[i]
    k = 0.0 if t1 == t0 else (t_ms - t0) / (t1 - t0)
    x = p["x"][i - 1] + (p["x"][i] - p["x"][i - 1]) * k
    y = p["y"][i - 1] + (p["y"][i] - p["y"][i - 1]) * k
    # yaw interpoleras INTE över wrap; ta närmaste sample
    yaw = p["yaw"][i - 1] if k < 0.5 else p["yaw"][i]
    return x, y, yaw

# damage-events per victim, sorterade
hits = {}
for e in data["damage"]["events"]:
    a, v = e.get("attacker"), e.get("victim")
    if not a or not v or a == v:
        continue
    if a in players and v in players and players[a]["team"] != players[v]["team"]:
        hits.setdefault(v, []).append((e["time"], a))
for v in hits:
    hits[v].sort()

# egna skott per spelare
shots = {}
for s in data["shots"]["shots"]:
    shots.setdefault(s["player"], []).append(s["time"])
for k in shots:
    shots[k].sort()

t_end = max(p["t"][-1] for p in players.values())
result = {}
for name, p in players.items():
    my_hits = hits.get(name, [])
    my_shots = shots.get(name, [])
    hit_times = [h[0] for h in my_hits]
    lock_ms = 0
    fire_ms = 0
    episodes = []
    cur = 0
    for t in range(0, int(t_end), TICK_MS):
        i = bisect.bisect_right(hit_times, t)
        if i == 0 or t - hit_times[i - 1] > WINDOW_MS:
            if cur >= 1000:
                episodes.append(cur / 1000.0)
            cur = 0
            continue
        fire_ms += TICK_MS
        attacker = my_hits[i - 1][1]
        me = sample(name, t)
        en = sample(attacker, t)
        locked = False
        if me and en:
            bearing = math.degrees(math.atan2(en[1] - me[1], en[0] - me[0]))
            d = (bearing - me[2] + 180.0) % 360.0 - 180.0
            if abs(d) <= POV_DEG / 2:
                j = bisect.bisect_left(my_shots, t - WINDOW_MS)
                fired = j < len(my_shots) and my_shots[j] <= t + GRACE_MS
                locked = not fired
        if locked:
            lock_ms += TICK_MS
            cur += TICK_MS
        else:
            if cur >= 1000:
                episodes.append(cur / 1000.0)
            cur = 0
    if cur >= 1000:
        episodes.append(cur / 1000.0)
    result[name] = {
        "team": p["team"],
        "lock_s": round(lock_ms / 1000.0, 1),
        "under_fire_s": round(fire_ms / 1000.0, 1),
        "share": round(lock_ms / fire_ms, 2) if fire_ms else None,
        "episodes_ge_1s": len(episodes),
        "longest_s": round(max(episodes), 1) if episodes else 0.0,
    }

out = {"schema": "combat-lock/1", "window_ms": WINDOW_MS, "grace_ms": GRACE_MS,
       "pov_deg": POV_DEG, "players": result}
if args.out:
    json.dump(out, open(args.out, "w"), separators=(",", ":"))
print(f'{"spelare":14s} {"lag":5s} {"lock s":>7s} {"under eld s":>11s} {"andel":>6s} {"ep>=1s":>7s} {"längst":>7s}')
for n, r in sorted(result.items(), key=lambda kv: -kv[1]["lock_s"]):
    print(f'{n:14s} {r["team"]:5s} {r["lock_s"]:7.1f} {r["under_fire_s"]:11.1f} '
          f'{(str(r["share"]) if r["share"] is not None else "-"):>6s} {r["episodes_ge_1s"]:7d} {r["longest_s"]:6.1f}s')
