"""Validera en klassningsfil mot rev 4-evidenskrav.

Klassare fyller klassens obligatoriska fält. Saknas fält eller pekar de
inte på verifierbart underlag i kandidatens källor avvisas raden —
förslag: okand_ingen_fix + missing_*. Samma läxa som B:s attest-grind.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .krav import (
    KLASSER,
    KRAV,
    KRAV_PEKARE,
    PRIS_OCERTIFIERAD,
    REASON_PRIO,
    UNKNOWN_REASONS,
)

SCHEMA = "verktygslada/taxonomi-validering/1"
KLASSNING_SCHEMA = "verktygslada/taxonomi-klassning/2"


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True) + "\n"


def _tom(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return False
    if isinstance(v, str):
        return v.strip() in ("", "unknown")
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _get(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _fil_match(pekad: str, kalla: str) -> bool:
    p = pekad.replace("\\", "/").rstrip("/")
    k = str(kalla).replace("\\", "/").rstrip("/")
    return p == k or p.endswith("/" + k) or k.endswith("/" + p) or p in k or k in p


def las_jsonl(path: Path) -> list[dict]:
    rader = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{i} inte ett objekt")
        rader.append(obj)
    return rader


def _pekare_fel(evidens: dict, kandidat: dict | None) -> list[str]:
    pekare = evidens.get("pekare")
    if not isinstance(pekare, list) or not pekare:
        return ["evidens.pekare saknas (kräver [{fil, falt|rad}, ...])"]
    fel = []
    kallor = list((kandidat or {}).get("kallor") or [])
    for i, p in enumerate(pekare):
        if not isinstance(p, dict):
            fel.append(f"evidens.pekare[{i}] inte objekt")
            continue
        fil = p.get("fil")
        if _tom(fil):
            fel.append(f"evidens.pekare[{i}].fil saknas")
            continue
        if p.get("falt") is None and p.get("rad") is None:
            fel.append(f"evidens.pekare[{i}] saknar falt eller rad")
        if kandidat is not None and kallor:
            if not any(_fil_match(str(fil), k) for k in kallor):
                fel.append(
                    f"evidens.pekare[{i}].fil={fil!r} finns inte i "
                    f"kandidatens kallor"
                )
        elif kandidat is not None and not kallor:
            fel.append("kandidat saknar kallor — pekare kan inte verifieras")
    return fel


def _saknade_falt(klass: str, evidens: dict) -> list[tuple[str, str]]:
    ut = []
    for path, reason in KRAV.get(klass, ()):
        if _tom(_get(evidens, path)):
            ut.append((path, reason))
    if klass == "lagg_lank":
        struktur = evidens.get("struktur_dom") or _get(evidens, "falt.struktur_dom")
        if struktur == "structural_missing_link":
            if _get(evidens, "falt.goal_reachable") is not False:
                ut.append(("falt.goal_reachable", "missing_graph_inventory"))
            if _get(evidens, "falt.selected_link") is not None:
                ut.append(("falt.selected_link", "missing_graph_inventory"))
            niva2 = _get(evidens, "niva2_inventering.graph_content_hash")
            if _tom(niva2) or niva2 == "unknown":
                ut.append(("niva2_inventering.graph_content_hash",
                           "missing_graph_inventory"))
            if _get(evidens, "harness_predikatstopp.stopp_utanfor") is not True:
                ut.append(("harness_predikatstopp.stopp_utanfor",
                           "missing_harness_predicate"))
    if klass == "ignorera_avsett":
        hk = _get(evidens, "falt.handelse_klass")
        undanta = _get(evidens, "falt.undanta")
        if hk != "avsett_drop" and undanta is not True:
            ut.append(("falt.handelse_klass", "missing_harness_predicate"))
    if klass == "pris_vreq" and PRIS_OCERTIFIERAD:
        ut.append(("certifierad", "missing_plan_fields"))
    if _get(evidens, "falt.orsak_etikett") == "v_req_deficit":
        ut.append(("falt.orsak_etikett", "missing_plan_fields"))
    if _get(evidens, "falt.v_req_deficit") is True:
        ut.append(("falt.v_req_deficit", "missing_plan_fields"))
    return ut


def _valj_reason(reasons: list[str]) -> str:
    for r in REASON_PRIO:
        if r in reasons:
            return r
    return "missing_plan_fields"


def validera_rad(rad: dict, kandidat: dict | None) -> dict:
    rid = rad.get("id")
    if _tom(rid):
        return {
            "id": "unknown",
            "klass_in": rad.get("klass") or rad.get("atgardsklass"),
            "utfall": "avvisad",
            "forslag_klass": "okand_ingen_fix",
            "unknown_reason": "missing_plan_fields",
            "skal": ["id saknas"],
        }
    klass = rad.get("klass") or rad.get("atgardsklass")
    evidens = rad.get("evidens")
    skal: list[str] = []
    reasons: list[str] = []

    if not isinstance(evidens, dict):
        skal.append("evidens saknas eller är inte objekt")
        reasons.append("missing_plan_fields")
        evidens = {}

    if _tom(klass) or klass not in KLASSER:
        skal.append(f"klass ogiltig: {klass!r}")
        reasons.append("missing_plan_fields")
        klass = None

    if klass == "okand_ingen_fix":
        ur = rad.get("unknown_reason") or evidens.get("unknown_reason")
        if ur not in UNKNOWN_REASONS:
            skal.append("okand_ingen_fix kräver unknown_reason ur sluten vokabulär")
            reasons.append("missing_plan_fields")
    elif klass is not None:
        for path, reason in _saknade_falt(klass, evidens):
            skal.append(f"{path} saknas eller är unknown")
            reasons.append(reason)
        if klass in KRAV_PEKARE:
            for f in _pekare_fel(evidens, kandidat):
                skal.append(f)
                reasons.append("missing_plan_fields")

    skal = sorted(set(skal))
    if skal:
        return {
            "id": rid,
            "klass_in": klass,
            "utfall": "avvisad",
            "forslag_klass": "okand_ingen_fix",
            "unknown_reason": _valj_reason(reasons),
            "skal": skal,
        }
    return {
        "id": rid,
        "klass_in": klass,
        "utfall": "godkand",
        "forslag_klass": klass,
        "unknown_reason": (
            rad.get("unknown_reason") or evidens.get("unknown_reason")
            if klass == "okand_ingen_fix" else None
        ),
        "skal": [],
    }


def validera(klassning: list[dict], kandidater: list[dict] | None) -> dict:
    idx = {}
    if kandidater is not None:
        for k in kandidater:
            kid = k.get("id")
            if kid:
                idx[kid] = k
    resultat = []
    for rad in klassning:
        kid = rad.get("id")
        kand = idx.get(kid) if kid else None
        if kandidater is not None and kid and kand is None:
            rec = {
                "id": kid,
                "klass_in": rad.get("klass") or rad.get("atgardsklass"),
                "utfall": "avvisad",
                "forslag_klass": "okand_ingen_fix",
                "unknown_reason": "missing_plan_fields",
                "skal": ["id saknas i kandidatfilen"],
            }
        else:
            rec = validera_rad(rad, kand)
        resultat.append(rec)
    resultat.sort(key=lambda r: (r["id"], r["utfall"]))
    n_av = sum(1 for r in resultat if r["utfall"] == "avvisad")
    return {
        "schema": SCHEMA,
        "klassning_schema": KLASSNING_SCHEMA,
        "n_avvisade": n_av,
        "n_godkanda": len(resultat) - n_av,
        "n_rader": len(resultat),
        "ok": n_av == 0,
        "rader": resultat,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="validera_klassning",
        description="Avvisa klassning som saknar rev 4-evidens eller "
                    "pekare in i kandidatens källor.")
    p.add_argument("--klassning", required=True, type=Path,
                   help="jsonl: id, klass, evidens{}")
    p.add_argument("--kandidater", type=Path, default=None,
                   help="blind kandidatfil (kallor). Krävs i runda 2.")
    p.add_argument("--out", type=Path, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        klassning = las_jsonl(args.klassning)
        kandidater = las_jsonl(args.kandidater) if args.kandidater else None
    except (OSError, json.JSONDecodeError, ValueError) as e:
        sys.stderr.write(f"AVBRYTER: {e}\n")
        return 2
    doc = validera(klassning, kandidater)
    text = dumps(doc)
    if args.out is None or str(args.out) == "-":
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
