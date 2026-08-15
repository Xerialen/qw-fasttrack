#!/usr/bin/env python3
"""suite.py — standardiserad testsvit för rtx-byggen på fasttrack-labbet.

Nivåer (jämför ALDRIG resultat mellan olika nivåer):
  T0  offline-orakel     cargo test i rtx-repot (Nanos sviter, körs vid bygge — inte härifrån)
  T1  rörelsedrillar     deterministiska en-bots-drillar med trösklar (~8 min)
  T2  pacifist-frispel   4 bottar, inga skott, 10 min — ren navigationssignal
  T3  riktig match       4 bottar, skott på, 10 min — strid + navigation

Användning (cwd = qw-fasttrack):
    python3 -u scripts/suite.py t1 [--quick] [--with-dash]
    python3 -u scripts/suite.py t2 [--secs 600] --branch <gren> --build <md5>
    python3 -u scripts/suite.py t3 [--secs 600] --branch <gren> --build <md5>

Resultat: evidence/suite/<datum>-<nivå>-run<N>.json (löpnummer ur samma runseq
som snapshotterna). T2/T3 skriver dessutom snapshot-JSON för artefakten, med
"regime"-fält. Sviten återställer serverns cvars efter sig.

Trösklar (T1): ra 10/10 · mega >=8/10 · hexagon sod_tur >=9/10 ·
724->503 10/10 · 503->194 10/10 · dash-peak >= 800 (informativ, röd under).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fasttrack"))
import fasttrack.core as core  # noqa: E402

EVID = Path("~/.local/share/qw-fasttrack/evidence").expanduser()
RUNSEQ = EVID / "snapshots/runseq"
SUITE_DIR = EVID / "suite"

HEX_LINKS = [
    "352 -192 56 440 -191 56 733 -215 56 445",
    "768 -192 56 704 -209 56 407 -193 56 445",
    "352 128 56 440 133 56 733 150 56 445",
    "832 128 56 750 139 56 444 144 56 450",
]


def next_run() -> int:
    try:
        cur = int(RUNSEQ.read_text().strip())
    except (FileNotFoundError, ValueError):
        cur = 0
    RUNSEQ.parent.mkdir(parents=True, exist_ok=True)
    RUNSEQ.write_text(str(cur + 1))
    return cur + 1


def conn() -> core.Control:
    return core.Control("127.0.0.1", 27980, timeout=20)


def keep_telemetry(c: core.Control) -> None:
    c.request("set rtx_telemetry 1")


def bot_ids(c: core.Control, want: int, timeout_s: float = 40.0) -> list[int]:
    c.request(f"set rtx_bot_count {want}")
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        ids = sorted(int(b["ent"]) for b in c.request("status")["data"].get("bots", []))
        if len(ids) >= want:
            return ids[:want]
        time.sleep(2)
    raise SystemExit(f"fick aldrig {want} bottar")


# --------------------------------------------------------------------- T1
def leg(c, bot, start, tgt, max_s, fall_gate=None, crossing=None, box=70):
    """teleport -> goto -> klassa. fall_gate=(armed_z, fail_z); crossing=(bowl_y)."""
    c.request(f"stop {bot}"); c.request(f"hold {bot}")
    c.request(f"teleport {bot} {start[0]:g} {start[1]:g} {start[2]:g}")
    time.sleep(1.0)
    c.events.clear()
    c.request(f"goto {bot} {tgt[0]:g} {tgt[1]:g} {tgt[2]:g}")
    t0 = time.monotonic(); z_hi = -9e9; regd = 0; crossed = False
    while time.monotonic() - t0 < max_s:
        st = c.request("status")["data"]["bots"]
        b = next((x for x in st if int(x["ent"]) == bot), None)
        if b is None or not b.get("alive"):
            return "died", None
        p = b["origin"]; z_hi = max(z_hi, p[2])
        if fall_gate and z_hi >= fall_gate[0] and p[2] < fall_gate[1]:
            return "fell", None
        if crossing is not None:
            if 500 < p[0] < 652 and abs(p[1] - crossing) < 130 and p[2] > 40 and not b.get("on_ground"):
                crossed = True
            if p[2] < 20 and 460 < p[0] < 692:
                return "fell", None
        arr = any(e.get("ev") == "arrived" for e in c.events)
        stall = any(e.get("ev") == "goto_stall" for e in c.events)
        c.events.clear()
        if stall:
            return "stall", None
        if arr:
            if abs(p[0] - tgt[0]) < box and abs(p[1] - tgt[1]) < box:
                if crossing is not None and not crossed:
                    return "detoured", None
                return "passed", round(time.monotonic() - t0, 2)
            if regd >= 6:
                return "loop", None
            regd += 1
            c.request(f"goto {bot} {tgt[0]:g} {tgt[1]:g} {tgt[2]:g}")
        time.sleep(0.07)
    return "timeout", None


def series(c, bot, name, start, tgt, n, max_s, pause, **kw):
    out = []
    for i in range(n):
        r, el = leg(c, bot, start, tgt, max_s, **kw)
        out.append(r)
        print(f"  {name} {i+1}/{n}: {r}" + (f" {el}s" if el else ""), flush=True)
        time.sleep(pause)
    ok = out.count("passed")
    return {"name": name, "passed": ok, "of": n, "results": out}


def dash_100m(c) -> dict:
    """Byt till 100m.bsp, mät bästa peak av 2 rena dashar, byt tillbaka till dm3.
    Kartbytet dödar kontrollkanalen och fryser boten (känd bugg) — cykla bot_count."""
    peaks = []
    def reconn():
        for _ in range(12):
            try:
                return conn()
            except Exception:
                time.sleep(2)
        raise SystemExit("ingen anslutning efter kartbyte")
    try:
        c.request("runcmd map 100m")
    except core.ControlError:
        pass
    c.close(); time.sleep(5); c = reconn()
    for _ in range(2):
        try:
            c.request("set rtx_bot_count 0"); time.sleep(2)
            c.request("set rtx_bot_count 1")
        except (core.ControlError, OSError):
            pass
        try:
            c.close()
        except Exception:
            pass
        time.sleep(5); c = reconn()
        try:
            ids = bot_ids(c, 1)
            bot = ids[0]
            c.request(f"teleport {bot} -32 -2100 24"); time.sleep(1)
            c.events.clear()
            c.request(f"goto {bot} -32 3500 24")
            t0 = time.monotonic(); vmax = 0.0
            while time.monotonic() - t0 < 16:
                b = c.request("status")["data"]["bots"][0]
                vmax = max(vmax, b.get("speed", 0))
                if any(e.get("ev") in ("arrived", "goto_stall") for e in c.events):
                    break
                c.events.clear()
                time.sleep(0.05)
            peaks.append(round(vmax))
            print(f"  dash peak {round(vmax)}", flush=True)
        except SystemExit:
            print("  dash: bot uteblev, hoppar", flush=True)
    try:
        c.request("runcmd map dm3")
    except core.ControlError:
        pass
    c.close(); time.sleep(6)
    c = reconn()
    bot_ids(c, 1)
    c.close()
    return {"name": "dash_100m", "peaks": peaks, "peak": max(peaks) if peaks else None, "floor": 800}


def run_t1(quick: bool, with_dash: bool) -> None:
    n = 3 if quick else 10
    run = next_run()
    c = conn()
    keep_telemetry(c)
    ids = bot_ids(c, 1)
    bot = ids[0]
    for args in HEX_LINKS:
        c.request("planlink " + args)
    res = []
    res.append(series(c, bot, "ra_klattring", (464, -488, 56), (256, -704, 328), n, 30, 1.0,
                      fall_gate=(140, 70)))
    res.append(series(c, bot, "sng_mega", (-473, 514, 120), (-720, 80, 160), n, 20, 1.0))
    res.append(series(c, bot, "hexagon_sod_tur", (176, -192, 56), (880, -200, 56), n, 9, 7.0,
                      crossing=-200.0, box=90))
    res.append(series(c, bot, "cell_724_503", (-288, 768, -16), (-544, 864, 120), n, 12, 0.5, box=60))
    res.append(series(c, bot, "cell_503_194", (-544, 864, 120), (-800, 96, 184), n, 16, 0.5, box=60))
    c.request(f"stop {bot}"); c.request(f"hold {bot}")
    dash = None
    if with_dash:
        dash = dash_100m(c)
    else:
        c.close()
    thresholds = {"ra_klattring": n, "sng_mega": max(1, round(n * 0.8)),
                  "hexagon_sod_tur": max(1, round(n * 0.9)),
                  "cell_724_503": n, "cell_503_194": n}
    verdicts = {r["name"]: (r["passed"] >= thresholds[r["name"]]) for r in res}
    if dash and dash["peak"] is not None:
        verdicts["dash_100m"] = dash["peak"] >= dash["floor"]
    out = {"schema": "rtx-suite/1", "regime": "T1", "run": run,
           "date": time.strftime("%Y-%m-%d"), "time": time.strftime("%H:%M"),
           "quick": quick, "drills": res, "dash": dash,
           "thresholds": thresholds, "verdicts": verdicts,
           "PASS": all(verdicts.values())}
    SUITE_DIR.mkdir(parents=True, exist_ok=True)
    path = SUITE_DIR / f'{out["date"]}-t1-run{run}.json'
    path.write_text(json.dumps(out, indent=1))
    print(json.dumps({"RUN": run, "verdicts": verdicts, "PASS": out["PASS"], "fil": str(path)}, indent=1))


# ----------------------------------------------------------------- T2/T3
def run_match(regime: str, secs: int, branch: str, build: str) -> None:
    c = conn()
    keep_telemetry(c)
    pacifist = "1" if regime == "T2" else "0"
    c.request(f"set rtx_bot_pacifist {pacifist}")
    bot_ids(c, 4)
    c.close()
    run = next_run()
    label = ("Pacifist-frispel 4 bottar" if regime == "T2" else "Riktig match 4 bottar, skott på")
    out = EVID / f'snapshots/{time.strftime("%Y-%m-%d")}/{regime.lower()}-run{run}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-u", str(Path(__file__).parent / "match_snapshot.py"),
           "--secs", str(secs), "--out", str(out), "--run", str(run),
           "--label", f"{regime} · {label}", "--branch", branch, "--build", build]
    print("kör:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    # stämpla regimen i snapshotten
    d = json.loads(out.read_text())
    d["regime"] = regime
    out.write_text(json.dumps(d, separators=(",", ":")))
    # återställ standardläget (pacifist på)
    c = conn()
    c.request("set rtx_bot_pacifist 1")
    c.close()
    print(json.dumps({"RUN": run, "regime": regime, "snapshot": str(out)}))
    if regime == "T3":
        print("OBS: combat lock kräver MVD-demo + combat_lock.py — koppla på när "
              "demoinspelning på labbet är verifierad.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", choices=["t1", "t2", "t3"])
    ap.add_argument("--quick", action="store_true", help="T1: 3 försök i stället för 10")
    ap.add_argument("--with-dash", action="store_true", help="T1: inkludera 100m-dashen (kartbyte)")
    ap.add_argument("--secs", type=int, default=600)
    ap.add_argument("--branch", default="?")
    ap.add_argument("--build", default="?")
    a = ap.parse_args()
    if a.tier == "t1":
        run_t1(a.quick, a.with_dash)
    else:
        run_match(a.tier.upper(), a.secs, a.branch, a.build)


if __name__ == "__main__":
    main()
