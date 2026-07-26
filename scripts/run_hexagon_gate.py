#!/usr/bin/env python3
"""Shim: kör hexagon_gate.py mot ett repo-bygge som saknar `penalties`-verbet.

Monkeypatchar core.Control.request så att `penalties <bot>` besvaras med en tom
lista i stället för att parse:a mot verbtabellen. Allt annat går orört igenom.
Användning: python3 -u scripts/run_hexagon_gate.py <bot> <mode> [n] [jsonl]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fasttrack"))
import fasttrack.core as core  # noqa: E402

_orig = core.Control.request


def request(self, verb_and_args, timeout=15.0, before_send=None):
    if verb_and_args.split()[0] == "penalties":
        return {"ok": True, "data": []}
    return _orig(self, verb_and_args, timeout=timeout, before_send=before_send)


core.Control.request = request

sys.argv[0] = "hexagon_gate.py"
exec(compile(open(Path(__file__).parent / "hexagon_gate.py").read(),
             "hexagon_gate.py", "exec"))
