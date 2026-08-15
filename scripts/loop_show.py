#!/usr/bin/env python3
"""loop_show.py — uppvisningsläge: tre bottar loopar de fixade dm3-rutterna.

Roller (efter stigande ent-id på servern):
  MEGA — varannan runda från SNG-deckssidan (-473,514,120), varannan från
         lifts-hållet (-928,608,120), mål megan (-720,80,160).
  HEX  — hexagonhoppet söder tur: (176,-192,56) -> (880,-200,56); 7 s paus
         mellan varven (straffhygien — tätare ger pass/detour-alternering).
  RA   — golvet (464,-488,56) -> RA-toppen (256,-704,328); re-goto vid för
         tidig finish-plane-arrival tills botten står i boxen.

Kör tills den dödas. En rad per fullbordat varv i loggen. Planterar
hexagonlänkarna vid start och efter serveromstart (speltiden backar).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fasttrack"))
import fasttrack.core as core  # noqa: E402

MEGA_STARTS = [(-473, 514, 120), (-928, 608, 120)]  # SNG-sidan, lifts-sidan
MEGA_TGT = (-720, 80, 160)
HEX_START = (176, -192, 56)
HEX_TGT = (880, -200, 56)
RA_START = (464, -488, 56)
# Tvåsteg: först till hopp-källcellen på rampens slut (rutt utan hopplänk =>
# hoppkedjan bromsar in mot ruttslutet i stället för att bära 450+ ups förbi
# svängen, vilket den gör i trebotsläget), sedan kort goto upp på RA-platån.
RA_VIA = (96, -568, 296)
RA_TGT = (256, -704, 328)

HEX_LINKS = [
    "352 -192 56 440 -191 56 733 -215 56 445",
    "768 -192 56 704 -209 56 407 -193 56 445",
    "352 128 56 440 133 56 733 150 56 445",
    "832 128 56 750 139 56 444 144 56 450",
]


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def setup(c: core.Control) -> list[int]:
    c.request("set rtx_telemetry 1")
    c.request("set rtx_bot_count 3")
    bots: list[int] = []
    for _ in range(20):
        bots = sorted(int(b["ent"]) for b in c.request("status")["data"].get("bots", []))
        if len(bots) >= 3:
            break
        time.sleep(2)
    for args in HEX_LINKS:
        c.request("planlink " + args)
    log(f"setup: bottar {bots}, hexagonlänkar planterade")
    return bots


def teleport_goto(c, bot, start, tgt):
    c.request(f"stop {bot}")
    c.request(f"hold {bot}")
    c.request(f"teleport {bot} {start[0]:g} {start[1]:g} {start[2]:g}")
    # kort sättning; goto:t skickas från huvudloopen en poll senare
    return {"phase": "settle", "until": time.monotonic() + 1.0, "tgt": tgt}


def main() -> None:
    while True:
        try:
            c = core.Control("127.0.0.1", 27980, timeout=15)
            bots = setup(c)
            mega, hexb, ra = bots[0], bots[1], bots[2]
            roles = {
                mega: {"name": "MEGA", "iter": 0, "timeout": 20.0, "pause": 2.5},
                hexb: {"name": "HEX", "iter": 0, "timeout": 10.0, "pause": 7.0},
                ra: {"name": "RA", "iter": 0, "timeout": 30.0, "pause": 2.5},
            }
            state: dict[int, dict] = {}

            def begin(bot):
                r = roles[bot]
                if bot == mega:
                    start = MEGA_STARTS[r["iter"] % 2]
                    legs = [MEGA_TGT]
                elif bot == hexb:
                    start, legs = HEX_START, [HEX_TGT]
                else:
                    start, legs = RA_START, [RA_VIA, RA_TGT]
                st = teleport_goto(c, bot, start, legs[0])
                st.update({"regotos": 0, "t0": None, "legs": legs, "leg": 0})
                state[bot] = st

            last_game_time = c.request("status")["data"].get("time", 0.0)
            last_telem = time.monotonic()
            for b in roles:
                begin(b)

            while True:
                now = time.monotonic()
                if now - last_telem >= 10.0:
                    last_telem = now
                    c.request("set rtx_telemetry 1")  # bryggan stänger av vid viewer-frånkoppling
                st = c.request("status")["data"]
                gt = st.get("time", 0.0)
                if gt + 5.0 < last_game_time:
                    raise core.ControlError("servern omstartad (speltiden backade)")
                last_game_time = max(last_game_time, gt)
                pos = {int(b["ent"]): b["origin"] for b in st.get("bots", [])}

                arrived = set()
                for ev in list(c.events):
                    if ev.get("ev") == "arrived":
                        arrived.add(ev.get("bot"))
                c.events.clear()

                for bot, s in list(state.items()):
                    r = roles[bot]
                    if s["phase"] == "settle" and now >= s["until"]:
                        t = s["tgt"]
                        c.request(f"goto {bot} {t[0]:g} {t[1]:g} {t[2]:g}")
                        s["phase"] = "run"
                        if s["t0"] is None:
                            s["t0"] = now  # varvtiden räknas från första benet
                    elif s["phase"] == "run":
                        p = pos.get(bot)
                        if bot in arrived and p is not None:
                            t = s["tgt"]
                            in_box = abs(p[0] - t[0]) < 70 and abs(p[1] - t[1]) < 70
                            if in_box or s["regotos"] >= 6:
                                if s["leg"] + 1 < len(s["legs"]):
                                    # Fullstopp mellan benen (hexagon_gate-mönstret): ben 2 ruttas
                                    # från stillastående så avstampet sker som i drillen — het
                                    # inrullning gav ett lågfartshopp rakt ner i skarven.
                                    s["leg"] += 1
                                    s["tgt"] = s["legs"][s["leg"]]
                                    s["regotos"] = 0
                                    c.request(f"stop {bot}")
                                    c.request(f"hold {bot}")
                                    # snäpp till exakta via-punkten (<=20u, osynligt): utan den
                                    # står botten på grannecellen och hoppet avgår från skirten
                                    v = s["legs"][s["leg"] - 1]
                                    c.request(f"teleport {bot} {v[0]:g} {v[1]:g} {v[2]:g}")
                                    s["phase"] = "settle"
                                    s["until"] = now + 0.8
                                else:
                                    el = now - s["t0"]
                                    r["iter"] += 1
                                    log(f'{r["name"]} varv {r["iter"]} klart {el:.1f}s'
                                        + ("" if in_box else " (utanför box)"))
                                    s["phase"] = "pause"
                                    s["until"] = now + r["pause"]
                            else:
                                s["regotos"] += 1
                                c.request(f"goto {bot} {t[0]:g} {t[1]:g} {t[2]:g}")
                        elif now - s["t0"] > r["timeout"]:
                            r["iter"] += 1
                            log(f'{r["name"]} varv {r["iter"]} TIMEOUT')
                            s["phase"] = "pause"
                            s["until"] = now + r["pause"]
                    elif s["phase"] == "pause" and now >= s["until"]:
                        begin(bot)

                time.sleep(0.15)
        except (core.ControlError, OSError) as e:
            log(f"anslutning tappad ({e}); återansluter om 5 s")
            try:
                c.close()
            except Exception:
                pass
            time.sleep(5)


if __name__ == "__main__":
    main()
