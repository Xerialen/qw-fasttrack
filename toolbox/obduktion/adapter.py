"""Läs mätserie. Stämplar tas om de finns; annars explicit unknown."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

from .dump import cell_str, lank_str, q, q_xyz

STAMP_CELL_KEYS = ("cell_id", "cell")
STAMP_LINK_KEYS = ("link_id", "link", "lank", "aktiv_lank", "chosen_link")
# Spår A:s stämpelrad bär kontraktsnamnet i "schema" och grafidentiteten i "graph_stamp"
# (decimalsträng — u64 överstiger 2^53 och skulle tappa precision som JSON-tal).
# "graph_contract" och "navmesh_stamp" är de äldre namnen och läses först.
STAMP_CONTRACT_KEYS = ("graph_contract", "schema")
STAMP_ID_KEYS = ("graph_stamp",)
T1H_CYKEL = re.compile(r"^c(\d{3})$")
T1H_BEN = ("ut_ring", "in_ring", "ut_tunnel", "in_tunnel", "ut_vast", "in_vast")
ATTEMPT = re.compile(r"^attempt_(\d+)\.jsonl$")
META_SKIP = frozenset({"ogiltig_tic", "kasserad"})


def _first(d: dict, keys: tuple[str, ...]):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def stamp_id_str(value) -> str | None:
    """Grafidentiteten som sträng. u64 skrivs som decimalsträng i JSONL (kontraktet §4)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else str(value)
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


def extract_stamp(row: dict, player: dict | None = None,
                  ref_stamp: str | None = None) -> dict:
    """Plocka stämpel från rad och ev. player-objekt. Gissar aldrig xyz.

    När `ref_stamp` är satt valideras radens `graph_stamp` mot den. En rad som
    bär en ANNAN graf får sin cell- och länkbindning nollställd till
    ``"unknown"``: ett cell-id är bara ett namn på en cell *inom en graf*, så
    att behålla bindningen vore att peka ut fel plats med full säkerhet. Vi
    gissar inte vilken graf som är rätt — vi vägrar binda.
    """
    sources = []
    if player:
        sources.append(player)
    sources.append(row)
    cell = "unknown"
    lank = "unknown"
    stamp = None
    contract = None
    graph_stamp = None
    plan = None
    verdict = None
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
        if contract is None:
            contract = _first(src, STAMP_CONTRACT_KEYS)
        if graph_stamp is None:
            graph_stamp = stamp_id_str(_first(src, STAMP_ID_KEYS))
        # Spår B:s planerartelemetri. Ren genomsläppning: fälten tolkas inte här,
        # och särskilt görs INGEN sentinelöversättning. B:s signerade fält
        # (runway, sj_progress, first_air_vz) bär sin frånvaro i egna
        # *_measured-flaggor just för att -1.0 och 0.0 är giltiga avläsningar;
        # den som "städar" dem här återinför buggen B redan har rättat.
        if plan is None and isinstance(src.get("plan"), dict):
            plan = src["plan"]
        # A:s attributionsdom för ticken (covered/airborne/off_grid/missing).
        # Genomsläppning, ingen tolkning: den förklarar VARFÖR en tick saknar
        # cell — en luftburen tick bär sentinelen 4294967295 därför att boten
        # inte står i någon cell, vilket är något helt annat än att stämplingen
        # missade. Domlagret behöver kunna skilja de två.
        if verdict is None and isinstance(src.get("verdict"), str):
            verdict = src["verdict"]

    avvik = bool(ref_stamp and graph_stamp and graph_stamp != ref_stamp)
    if avvik:
        cell = "unknown"
        lank = "unknown"
    bind = "stamped" if cell != "unknown" else "unknown"
    return {
        "cell": cell,
        "lank": lank,
        "bind": bind,
        "navmesh_stamp": stamp,
        "graph_contract": contract,
        "graph_stamp": graph_stamp,
        "stamp_avvik": avvik,
        "plan": plan,
        "verdict": verdict,
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
               serie: Path | None = None,
               ref_stamp: str | None = None) -> Iterator[dict]:
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
            yield from _ticks_from_row(row, ent, i, ref_stamp)


def _ticks_from_row(row: dict, ent: int, idx: int,
                    ref_stamp: str | None = None) -> Iterator[dict]:
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
        stamp = extract_stamp(row, picked, ref_stamp)
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
        stamp = extract_stamp(ev, None, ref_stamp)
        stamp2 = extract_stamp(row, None, ref_stamp)
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
    ref = forsok.get("_arm_stamp", forsok.get("ref_stamp"))
    return list(iter_ticks(forsok["jsonl"], forsok["ent"],
                           forsok.get("stamplar"), forsok.get("serie"), ref))


def load_attr(forsok: dict) -> dict:
    """Spår A:s per-försöks-attribution (``<ben>.attr.json``), eller tomt.

    A kör GraphMatcher över hela försöket och skriver ned var det faktiskt tog
    slut — ``attribution.cell_id`` samt ``drop_from_cell``/``start_cell``. Det
    är en annan fråga än "vilken cell stod boten i på den här ticken", och det
    är den fråga en fallbindning ska ställa: ett fall triggar på en luftburen
    tick, vars cell är den boten *lämnade*, inte den den landade i.

    Adaptern läser filen och lägger den på försöket. Den binder inte själv —
    klassningen äger den kopplingen (spår I).
    """
    stamplar = forsok.get("stamplar")
    jsonl = forsok.get("jsonl")
    serie = forsok.get("serie")
    if not jsonl:
        return {}
    cands = [jsonl.with_name(jsonl.stem + ".attr.json")]
    if stamplar is not None:
        if serie is not None:
            try:
                rel = jsonl.relative_to(serie)
                cands.append((stamplar / rel).with_name(jsonl.stem + ".attr.json"))
            except ValueError:
                cands.append(stamplar / f"{jsonl.stem}.attr.json")
        else:
            cands.append(stamplar / f"{jsonl.stem}.attr.json")
    for c in cands:
        if c.is_file():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
    return {}


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


