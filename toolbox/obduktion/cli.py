"""CLI för obducera — samma JSON som MCP."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dump import dumps
from .pipeline import obducera


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="obducera",
        description="Batch-obduktion: JSONL-serie → klassade händelser → "
                    "kluster → prioriterad åtgärdslista.")
    p.add_argument("--serie", required=True, type=Path,
                   help="katalog med T1h- (A/cNNN/*.jsonl) eller K-layout")
    p.add_argument("--arm", choices=["A", "B", "AB"], default="AB")
    p.add_argument("--regim", choices=["kedjad", "alla", "teleport"],
                   default="kedjad",
                   help="evidensfilter (default kedjad, E-punkten)")
    p.add_argument("--stamplar", type=Path, default=None,
                   help="sidovagn med A-stämplar; gissas aldrig fram")
    p.add_argument("--ent", type=int, default=1)
    p.add_argument("--out", type=Path, default=None,
                   help="skriv JSON här; default stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    doc = obducera(args.serie, arm=args.arm, regim=args.regim,
                   stamplar=args.stamplar, ent=args.ent)
    text = dumps(doc)
    if args.out is None or str(args.out) == "-":
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
    return 0
