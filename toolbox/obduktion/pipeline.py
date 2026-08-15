"""obducera: serie → händelser → kluster → prioriterad åtgärdslista."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapter import (apply_kap, discover_forsok, load_attr, load_ticks,
                      merge_navmesh, population_etikett, resolve_graph_stamp)
from .dump import SCHEMA
from .klassa import finalize_handelse, klassa_forsok
from .kluster import (klustra, numrera_och_prioritera, raknare,
                      tilldela_handelse_id)

POP_KINDS = ("alla_giltiga", "kedjad", "teleport_efter_fel")
POP_PREFIX = {
    "alla_giltiga": ("G", "GK"),
    "kedjad": ("H", "K"),
    "teleport_efter_fel": ("X", "XK"),
}


def _process_forsok(forsok: list[dict]) -> tuple[list[dict], list[Any], list[Any],
                                                 dict, dict, dict]:
    raw_events: list[dict] = []
    stamps: list[Any] = []
    contracts: list[Any] = []
    n_stamped = n_unknown = 0
    # Grafkontrollen per tick, PER ARM: ok = validerad mot armens referens;
    # avvikande = validerad och avvek; ovaliderad = rad bar en stamp men armen
    # saknade referens (intra-arm-konflikt) så inget validerades (fail-closed i
    # adaptern); ostamplad = ingen stamp alls.
    per_arm: dict[str, dict] = {}
    for f in forsok:
        arm = f.get("arm") or "?"
        ref = f.get("_arm_stamp", f.get("ref_stamp"))
        st = per_arm.setdefault(arm, {
            "referens": ref if ref is not None else "unknown",
            "ok": 0, "avvikande": 0, "ostamplade": 0, "ovaliderad": 0,
        })
        ticks = load_ticks(f)
        for tk in ticks:
            if tk.get("bind") == "stamped":
                n_stamped += 1
            else:
                n_unknown += 1
            if tk.get("stamp_avvik"):
                st["avvikande"] += 1
            elif tk.get("graph_stamp"):
                if ref is not None:
                    st["ok"] += 1
                else:
                    st["ovaliderad"] += 1
            else:
                st["ostamplade"] += 1
            if tk.get("navmesh_stamp") is not None:
                stamps.append(tk["navmesh_stamp"])
            if tk.get("graph_contract") is not None:
                contracts.append(tk["graph_contract"])
        raw_events.extend(klassa_forsok(f, ticks))
    sk = {"ok": 0, "avvikande": 0, "ostamplade": 0, "ovaliderad": 0}
    for st in per_arm.values():
        sk["ok"] += st["ok"]
        sk["avvikande"] += st["avvikande"]
        sk["ostamplade"] += st["ostamplade"]
        sk["ovaliderad"] += st["ovaliderad"]
    return (raw_events, stamps, contracts,
            {"stamplade": n_stamped, "unknown": n_unknown},
            sk, per_arm)


def _stamp_population(handelser: list[dict], kluster: list[dict],
                      atgarder: list[dict], etikett: str) -> None:
    for k in kluster:
        k["population"] = etikett
    for a in atgarder:
        a["population"] = etikett


def _finalize_set(raw_events: list[dict], hid_prefix: str, kid_prefix: str,
                  etikett: str, with_atgarder: bool
                  ) -> tuple[list[dict], list[dict], list[dict]]:
    ordered = tilldela_handelse_id(raw_events, prefix=hid_prefix)
    handelser = []
    for i, ev in enumerate(ordered, 1):
        handelser.append(finalize_handelse(ev, f"{hid_prefix}{i:04d}"))
    kluster, atgarder = numrera_och_prioritera(klustra(handelser), prefix=kid_prefix)
    if not with_atgarder:
        atgarder = []
    _stamp_population(handelser, kluster, atgarder, etikett)
    return handelser, kluster, atgarder


def _pop_members(giltiga: list[dict], kind: str) -> list[dict]:
    if kind == "alla_giltiga":
        return list(giltiga)
    if kind == "kedjad":
        return [f for f in giltiga if f["regim"] == "kedjad"]
    return [f for f in giltiga if f["regim"] in ("teleport", "teleport_efter_fel")]


def _evidens_kind(regim: str) -> str:
    if regim == "alla":
        return "alla_giltiga"
    if regim == "teleport":
        return "teleport_efter_fel"
    return "kedjad"


def _population_obj(kind: str, n_kap: int | None, members: list[dict],
                    raw: list[dict], bind: dict, with_atgarder: bool) -> dict:
    etikett = population_etikett(kind, n_kap)
    hid, kid = POP_PREFIX[kind]
    handelser, kluster, atgarder = _finalize_set(
        raw, hid, kid, etikett, with_atgarder)
    counts = raknare(handelser, kluster, len(members))
    out = {
        "population": etikett,
        "n_kap": n_kap,
        **counts,
        "bind_statistik": bind,
        "handelser": handelser,
        "kluster": kluster,
    }
    return out, atgarder


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
    upptackta = discover_forsok(serie_p, arm_arg, ent, stamp_p)
    # Vilken graf serien är mätt mot, EN gång, innan någon rad läses för allvar.
    # Varje tick valideras sedan mot den; en rad från en annan graf blir obunden
    # i stället för felbunden.
    graf = resolve_graph_stamp(upptackta, stamp_p, serie_p)
    for f in upptackta:
        f["ref_stamp"] = None if graf["referens"] == "unknown" else graf["referens"]
        # Spår A:s per-försöks-attribution, läst men inte tolkad här: bindningen
        # av ett fall till landningscellen ägs av klassningen (spår I).
        f["attr"] = load_attr(f)
    giltiga, kap = apply_kap(upptackta)
    n_kap = kap["n"]

    ev_kind = _evidens_kind(regim)
    evidens = _pop_members(giltiga, ev_kind)
    filt = {
        "regim": regim,
        "n_forsok_fore_kap": len(upptackta),
        "n_forsok_in": len(giltiga),
        "n_forsok_behallna": len(evidens),
        "n_forsok_exkluderade": len(giltiga) - len(evidens),
    }

    pop_cache: dict[str, dict] = {}
    all_stamps: list[Any] = []
    all_contracts: list[Any] = []
    stamp_kontroll = {"ok": 0, "avvikande": 0, "ostamplade": 0, "ovaliderad": 0}
    stamp_per_arm: dict[str, dict] = {}
    for kind in POP_KINDS:
        members = _pop_members(giltiga, kind)
        raw, stamps, contracts, bind, sk, per_arm = _process_forsok(members)
        all_stamps.extend(stamps)
        all_contracts.extend(contracts)
        if kind == "alla_giltiga":
            # Räknat på alla giltiga försök: grafkontrollen är en egenskap hos
            # datat, inte hos evidensfiltret, och ska inte ändras av --regim.
            stamp_kontroll = sk
            stamp_per_arm = per_arm
        obj, atg = _population_obj(
            kind, n_kap, members, raw, bind,
            with_atgarder=(kind == ev_kind),
        )
        pop_cache[kind] = (obj, atg)

    populationer = {}
    for kind in POP_KINDS:
        et = population_etikett(kind, n_kap)
        populationer[et] = pop_cache[kind][0]

    ev, ev_atgarder = pop_cache[ev_kind]
    if arm in (None, "AB"):
        arms_seen = sorted({f["arm"] for f in giltiga if f["arm"] in ("A", "B")})
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
        "graph_contract": _one_or_unknown(all_contracts),
        "graph_stamp": graf["referens"],
        "stamp_kontroll": {
            "kalla": graf["kalla"],
            "referens": graf["referens"],
            "per_arm": stamp_per_arm,
            **stamp_kontroll,
        },
        "navmesh_stamp": merge_navmesh(all_stamps),
        "bind_statistik": ev["bind_statistik"],
        "kap": kap,
        "filter": filt,
        "handelser": ev["handelser"],
        "kluster": ev["kluster"],
        "atgarder": ev_atgarder,
        "populationer": populationer,
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
