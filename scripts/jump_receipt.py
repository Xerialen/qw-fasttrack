"""Live-kvittera hopp ur pmove-JSONL:en (tail -f-stil). En rad per hopp >=150u."""
import json, math, sys, time

PATH = '/home/xerial/.local/share/qw-fasttrack/evidence/pmove-session-2026-07-23.jsonl'
MIN_DIST, MIN_AIR = 150.0, 0.3

f = open(PATH, encoding='utf-8')
f.seek(0, 2)  # bara nya rader
state = {}  # ent -> {last_ground, air_since, takeoff, takeoff_speed}
n = 0
print('ARMERAD: hoppar du nu sa kvitteras varje hopp >=150u har', flush=True)
while True:
    line = f.readline()
    if not line:
        time.sleep(0.05)
        continue
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        continue
    ent = r['ent']
    s = state.setdefault(ent, {'ground': None, 'air_t': None, 'takeoff': None, 'speed': 0.0})
    if r['on_ground']:
        if s['air_t'] is not None and s['takeoff'] is not None:
            air = r['t'] - s['air_t']
            dist = math.dist(s['takeoff'], r['origin'])
            step_ok = dist < 700  # tele-diskriminator pa segmentniva
            if air >= MIN_AIR and dist >= MIN_DIST:
                n += 1
                tag = 'HOPP' if step_ok else 'TELE?'
                print(f"{tag} {n}: ({s['takeoff'][0]:.0f},{s['takeoff'][1]:.0f},{s['takeoff'][2]:.0f}) -> "
                      f"({r['origin'][0]:.0f},{r['origin'][1]:.0f},{r['origin'][2]:.0f})  "
                      f"{dist:.0f}u  luft {air:.2f}s  avstamp {s['speed']:.0f} ups", flush=True)
        s['ground'] = r['origin']
        s['air_t'] = None
        s['takeoff'] = None
        s['speed'] = math.hypot(r['vel'][0], r['vel'][1])
    else:
        if s['air_t'] is None:
            s['air_t'] = r['t']
            s['takeoff'] = s['ground']
            # speed behalls fran sista mark-samplet
