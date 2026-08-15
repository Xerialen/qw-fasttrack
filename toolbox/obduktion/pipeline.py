"""obducera: serie → händelser → kluster → prioriterad åtgärdslista."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapter import apply_regim_filter, discover_forsok, load_ticks, merge_navmesh
from .dump import SCHEMA
from .klassa import finalize_handelse, klassa_forsok
from .kluster import klustra, numrera_och_prioritera, tilldela_handelse_id


def obducera(serie: str | Path, *,
             arm: str | None = None,
             regim: str = "kedjad",
             stamplar: str | Path | None = None,
             ent: int = 1) -> dict[str, Any]:
    serie_p = Path(serie)
    if not serie_p.is_dir():
        raise FileNotFoundError(f"serie finns inte: {serie_p}")
    stamp_p = Path(stamplar) if stamplar else None
    if arm not in (None, "A", "B", "AB"):
        raise ValueError("arm måste vara A, B, AB eller utelämnad")
    arm_arg = None if arm in (None, "AB") else arm
    forsok = discover_forsok(serie_p, arm_arg, ent, stamp_p)
    kept, filt = apply_regim_filter(forsok, regim)

    raw_events: list[dict] = []
    stamps: list[Any] = []
    contracts: list[Any] = []
    n_stamped = n_unknown = 0
    for f in kept:
        ticks = load_ticks(f)
        for tk in ticks:
            if tk.get("bind") == "stamped":
                n_stamped += 1
            else:
                n_unknown += 1
            if tk.get("navmesh_stamp") is not None:
                stamps.append(tk["navmesh_stamp"])
            if tk.get("graph_contract") is not None:
                contracts.append(tk["graph_contract"])
        raw_events.extend(klassa_forsok(f, ticks))

    ordered = tilldela_handelse_id(raw_events)
    handelser = []
    for i, ev in enumerate(ordered, 1):
        handelser.append(finalize_handelse(ev, f"H{i:04d}"))

    kluster, atgarder = numrera_och_prioritera(klustra(handelser))

    if arm in (None, "AB"):
        arms_seen = sorted({f["arm"] for f in kept if f["arm"] in ("A", "B")})
        arm_out = "".join(arms_seen) if arms_seen else "AB"
        if arm_out not in ("A", "B", "AB"):
            arm_out = "AB"
    else:
        arm_out = arm

    return {
        "schema": SCHEMA,
        "kommando": "obducera",
        "serie": serie_p.name,
        "arm": arm_out,
        "regim": regim,
        "graph_contract": _one_or_unknown(contracts),
        "navmesh_stamp": merge_navmesh(stamps),
        "bind_statistik": {"stamplade": n_stamped, "unknown": n_unknown},
        "filter": filt,
        "handelser": handelser,
        "kluster": kluster,
        "atgarder": atgarder,
    }


def _one_or_unknown(vals: list[Any]) -> Any:
    if not vals:
        return "unknown"
    first = vals[0]
    for v in vals[1:]:
        if v != first:
            return "unknown"
    if isinstance(first, str) and first:
        return first
    return "unknown"