def n_hela_per_arm(forsok: list[dict]) -> dict[str, int]:
    """Högsta cykelnummer där alla sex T1h-ben finns, per arm (konsekutivt från 1)."""
    by_arm: dict[str, dict[int, set[str]]] = {}
    for f in forsok:
        if f.get("layout") != "t1h" or f.get("cykel") is None:
            continue
        by_arm.setdefault(f["arm"], {}).setdefault(f["cykel"], set()).add(f["ben"])
    out: dict[str, int] = {}
    for arm, cycles in by_arm.items():
        n = 0
        c = 1
        while c in cycles and set(T1H_BEN) <= cycles[c]:
            n = c
            c += 1
        if n:
            out[arm] = n
    return out


def apply_kap(forsok: list[dict]) -> tuple[list[dict], dict]:
    """Kapa till N = min(n_hela) när minst en arm har hela cykler."""
    hela = n_hela_per_arm(forsok)
    if not hela:
        return list(forsok), {
            "n": None,
            "per_arm": {},
            "kastade_cykler": {},
        }
    n = min(hela.values())
    kept = []
    kastade: dict[str, list[int]] = {arm: [] for arm in hela}
    seen_drop: dict[str, set[int]] = {arm: set() for arm in hela}
    for f in forsok:
        if f.get("layout") == "t1h" and f.get("cykel") is not None and f["cykel"] > n:
            arm = f["arm"]
            seen_drop.setdefault(arm, set()).add(f["cykel"])
            continue
        kept.append(f)
    for arm, cyk in seen_drop.items():
        kastade[arm] = sorted(cyk)
    return kept, {
        "n": n,
        "per_arm": {k: hela[k] for k in sorted(hela)},
        "kastade_cykler": {k: kastade.get(k, []) for k in sorted(hela)},
    }


def _manifest_stamps(stamplar: Path | None, serie: Path | None):
    """Per-arm grafidentiteter ur A:s manifest. Returnerar {arm: (stamp, schema)}.

    Omstämplade manifestet bär ``per_arm`` (två armar = två identiteter). Äldre
    manifest bar en enda top-level ``graph_stamp`` och mappas som ``"*"``
    (wildcard: gäller alla armar).
    """
    for base in (stamplar, serie):
        if base is None:
            continue
        p = base / "manifest.json"
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        per_arm = data.get("per_arm")
        if isinstance(per_arm, dict):
            out = {}
            for arm, v in per_arm.items():
                if isinstance(v, dict):
                    s = stamp_id_str(v.get("graph_stamp"))
                    if s:
                        out[str(arm)] = (s, v.get("schema"))
            if out:
                return out
        s = stamp_id_str(data.get("graph_stamp"))
        if s:
            return {"*": (s, data.get("schema"))}
    return None


def _arm_ref(forsok: dict, referenser: dict) -> str | None:
    """Stampen ett försök ska valideras mot: dess arms, annars wildcard."""
    entry = referenser.get(forsok.get("arm"), referenser.get("*"))
    if entry is None:
        return None
    return None if entry[0] == "unknown" else entry[0]


def resolve_graph_stamp(forsok: list[dict], stamplar: Path | None,
                        serie: Path | None) -> dict:
    """Per-arm referens: manifestets ``per_arm`` först, rader per arm sedan.

    Varje försök får ``_arm_stamp`` satt här (sin arms stamp); ``load_ticks``
    läser det. Konflikt = två olika stamps INOM samma arm — den armen lämnas
    ovaliderad (``_arm_stamp=None``). Två armar med olika stamps är INTE en
    konflikt; det är per-arm-designen.
    """
    mani = _manifest_stamps(stamplar, serie)
    if mani is not None:
        referenser = dict(mani)
        kalla = "manifest"
    else:
        referenser = {}
        kalla = "rader"
        by_arm: dict[str, list[dict]] = {}
        for f in forsok:
            by_arm.setdefault(f.get("arm") or "?", []).append(f)
        konflikt = False
        nagon_stamp = False
        for arm, flist in by_arm.items():
            seen: set[str] = set()
            for f in flist:
                for tk in iter_ticks(f["jsonl"], f["ent"],
                                     f.get("stamplar"), f.get("serie")):
                    gs = tk.get("graph_stamp")
                    if gs:
                        seen.add(gs)
                        if len(seen) > 1:
                            break
                if len(seen) > 1:
                    break
            if len(seen) == 1:
                referenser[arm] = (next(iter(seen)), None)
                nagon_stamp = True
            elif len(seen) > 1:
                referenser[arm] = ("unknown", None)
                konflikt = True
            else:
                referenser[arm] = ("unknown", None)
        if konflikt:
            kalla = "konflikt"
        elif nagon_stamp:
            kalla = "rader"
        else:
            kalla = "ingen"

    for f in forsok:
        f["_arm_stamp"] = _arm_ref(f, referenser)

    vals = [v[0] for v in referenser.values()]
    if vals and all(v == vals[0] and v != "unknown" for v in vals):
        top = vals[0]
    else:
        top = "unknown"
    schema = next((v[1] for v in referenser.values() if v[1]), None)
    return {
        "referens": top,
        "kalla": kalla,
        "schema": schema,
        "per_arm": {arm: v[0] for arm, v in referenser.items()},
    }


def population_etikett(kind: str, n_kap: int | None) -> str:
    suffix = f"N{n_kap}" if n_kap is not None else "Nall"
    return f"{kind}_{suffix}"


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
