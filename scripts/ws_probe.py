#!/usr/bin/env python3
"""Läs N qw-live-frame/1-frames från en producer-websocket och skriv digest.

Användning (WSL):
    python3 scripts/ws_probe.py [N] [port]

N = antal frames (default 5). port = producerns ws-port (default 8093 =
live-bryggan; 8095 = replay-uniten). Digest per aktör: ent/human/name/pos/
speed/cell_id + storlek på used/missing. Sista raden räknar unika (ent,pos)
över de lästa framesen — 0 betyder att inget rör sig.

Säker att köra när som helst: websocket-lyssnare stör ALDRIG kontrollkanalen
(27980 har EN svarsläsare — bryggan; se runbooken)."""
import base64, json, math, os, socket, struct, sys

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8093
HOST = "127.0.0.1"

key = base64.b64encode(os.urandom(16)).decode()
s = socket.create_connection((HOST, PORT), timeout=15)
s.sendall((f"GET / HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nUpgrade: websocket\r\n"
           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
           f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
buf = b""
while b"\r\n\r\n" not in buf:
    buf += s.recv(4096)
buf = buf.split(b"\r\n\r\n", 1)[1]


def read_exact(n):
    global buf
    while len(buf) < n:
        chunk = s.recv(65536)
        if not chunk:
            raise ConnectionError("ws stängd")
        buf += chunk
    out, buf = buf[:n], buf[n:]
    return out


frames = []
while len(frames) < N:
    h = read_exact(2)
    ln = h[1] & 0x7F
    if ln == 126:
        ln = struct.unpack("!H", read_exact(2))[0]
    elif ln == 127:
        ln = struct.unpack("!Q", read_exact(8))[0]
    payload = read_exact(ln)
    if (h[0] & 0x0F) == 0x1:
        frames.append(json.loads(payload))
s.close()

last = frames[-1]
print("schema:", last["schema"], "seq:", last["seq"],
      "graph:", last["graph"]["name"], last["graph"]["sha256"])
for a in last["bots"]:
    print(json.dumps({k: a.get(k) for k in ("ent", "human", "name", "pos", "speed", "cell_id")}))
    print("  used_cells:", len(a["used"]["cells"]), "used_links:", len(a["used"]["links"]),
          "missing_cells:", len(a["missing"]["cells"]), "missing_links:", len(a["missing"]["links"]))
moved = set()
for f in frames:
    for a in f["bots"]:
        moved.add((a["ent"], tuple(round(v) for v in a["pos"])))
print("unika (ent,pos) över", len(frames), "frames:", len(moved))
