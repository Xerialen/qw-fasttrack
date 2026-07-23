#!/usr/bin/env python3
"""Följ människan i live-frames tills hen stannar — glesa events på stdout.

Användning (via Monitor eller direkt i WSL):
    python3 scripts/follow_live.py [ws-port]

Emitterar EN rad per händelse (Monitor-vänligt):
  - ZON: <närmsta dm3-spawns-markör> när spelaren byter område
  - NY MESH-LUCKA: from -> to när en genuint ny missing-traversal dyker upp
  - STANNAT ... när spelaren varit stilla >6 s efter att ha rört sig (exit)

Seedar sett-mängden från aktörens NUVARANDE missing-lista innan rapportering
startar, så gamla luckor från tidigare i sessionen inte dumpas som "nya" vid
start (lärdom 2026-07-23: utan seeden flödar hela backloggen ut på första
framen)."""
import base64, json, math, os, socket, struct, sys, time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8093
OVL = '/mnt/c/Users/benya/projects/quakeworld/route-lab/qw-nav-viewer/overlays'
markers = json.load(open(f'{OVL}/dm3-spawns.json'))['markers']


def near_label(pos):
    best, bd = None, 1e18
    for m in markers:
        d = math.dist(pos, m['pos'])
        if d < bd:
            best, bd = m['name'], d
    return f"{best} ({bd:.0f}u)"


def gap_key(link):
    return (round(link["from"][0] / 50), round(link["from"][1] / 50),
            round(link["to"][0] / 50), round(link["to"][1] / 50))


key = base64.b64encode(os.urandom(16)).decode()
s = socket.create_connection(("127.0.0.1", PORT), timeout=30)
s.sendall((f"GET / HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
buf = b""
while b"\r\n\r\n" not in buf:
    buf += s.recv(4096)
buf = buf.split(b"\r\n\r\n", 1)[1]


def read_exact(n):
    global buf
    while len(buf) < n:
        c = s.recv(65536)
        if not c:
            raise ConnectionError("ws stängd")
        buf += c
    out, buf = buf[:n], buf[n:]
    return out


def next_frame():
    while True:
        h = read_exact(2)
        ln = h[1] & 0x7F
        if ln == 126:
            ln = struct.unpack("!H", read_exact(2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", read_exact(8))[0]
        p = read_exact(ln)
        if (h[0] & 0x0F) == 0x1:
            return json.loads(p)


seen_missing = None  # seedas från första framen med människan
label = None
moved = False
still_since = None
last_pos = None
peak_speed = 0.0
new_gaps = 0
t0 = time.time()
print("FOLJER: väntar på rörelse...", flush=True)
while True:
    f = next_frame()
    hum = next((b for b in f["bots"] if b.get("human")), None)
    if hum is None:
        continue
    pos, speed = hum["pos"], hum["speed"]
    peak_speed = max(peak_speed, speed)
    if seen_missing is None:
        seen_missing = {gap_key(l) for l in hum["missing"]["links"]}
        if seen_missing:
            print(f"(seedade {len(seen_missing)} redan kända luckor — rapporterar bara nya)",
                  flush=True)
    for l in hum["missing"]["links"]:
        k = gap_key(l)
        if k not in seen_missing:
            seen_missing.add(k)
            new_gaps += 1
            d = math.dist(l["from"], l["to"])
            print(f"NY MESH-LUCKA: ({l['from'][0]:.0f},{l['from'][1]:.0f},{l['from'][2]:.0f}) -> "
                  f"({l['to'][0]:.0f},{l['to'][1]:.0f},{l['to'][2]:.0f}) {d:.0f}u", flush=True)
    lab = near_label(pos)
    zone = lab.split(" (")[0]
    if label is None or zone != label:
        if label is not None or speed > 5:
            print(f"ZON: {lab} pos=({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f}) fart={speed:.0f}",
                  flush=True)
        label = zone
    if speed > 30:
        moved = True
        still_since = None
        last_pos = pos
    elif moved:
        if last_pos is not None and math.dist(pos, last_pos) < 25:
            if still_since is None:
                still_since = time.time()
            elif time.time() - still_since > 6.0:
                print(f"STANNAT vid {near_label(pos)} pos=({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f}) "
                      f"efter {time.time() - t0:.0f}s, toppfart {peak_speed:.0f} ups, "
                      f"{new_gaps} nya mesh-luckor denna runda", flush=True)
                break
        else:
            last_pos = pos
            still_since = None
