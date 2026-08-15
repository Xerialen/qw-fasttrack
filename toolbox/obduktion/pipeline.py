"""obducera: serie → händelser → kluster → prioriterad åtgärdslista."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .adapter import apply_regim_filter, discover_forsok, load_ticks, merge_navmesh
from .dump import SCHEMA
from .klassa import finalize_handelse, klassa_forsok
from .kluster import (klustra, numrera_och_prioritera, raknare,
                      tilldela_handelse_id)


def _process_forsok(forsok: list[dict]) -> tuple[list[dict], list[Any], list[Any],
                                                 dict]:
    raw_events: list[dict] = []
    stamps: list[Any] = []
    contracts: list[Any] = []
    n_stamped = n_unknown = 0
    for f in forsok:
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
    return raw_events, stamps, contracts, {"stamplade": n_stamped, "unknown": n_unknown}


def _finalize_set(raw_events: list[dict], hid_prefix: str, kid_prefix: str,
                  with_atgarder: bool) -> tuple[list[dict], list[dict], list[dict]]:
    ordered = tilldela_handelse_id(raw_events, prefix=hid_prefix)
    handelser = []
    for i, ev in enumerate(ordered, 1):
        handelser.append(finalize_handelse(ev, f"{hid_prefix}{i:04d}"))
    kluster, atgarder = numrera_och_prioritera(klustra(handelser), prefix=kid_prefix)
    if not with_atgarder:
        atgarder = []
    return handelser, kluster, atgarder


def _exkluderade_sektion(dropped: list[dict], raw_events: list[dict],
                         bind: dict) -> dict:
    handelser, kluster, _ = _finalize_set(raw_events, "X", "XK", with_atgarder=False)
    by_regim: dict[str, list[dict]] = defaultdict(list)
    forsok_by_regim: dict[str, set[str]] = defaultdict(set)
    for f in dropped:
        forsok_by_regim[f["regim"]].add(f["forsok_id"])
    hid_to_regim = {h["id"]: h["regim"] for h in handelser}
    for h in handelser:
        by_regim[h["regim"]].append(h)
    # kluster per regim: de vars alla händelser delar regimen
    kluster_by_regim: dict[str, list[dict]] = defaultdict(list)
    for k in kluster:
        regs = {hid_to_regim.get(i) for i in k["handelse_id"]}
        if len(regs) == 1:
            kluster_by_regim[next(iter(regs))].append(k)
    per_regim = {}
    for regim in sorted(set(forsok_by_regim) | set(by_regim)):
        per_regim[regim] = raknare(
            by_regim.get(regim, []),
            kluster_by_regim.get(regim, []),
            len(forsok_by_regim.get(regim, ())),
        )
    return {
        "n_forsok": len(dropped),
        "n_handelser": len(handelser),
        "n_kluster": len(kluster),
        "bind_statistik": bind,
        "per_regim": per_regim,
        "handelser": handelser,
        "kluster": kluster,
    }


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
    kept_ids = {id(f) for f in kept}
    dropped = [f for f in forsok if id(f) not in kept_ids]

    raw_kept, stamps_k, contracts_k, bind_k = _process_forsok(kept)
    raw_drop, stamps_d, contracts_d, bind_d = _process_forsok(dropped)

    handelser, kluster, atgarder = _finalize_set(
        raw_kept, "H", "K", with_atgarder=True)
    excl = _exkluderade_sektion(dropped, raw_drop, bind_d)

    if arm in (None, "AB"):
        arms_seen = sorted({f["arm"] for f in forsok if f["arm"] in ("A", "B")})
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
        "graph_contract": _one_or_unknown(contracts_k + contracts_d),
        "navmesh_stamp": merge_navmesh(stamps_k + stamps_d),
        "bind_statistik": bind_k,
        "filter": filt,
        "handelser": handelser,
        "kluster": kluster,
        "atgarder": atgarder,
        "exkluderade_regimer": excl,
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
