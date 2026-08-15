"""CLI: obducera JSON → snapshots + ev. dashboard-HTML."""
from __future__ import annotations

import argparse
from pathlib import Path

from .convert import convert_path, dumps
from .render import default_map_dir, render_html


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dashadapter")
    p.add_argument("--obducera", type=Path, required=True)
    p.add_argument("--out-snapshots", type=Path, required=True)
    p.add_argument("--out-html", type=Path, default=None)
    p.add_argument("--map-dir", type=Path, default=None,
                   help="assets/maps/<karta> (graph.json + entities.json)")
    p.add_argument("--map-template", type=Path, required=True,
                   help="map-template.html med I-klassnycklar "
                        "(toolbox/dashboard-i-classes). Obligatorisk.")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if not a.map_template.is_file():
        raise SystemExit(f"map-template saknas: {a.map_template}")
    map_dir = a.map_dir or default_map_dir()
    if not map_dir.is_dir():
        map_dir = None
    proposal = convert_path(a.obducera, map_dir, a.map_template)
    a.out_snapshots.write_text(dumps(proposal), encoding="utf-8")
    if a.out_html is not None:
        html = render_html(proposal, a.map_template.read_text(encoding="utf-8"))
        a.out_html.parent.mkdir(parents=True, exist_ok=True)
        a.out_html.write_text(html, encoding="utf-8")
    return 0
