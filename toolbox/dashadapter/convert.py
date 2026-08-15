"""Konvertera obducera-v2/v3 JSON till dashboardens PROPOSAL_DATA."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "verktygslada/dashadapter/1"

REASONS = (
    "displacement",
    "prestrafe_deficit",
    "air_commit_off",
    "air_commit_timeout",
    "speedjump_stall",
)

KLASS_TO_REASON = {
    "fall": "air_commit_timeout",
    "fastnad": "displacement",
    "timeout": "air_commit_timeout",
    "avsett_drop": "prestrafe_deficit",
    "stall": "speedjump_stall",
}


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True).replace("<", "\\u003c") + "\n"


def json_literal(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True).replace("<", "\\u003c")


def _cell_id(raw: str, kluster_id: str) -> int | str:
    if raw and raw != "unknown":
        try:
            return int(raw)
        except ValueError:
            return raw
    return kluster_id


def _reason_key(klass: str, stall_reason: str | None = None) -> str:
    if klass == "stall" and stall_reason in REASONS:
        return stall_reason
    return KLASS_TO_REASON.get(klass, "displacement")


def _merge_key(cell: dict) -> tuple:
    c = cell["cell"]
    if isinstance(c, str) and str(c).startswith("K"):
        return ("id", c, cell["reason"])
    if isinstance(c, str) and str(c).startswith("XK"):
        return ("id", c, cell["reason"])
    if isinstance(c, str) and str(c).startswith("GK"):
        return ("id", c, cell["reason"])
    return ("cell", c, cell["reason"])


def _kluster_to_cell(k: dict) -> dict:
    cid = _cell_id(str(k.get("cell") or "unknown"), k.get("kluster_id") or "K")
    klass = k.get("klass") or "unknown"
    reason = _reason_key(klass)
    n = int(k.get("n_forsok") or 0)
    pos = k.get("centroid") or k.get("locus")
    if isinstance(pos, list) and len(pos) >= 3:
        pos = [round(float(pos[0]), 2), round(float(pos[1]), 2),
               round(float(pos[2]), 2)]
    else:
        pos = None
    samples = []
    for fid in (k.get("forsok_id") or [])[:8]:
        samples.append({"forsok_id": fid, "klass": klass, "reason": reason})
    links = {}
    lank = k.get("lank")
    if lank and lank != "unknown":
        links[str(lank)] = n
    return {
        "cell": cid,
        "pos": pos,
        "n": n,
        "reasons": {reason: n},
        "links": links,
        "reason": reason,
        "samples": samples,
    }


def _merge_cells(cells: list[dict]) -> list[dict]:
    acc: dict[tuple, dict] = {}
    for c in cells:
        key = _merge_key(c)
        if key not in acc:
            acc[key] = {
                "cell": c["cell"],
                "pos": c["pos"],
                "n": 0,
                "reasons": {},
                "links": {},
                "reason": c["reason"],
                "samples": [],
            }
        t = acc[key]
        t["n"] += c["n"]
        for rk, rv in c["reasons"].items():
            t["reasons"][rk] = t["reasons"].get(rk, 0) + rv
        for lk, lv in c["links"].items():
            t["links"][lk] = t["links"].get(lk, 0) + lv
        for s in c["samples"]:
            if len(t["samples"]) < 8:
                t["samples"].append(s)
        if t["pos"] is None:
            t["pos"] = c["pos"]
    out = list(acc.values())
    out.sort(key=lambda c: (-c["n"], str(c["cell"]), c["reason"]))
    return out


def _pops(doc: dict) -> list[tuple[str, dict]]:
    pops = doc.get("populationer")
    if isinstance(pops, dict) and pops:
        return sorted(pops.items(), key=lambda kv: kv[0])
    return [(doc.get("regim") or "kedjad", {
        "population": doc.get("regim") or "kedjad",
        "kluster": doc.get("kluster") or [],
        "n_handelser": len(doc.get("handelser") or []),
        "n_forsok": (doc.get("filter") or {}).get("n_forsok_behallna"),
    })]


def snapshots_from_obducera(doc: dict) -> list[dict]:
    snaps = []
    for i, (etikett, pop) in enumerate(_pops(doc), 1):
        cells = _merge_cells(
            [_kluster_to_cell(k) for k in (pop.get("kluster") or [])]
        )
        firings = sum(c["n"] for c in cells)
        snaps.append({
            "id": etikett,
            "run": i,
            "time": "",
            "date": "",
            "label": etikett,
            "branch": "toolbox/i-obduktion",
            "build": doc.get("schema") or "",
            "regime": etikett,
            "stats": {"stall_firings": firings},
            "cells": cells,
            "linktotals": {},
        })
    return snaps


def load_map_assets(map_dir: Path | None) -> tuple[dict, dict, dict]:
    empty_g = {"grid": 32, "cells": [], "links": [], "cell_ids": [],
               "linkKinds": []}
    empty_e = {"map": None, "entities": []}
    if map_dir is None or not map_dir.is_dir():
        return empty_g, empty_e, {}
    graph_p = map_dir / "graph.json"
    ents_p = map_dir / "entities.json"
    graph = json.loads(graph_p.read_text(encoding="utf-8")) if graph_p.is_file() else empty_g
    ents = json.loads(ents_p.read_text(encoding="utf-8")) if ents_p.is_file() else empty_e
    linkgeo: dict = {}
    for cand in sorted(map_dir.glob("linkgeo*.json")):
        linkgeo.update(json.loads(cand.read_text(encoding="utf-8")))
    return graph, ents, linkgeo


def convert(doc: dict, map_dir: Path | None = None) -> dict:
    graph, ents, linkgeo = load_map_assets(map_dir)
    return {
        "entities": ents,
        "graph": graph,
        "linkgeo": linkgeo,
        "snapshots": snapshots_from_obducera(doc),
    }


def convert_path(obducera_path: Path, map_dir: Path | None = None) -> dict:
    doc = json.loads(obducera_path.read_text(encoding="utf-8"))
    return convert(doc, map_dir)
