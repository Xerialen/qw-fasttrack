#!/usr/bin/env python3
"""stall_recorder.py — spela in varje `bot_stall` med botens audit-svans.

Ansluter via `core.Control`, lyssnar på `bot_stall`-eventet (rtx-sidans
BotStall: vilken vakthund som slog, på vilken cell, på vilket ben och vad den
gjorde åt saken), hämtar `audit <bot> <lines>` direkt efter varje stall och
appendar `{"stall": ..., "audit_tail": [...]}` som en JSONL-rad.

Poängen är kopplingen: stallet säger *att* boten fastnade och var; auditsvansen
säger vad den försökte precis innan. Var för sig är de gissningar.

    python3 scripts/stall_recorder.py [--out FIL] [--lines N] [--port P]
                                      [--host H] [--bot N] [--max N]

Avslutas med Ctrl-C, eller när --max stallar spelats in.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# `fasttrack/core.py` imports its siblings flat (`import mpwire`), so the
# package directory itself has to be on the path — the same insert every test
# under fasttrack/tests/ does.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fasttrack"))

import core  # noqa: E402

DEFAULT_OUT = Path.home() / ".local/share/qw-fasttrack/evidence/bot-stalls.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"JSONL att appenda till (default {DEFAULT_OUT})")
    ap.add_argument("--lines", type=int, default=400,
                    help="antal auditrader att hämta per stall (default 400)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=core.CONTROL_PORT)
    ap.add_argument("--bot", type=int, default=None,
                    help="spela bara in stallar för den här boten")
    ap.add_argument("--max", type=int, default=0,
                    help="sluta efter N stallar (0 = kör tills Ctrl-C)")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    ctl = core.Control(host=args.host, port=args.port)
    print(f"stall_recorder: lyssnar på {args.host}:{args.port} -> {args.out}", flush=True)

    n = 0
    try:
        with args.out.open("a", encoding="utf-8") as fh:
            while True:
                ev = ctl.wait_event(("bot_stall",), timeout=5.0)
                if ev is None:
                    continue
                bot = ev.get("bot")
                if args.bot is not None and bot != args.bot:
                    continue
                # Auditsvansen hämtas direkt: den är en ringbuffert på boten, så
                # varje sekunds dröjsmål är rader som skrivs över av nästa frame.
                try:
                    reply = ctl.request(f"audit {bot} {args.lines}", timeout=15.0)
                    tail = reply.get("data")
                except core.ControlError as exc:
                    tail = {"error": str(exc)}
                fh.write(json.dumps({"recorded_at": time.time(),
                                     "stall": ev,
                                     "audit_tail": tail},
                                    ensure_ascii=False) + "\n")
                fh.flush()
                n += 1
                print(f"[{n}] bot {bot} {ev.get('reason')} -> {ev.get('action')} "
                      f"cell {ev.get('cell')} link {ev.get('link')} "
                      f"kind {ev.get('kind')!r} speed {ev.get('speed')}", flush=True)
                if args.max and n >= args.max:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        ctl.close()
    print(f"stall_recorder: {n} stallar skrivna till {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
