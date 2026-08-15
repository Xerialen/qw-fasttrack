"""Offline-stämpling av K/T1h-JSONL (spår A).

Läser frysta mätrader ``{t, wall, players:[{ent, origin, on_ground}]}`` och
skriver stämplade rader enligt radkontraktet (Fables synkbeslut). A äger
rotfälten; nyckeln ``plan`` är reserverad åt B och skrivs aldrig här.

Radkontrakt (A):
  {"t": <3 dec>, "bot": <ent>, "cell": <u32|4294967295>, "verdict": <str>,
   "schema": "qw-nav-graph/1", "graph_stamp": "<u64 decimalsträng>"}

Radlagret: inga null; sentinel 4294967295 = okänd cell (luft/missing).
Domlagret (attributionssammanfattningen): explicit "unknown", aldrig sentinel.
Decimalkontrakt: t 3 dec, ingen exponentform.

Två identitetsnivåer (se WORK_LOGS/graphstamp-kontrakt.md):
- nivå 1 ``graph_stamp`` (FNV-1a-64 över counts) — billig per-rad-pin.
- nivå 2 ``graph_content_hash`` (SHA-256 över kanonisk inventering) —
  strukturidentitet, ALDRIG per rad; emitteras i .attr-sidovagnen.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

from live_bridge import Attribution, GraphContract, GraphMatcher

U32_MAX = 4294967295
FNV_OFFSET = 0xcbf29ce484222325
FNV_PRIME = 0x100000001b3
MASK64 = 0xFFFFFFFFFFFFFFFF
SCHEMA = "qw-nav-graph/1"


def fnv1a64(data: bytes) -> int:
    h = FNV_OFFSET
    for b in data:
        h ^= b
        h = (h * FNV_PRIME) & MASK64
    return h


def graph_stamp(map_name: str, cells: int, links: int, rj_links: int) -> int:
    """Nivå 1: FNV-1a-64 över (map_utf8 ++ LE32(cells) ++ LE32(links) ++ LE32(rj_links))."""
    return fnv1a64(map_name.encode("utf-8") + struct.pack("<III", cells, links, rj_links))


def canonical_inventory(doc: dict) -> bytes:
    """Nivå 2: kanonisk inventering — byte-stabil, oberoende av link-id.

    Celler sorterade på id med origin (int()-trunkering mot noll, mkgraph-
    beteende); ALLA riktade länkar (inkl. rensade ur adjacensen) sorterade på
    (source, target, kind, traversable), var och en med traverserbarhetsflagga
    T (1 = i adjacensen, 0 = rensad). Raketjump-länkar är L-poster med
    kind=rocketjump (ingen separat R-sektion).
    Separator: tab mellan fält, LF mellan poster, ingen avslutande LF.
    """
    lines = []
    for cid, c in sorted(zip(doc["cell_ids"], doc["cells"])):
        lines.append(f"C\t{cid}\t{int(c[0])}\t{int(c[1])}\t{int(c[2])}")
    lrecs = []
    for l in doc["links"]:
        t = l.get("T", l.get("traversable", 1))
        t = 0 if t in (0, False) else 1
        lrecs.append((int(l["from"]), int(l["to_cell"]), str(l["kind"]).lower(), t))
    lrecs.sort()
    for src, dst, kind, t in lrecs:
        lines.append(f"L\t{src}\t{dst}\t{kind}\t{t}")
    return "\n".join(lines).encode("utf-8")


def graph_content_hash(doc: dict) -> str:
    """Nivå 2: SHA-256 (hex) över kanonisk inventering — strukturidentitet.

    SHA-256 (inte FNV-1a-64) eftersom nivå 2 är en strukturell domgrind
    (structural_missing_link får bara avges mot matchande nivå 2) och en
    icke-kryptografisk 64-bit-hash inte ger den kollisionsresistensen.
    """
    return hashlib.sha256(canonical_inventory(doc)).hexdigest()


def _build_graph_from_doc(d: dict, path: Path) -> GraphContract:
    raw = Path(path).read_bytes()
    cells = [list(c) for c in d["cells"]]
    cell_ids = [int(x) for x in d["cell_ids"]]
    id_to_idx = {cid: i for i, cid in enumerate(cell_ids)}
    links: list[list] = []
    link_ids: list[int] = []
    links_by_cells: dict[tuple[int, int], list[int]] = {}
    for lid, lk in zip(d["link_ids"], d["links"]):
        if lk.get("T", 1) == 0:
            continue  # rensad ur adjacensen (teleport-trigger) — ej traverserbar
        src = int(lk["from"])
        dst = int(lk["to_cell"])
        kind = str(lk["kind"])
        cost = float(lk.get("cost", 0.0))
        links.append([id_to_idx[src], id_to_idx[dst], kind, cost])
        link_ids.append(int(lid))
        links_by_cells.setdefault((src, dst), []).append(int(lid))
    return GraphContract(
        path=Path(path),
        name=str(d.get("map", "dm3")),
        sha256=hashlib.sha256(raw).hexdigest()[:16],
        cells=cells,
        links=links,
        cell_ids=cell_ids,
        link_ids=link_ids,
        links_by_cells={k: tuple(sorted(v)) for k, v in links_by_cells.items()},
        cell_z_by_id={cid: float(c[2]) for cid, c in zip(cell_ids, cells)},
        cell_by_id={cid: c for cid, c in zip(cell_ids, cells)},
    )


def load_dm3_graph(path: str | Path) -> GraphContract:
    """Läser dm3-dumpen (länkar som dict) och bygger ett GraphContract."""
    p = Path(path)
    raw = p.read_bytes()
    d = json.loads(raw)
    if d.get("schema") != SCHEMA:
        raise ValueError(f"ogiltigt schema {d.get('schema')!r}")
    return _build_graph_from_doc(d, p)


def load_dm3_doc(path: str | Path) -> dict:
    """Rå dump-dict (för nivå 2-hash + grafen)."""
    d = json.loads(Path(path).read_bytes())
    if d.get("schema") != SCHEMA:
        raise ValueError(f"ogiltigt schema {d.get('schema')!r}")
    return d


def stamp_rows(in_path, out_path, graph: GraphContract, stamp: int, bot_ent: int = 1):
    """Stämplar varje rad i in_path. Returnerar (n_rader, Attribution)."""
    matcher = GraphMatcher(graph)
    state = Attribution()
    out_lines = []
    n = 0
    with open(in_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            t = float(row["t"])
            for p in row.get("players", []):
                ent = int(p["ent"])
                if ent != bot_ent:
                    continue
                on_ground = bool(p["on_ground"])
                if on_ground:
                    cell, verdict = matcher.classify(p["origin"])
                    if cell is None:
                        cell_out, verdict_out = U32_MAX, "missing"
                        state.note_missing_landing(p["origin"])
                    else:
                        cell_out, verdict_out = int(cell), verdict
                        state.observe(cell_out, t, graph)
                else:
                    cell_out, verdict_out = U32_MAX, "airborne"
                    state.note_airborne()
                out_lines.append(json.dumps({
                    "t": round(t, 3),
                    "bot": ent,
                    "cell": cell_out,
                    "verdict": verdict_out,
                    "schema": SCHEMA,
                    "graph_stamp": str(stamp),
                }, separators=(",", ":")))
                n += 1
    Path(out_path).write_text("\n".join(out_lines) + ("\n" if out_lines else ""))
    return n, state


def _link_desc(link_id, graph: GraphContract):
    if link_id is None or link_id not in graph.link_ids:
        return "unknown"
    idx = graph.link_ids.index(link_id)
    link = graph.links[idx]
    return {
        "from": int(graph.cell_ids[int(link[0])]),
        "to": int(graph.cell_ids[int(link[1])]),
        "kind": str(link[2]),
    }


def attribution_summary(state: Attribution, graph: GraphContract) -> dict:
    """Domlagret: attributionsytan per försök, explicit "unknown" (aldrig sentinel)."""
    landing = state.drop_landing_cell
    return {
        "attribution": {
            "cell_id": landing if landing is not None else "unknown",
            "cell_origin": graph.cell_by_id.get(landing, "unknown") if landing is not None else "unknown",
            "link": _link_desc(state.drop_link_id, graph),
        },
        "drop_from_cell": state.drop_from_cell if state.drop_from_cell is not None else "unknown",
        "start_cell": state.start_cell if state.start_cell is not None else "unknown",
        "used_cells": sorted(state.used_cells),
        "used_links": sorted(state.used_links),
        "missing": state.missing_payload(),
    }


def stamp_file(in_path, out_path, attr_path, graph: GraphContract, stamp: int,
               content_hash: str | None = None, bot_ent: int = 1) -> dict:
    n, state = stamp_rows(in_path, out_path, graph, stamp, bot_ent)
    summary = attribution_summary(state, graph)
    summary["n_rader"] = n
    summary["graph_stamp"] = str(stamp)
    # nivå 2 endast i sidovagnen, ALDRIG per rad
    if content_hash is not None:
        summary["graph_content_hash"] = content_hash
    if attr_path is not None:
        Path(attr_path).write_text(json.dumps(summary, ensure_ascii=False))
    return summary


def main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="spår A offline-stämpling")
    ap.add_argument("--graph", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--cells", type=int, required=True)
    ap.add_argument("--links", type=int, required=True)
    ap.add_argument("--rj", type=int, required=True)
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    ap.add_argument("--attr", dest="attr_path", default=None)
    ap.add_argument("--bot", type=int, default=1)
    a = ap.parse_args(argv)
    doc = load_dm3_doc(a.graph)
    graph = _build_graph_from_doc(doc, Path(a.graph))
    stamp = graph_stamp(a.map, a.cells, a.links, a.rj)
    content_hash = graph_content_hash(doc)
    summary = stamp_file(a.in_path, a.out_path, a.attr_path, graph, stamp,
                         content_hash, a.bot)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
