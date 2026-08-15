"""Kanonisk JSON-dump enligt toolbox/obduktion/KONTRAKT.md."""
from __future__ import annotations

import json
from typing import Any

SCHEMA = "verktygslada/obducera/1"
LOCUS_RADIE = 64.0
NOLINK = 4294967295
KLASSER = ("fall", "avsett_drop", "stall", "timeout", "fastnad")
ATGARD_KLASSER = frozenset({"fall", "fastnad", "timeout", "stall"})


def q(value: float | None, ndigits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), ndigits)


def q_xyz(origin) -> list[float]:
    return [round(float(origin[0]), 2),
            round(float(origin[1]), 2),
            round(float(origin[2]), 2)]


def cell_str(value) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, str):
        s = value.strip()
        return s if s else "unknown"
    if isinstance(value, bool):
        return "unknown"
    if isinstance(value, int):
        if value == NOLINK:
            return "unknown"
        return str(value)
    if isinstance(value, float):
        if value == float(NOLINK) or value != value:  # noqa: PLR0124
            return "unknown"
        if value == int(value):
            return str(int(value))
        return str(value)
    return "unknown"


def lank_str(value) -> str:
    return cell_str(value)


def dumps(obj: Any) -> str:
    """Byte-stabil kanonisk JSON + avslutande LF."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True) + "\n"
