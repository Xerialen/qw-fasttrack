"""Läs mätserie. Stämplar tas om de finns; annars explicit unknown."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

from .dump import cell_str, lank_str, q, q_xyz

STAMP_CELL_KEYS = ("cell_id", "cell")
STAMP_LINK_KEYS = ("link_id", "link", "lank", "aktiv_lank", "chosen_link")
T1H_CYKEL = re.compile(r"^c(\d{3})$")
ATTEMPT = re.compile(r"^attempt_(\d+)\.jsonl$")
META_SKIP = frozenset({"ogiltig_tic", "kasserad"})


def _first(d: dict, keys: tuple[str, ...]):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def extract_stamp(row: dict, player: dict | None = None) -> dict:
    """Plocka stämpel från rad och ev. player-objekt. Gissar aldrig xyz."""
    sources = []
    if player:
        sources.append(player)
    sources.append(row)
    cell = "unknown"
    lank = "unknown"
    stamp = None
    contract = None
    for src in sources:
        if not isinstance(src, dict):
            continue
        c = _first(src, STAMP_CELL_KEYS)
        if c is not None and cell == "unknown":
            cell = cell_str(c)
        ln = _first(src, STAMP_LINK_KEYS)
        if ln is not None and lank == "unknown":
            lank = lank_str(ln)
        if stamp is None and src.get("navmesh_stamp") is not None:
            stamp = src["navmesh_stamp"]
        if contract is None and src.get("graph_contract") is not None:
            contract = src["graph_contract"]
    bind = "stamped" if cell != "unknown" else "unknown"
    return {
        "cell": cell,
        "lank": lank,
        "bind": bind,
        "navmesh_stamp": stamp,
        "graph_contract": contract,
    }


def _load_stamp_sidecar(jsonl: Path, stamplar: Path | None,
                        serie: Path | None = None) -> list[dict] | None:
    cands = [Path(str(jsonl) + ".stamp.jsonl"),
             jsonl.with_name(jsonl.stem + ".stamp.jsonl")]
    if stamplar is not None:
        if serie is not None:
            try:
                rel = jsonl.relative_to(serie)
                cands.append(stamplar / rel)
                cands.append(Path(str(stamplar / rel) + ".stamp.jsonl"))
            except ValueError:
                cands.append(stamplar / jsonl.name)
        else:
            cands.append(stamplar / jsonl.name)
    for c in cands:
        if c.is_file():
            rows = []
            for line in c.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return rows
    return None


def _align_stamp(sidecars: list[dict] | None, idx: int, t: float | None) -> dict:
    if not sidecars:
        return {}
    if 0 <= idx < len(sidecars):
        row = sidecars[idx]
        if t is None:
            return row
        st = row.get("t")
        if st is None or q(st, 3) == q(t, 3):
            return row
    if t is None:
        return {}
    want = q(t, 3)
    for row in sidecars:
        if q(row.get("t"), 3) == want:
            return row
    return {}


def iter_ticks(jsonl: Path, ent: int, stamplar: Path | None = None,
               serie: Path | None = None) -> Iterator[dict]:
    sidecars = _load_stamp_sidecar(jsonl, stamplar, serie)
    with jsonl.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            extra = _align_stamp(sidecars, i, row.get("t"))
            if extra:
                merged = dict(row)
                for k, v in extra.items():
                    if k not in merged or merged[k] is None:
                        merged[k] = v
                row = merged
            yield from _ticks_from_row(row, ent, i)


def _ticks_from_row(row: dict, ent: int, idx: int) -> Iterator[dict]:
    t = row.get("t")
    players = row.get("players") or []
    picked = None
    for p in players:
        if p.get("ent") == ent:
            picked = p
            break
    if picked is None and len(players) == 1:
        picked = players[0]
    if picked is not None and picked.get("origin") is not None:
        stamp = extract_stamp(row, picked)
        yield {
            "t": t,
            "origin": list(picked["origin"]),
            "on_ground": picked.get("on_ground"),
            "row": row,
            "player": picked,
            "idx": idx,
            **stamp,
        }
        return
    # stall-kuvert utan players (stall_recorder / live event)
    if row.get("ev") == "bot_stall" or isinstance(row.get("stall"), dict):
        ev = row["stall"] if isinstance(row.get("stall"), dict) else row
        origin = ev.get("origin") or ev.get("pos")
        stamp = extract_stamp(ev)
        stamp2 = extract_stamp(row)
        if stamp["cell"] == "unknown":
            stamp["cell"] = stamp2["cell"]
        if stamp["lank"] == "unknown":
            stamp["lank"] = stamp2["lank"]
        yield {
            "t": ev.get("t", t),
            "origin": list(origin) if origin else None,
            "on_ground": ev.get("on_ground"),
            "row": row,
            "player": None,
            "idx": idx,
            "stall_event": ev,
            **stamp,
        }


def _ben_from_name(name: str) -> str:
    return Path(name).stem.replace("_meta", "")


def _regim_from_meta(meta: dict, layout: str) -> str:
    start = meta.get("start")
    if start == "kedjad":
        return "kedjad"
    if start == "teleport_efter_fel":
        return "teleport"
    if start:
        return str(start)
    # K-serien är teleport-isolerad om inget annat sägs
    if layout == "k":
        return "teleport"
    return "unknown"


def _cykel_from(meta: dict, cdir: str | None) -> int | None:
    if isinstance(meta.get("cykel"), int):
        return meta["cykel"]
    if cdir:
        m = T1H_CYKEL.match(cdir)
        if m:
            return int(m.group(1))
    return None


def discover_forsok(serie: Path, arm: str | None, ent: int,
                    stamplar: Path | None) -> list[dict]:
    """Hitta försök i T1h- eller K-layout (eller platt jsonl)."""
    serie = serie.resolve()
    found: list[dict] = []
    arms = [arm] if arm in ("A", "B") else ["A", "B"]

    t1h = False
    for a in arms:
        root = serie / a
        if not root.is_dir():
            continue
        cycles = sorted(p for p in root.iterdir()
                        if p.is_dir() and T1H_CYKEL.match(p.name))
        if cycles:
            t1h = True
            for cdir in cycles:
                for jsonl in sorted(cdir.glob("*.jsonl")):
                    if jsonl.name.endswith(".stamp.jsonl"):
                        continue
                    ben = _ben_from_name(jsonl.name)
                    meta_p = cdir / f"{ben}_meta.json"
                    meta = {}
                    if meta_p.is_file():
                        try:
                            meta = json.loads(meta_p.read_text(encoding="utf-8"))
                        except json.JSONDecodeError:
                            meta = {}
                    if meta.get("utfall") in META_SKIP:
                        continue
                    found.append(_pack(serie, a, ben, jsonl, meta, "t1h",
                                       cdir.name, ent, stamplar))

    if t1h:
        return found

    # K-layout: serie/{A,B}/<ben>/attempt_NN.jsonl + summary.json
    k = False
    for a in arms:
        root = serie / a
        if not root.is_dir():
            continue
        for ben_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            attempts = sorted(ben_dir.glob("attempt_*.jsonl"))
            if not attempts:
                continue
            k = True
            summary = {}
            sp = ben_dir / "summary.json"
            if sp.is_file():
                try:
                    summary = json.loads(sp.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    summary = {}
            by_fil = {}
            for rec in summary.get("forsok") or []:
                if isinstance(rec, dict) and rec.get("fil"):
                    by_fil[rec["fil"]] = rec
            for jsonl in attempts:
                rec = dict(by_fil.get(jsonl.name) or {})
                if rec.get("utfall") in META_SKIP:
                    continue
                # normalisera K-utfall: ok → framme analogt, timeout behålls
                found.append(_pack(serie, a, ben_dir.name, jsonl, rec, "k",
                                   None, ent, stamplar))

    if k:
        return found

    # platt: alla jsonl under serie (ej stamp-sidovagnar)
    for jsonl in sorted(serie.rglob("*.jsonl")):
        if jsonl.name.endswith(".stamp.jsonl"):
            continue
        rel = jsonl.relative_to(serie)
        parts = rel.parts
        a = parts[0] if parts and parts[0] in ("A", "B") else "?"
        found.append(_pack(serie, a, jsonl.stem, jsonl, {}, "flat",
                           None, ent, stamplar))
    return found


def _pack(serie: Path, arm: str, ben: str, jsonl: Path, meta: dict,
          layout: str, cdir: str | None, ent: int, stamplar: Path | None) -> dict:
    cykel = _cykel_from(meta, cdir)
    if layout == "t1h":
        forsok_id = f"{arm}/c{cykel:03d}/{ben}" if cykel is not None \
            else f"{arm}/{ben}"
    elif layout == "k":
        forsok_id = f"{arm}/{ben}/{jsonl.stem}"
    else:
        forsok_id = str(jsonl.relative_to(serie)).replace("\\", "/")
    return {
        "forsok_id": forsok_id,
        "arm": arm,
        "ben": ben,
        "cykel": cykel,
        "jsonl": jsonl,
        "meta": meta,
        "layout": layout,
        "regim": _regim_from_meta(meta, layout),
        "ent": ent,
        "stamplar": stamplar,
        "serie": serie,
        "utfall": meta.get("utfall"),
        "undanta_ut": _undanta_ut(ben, meta),
    }


def _undanta_ut(ben: str, meta: dict) -> bool:
    if isinstance(meta.get("undanta"), bool):
        return meta["undanta"]
    if isinstance(meta.get("undanta_ut"), bool):
        return meta["undanta_ut"]
    return ben.startswith("ut_")


def load_ticks(forsok: dict) -> list[dict]:
    return list(iter_ticks(forsok["jsonl"], forsok["ent"],
                           forsok.get("stamplar"), forsok.get("serie")))


def apply_regim_filter(forsok: list[dict], regim: str) -> tuple[list[dict], dict]:
    n_in = len(forsok)
    if regim == "alla":
        kept = list(forsok)
    elif regim == "kedjad":
        kept = [f for f in forsok if f["regim"] == "kedjad"]
    elif regim == "teleport":
        kept = [f for f in forsok if f["regim"] in ("teleport", "teleport_efter_fel")]
    else:
        kept = [f for f in forsok if f["regim"] == regim]
    filt = {
        "regim": regim,
        "n_forsok_in": n_in,
        "n_forsok_behallna": len(kept),
        "n_forsok_exkluderade": n_in - len(kept),
    }
    return kept, filt


def merge_navmesh(ticks_stamps: list[Any]) -> Any:
    """Ett stamp om alla lika; annars mixed; saknas = unknown."""
    vals = [s for s in ticks_stamps if s is not None]
    if not vals:
        return "unknown"
    first = vals[0]
    for v in vals[1:]:
        if v != first:
            return {"status": "mixed"}
    return first
