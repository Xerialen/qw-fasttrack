"""Händelseklassning. peak_drop_150-paritet med timtest_ben.py:98–107."""
from __future__ import annotations

import json
from pathlib import Path

from .dump import cell_str, lank_str, q, q_xyz

PEAK_DROP = 150.0


def _load_attr(forsok: dict) -> dict | None:
    """Sidovagn: per-försöks-.attr.json (spår A). Primär input är mät-JSONL."""
    cands: list[Path] = []
    jsonl = forsok.get("jsonl")
    if jsonl:
        p = Path(jsonl)
        cands.append(p.with_name(p.stem + ".attr.json"))
    stamplar = forsok.get("stamplar")
    serie = forsok.get("serie")
    if stamplar and jsonl and serie:
        try:
            rel = Path(jsonl).relative_to(serie)
            stem = rel.with_name(rel.stem + ".attr.json")
            cands.append(Path(stamplar) / stem)
        except ValueError:
            cands.append(Path(stamplar) / (Path(jsonl).stem + ".attr.json"))
    for c in cands:
        if c.is_file():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def _attr_landing_cell(attr: dict | None) -> tuple[str, str]:
    """(cell, bind) ur A:s attribution.cell_id / drop_landing_cell."""
    if not attr:
        return "unknown", "unknown"
    att = attr.get("attribution") or {}
    cid = att.get("cell_id")
    if cid is None:
        cid = attr.get("drop_landing_cell")
    if cid is None or cid == "unknown":
        return "unknown", "unknown"
    s = cell_str(cid)
    return s, ("stamped" if s != "unknown" else "unknown")


def _first_grounded_after(ticks: list[dict], start_i: int) -> dict | None:
    for tk in ticks[start_i + 1:]:
        if tk.get("on_ground") is True and tk.get("origin"):
            return tk
    return None


def _bind_landing(ticks: list[dict], trigger_i: int, trigger: dict,
                  drop_u: float, klass: str, attr: dict | None) -> dict:
    """Bind till första grounded tick efter droppen, annars A-attr."""
    land = trigger if trigger.get("on_ground") is True else None
    if land is None:
        land = _first_grounded_after(ticks, trigger_i)
    if land is not None:
        cell = land.get("cell") or "unknown"
        lank = land.get("lank") or "unknown"
        bind = land.get("bind") or "unknown"
        if cell == "unknown":
            ac, ab = _attr_landing_cell(attr)
            if ac != "unknown":
                cell, bind = ac, ab
        o = land.get("origin") or trigger.get("origin")
        return {
            "klass": klass,
            "t": land.get("t"),
            "origin": list(o),
            "cell": cell,
            "lank": lank,
            "bind": bind,
            "drop_u": drop_u,
            "stall_reason": None,
            "tick": land,
        }
    ac, ab = _attr_landing_cell(attr)
    o = trigger.get("origin")
    return {
        "klass": klass,
        "t": trigger.get("t"),
        "origin": list(o) if o else None,
        "cell": ac,
        "lank": "unknown",
        "bind": ab,
        "drop_u": drop_u,
        "stall_reason": None,
        "tick": trigger,
    }


def peak_drop_events(ticks: list[dict], undanta_ut: bool,
                     attr: dict | None = None) -> list[dict]:
    """peak_drop_150 med harness-paritet (timtest_ben.py:98–107).

    IN (undanta_ut=False): räkna fall och återställ peak efter varje slag.
    UT (undanta_ut=True): peak återställs ALDRIG; högst en avsett_drop
    per försök (första korsningen). Bindning = landning, inte lufttick.
    """
    out = []
    peak = -9e9
    emitted_avsett = False
    for i, tk in enumerate(ticks):
        o = tk.get("origin")
        if not o or len(o) < 3:
            continue
        z = float(o[2])
        if z > peak:
            peak = z
        elif peak - z > PEAK_DROP:
            if undanta_ut:
                if not emitted_avsett:
                    ev = _bind_landing(ticks, i, tk, peak - z, "avsett_drop", attr)
                    if ev.get("origin"):
                        out.append(ev)
                    emitted_avsett = True
                # peak orörd — samma som harnessens elif som aldrig tas
            else:
                ev = _bind_landing(ticks, i, tk, peak - z, "fall", attr)
                if ev.get("origin"):
                    out.append(ev)
                peak = z
    return out


def stall_events(ticks: list[dict]) -> list[dict]:
    """Stall utan origin emitteras inte (ingen klusterplats vid världsorigo)."""
    out = []
    for tk in ticks:
        ev = tk.get("stall_event")
        row = tk.get("row") or {}
        if ev is None and row.get("ev") == "bot_stall":
            ev = row
        if ev is None and isinstance(row.get("stall"), dict):
            ev = row["stall"]
        if not ev:
            continue
        origin = tk.get("origin") or ev.get("origin") or ev.get("pos")
        if not origin or len(origin) < 3:
            continue
        reason = ev.get("reason")
        out.append({
            "klass": "stall",
            "t": ev.get("t", tk.get("t")),
            "origin": list(origin),
            "cell": cell_from_ev(ev, tk),
            "lank": lank_from_ev(ev, tk),
            "bind": "stamped" if cell_from_ev(ev, tk) != "unknown" else "unknown",
            "drop_u": None,
            "stall_reason": reason if reason is not None else "unknown",
            "tick": tk,
        })
    return out


def cell_from_ev(ev: dict, tk: dict) -> str:
    if ev.get("cell") is not None:
        return cell_str(ev.get("cell"))
    return tk.get("cell") or "unknown"


def lank_from_ev(ev: dict, tk: dict) -> str:
    if ev.get("link") is not None:
        return lank_str(ev.get("link"))
    if ev.get("lank") is not None:
        return lank_str(ev.get("lank"))
    return tk.get("lank") or "unknown"


def endpoint_event(ticks: list[dict], klass: str) -> dict | None:
    """fastnad/timeout vid sista tick med origin — ingen origo-placeholder."""
    for tk in reversed(ticks):
        o = tk.get("origin")
        if o and len(o) >= 3:
            return {
                "klass": klass,
                "t": tk.get("t"),
                "origin": list(o),
                "cell": tk.get("cell") or "unknown",
                "lank": tk.get("lank") or "unknown",
                "bind": tk.get("bind") or "unknown",
                "drop_u": None,
                "stall_reason": None,
                "tick": tk,
            }
    return None


def klassa_forsok(forsok: dict, ticks: list[dict]) -> list[dict]:
    attr = _load_attr(forsok)
    events = []
    events.extend(peak_drop_events(ticks, forsok.get("undanta_ut", False), attr))
    events.extend(stall_events(ticks))
    utfall = forsok.get("utfall")
    if utfall == "timeout":
        ev = endpoint_event(ticks, "timeout")
        if ev:
            events.append(ev)
    elif utfall in ("fastnad", "fall_plus_fastnad"):
        ev = endpoint_event(ticks, "fastnad")
        if ev:
            events.append(ev)
    out = []
    for ev in events:
        if not ev.get("origin"):
            continue
        out.append({
            "forsok_id": forsok["forsok_id"],
            "arm": forsok["arm"],
            "ben": forsok["ben"],
            "cykel": forsok.get("cykel"),
            "klass": ev["klass"],
            "cell": ev["cell"],
            "lank": ev["lank"],
            "bind": ev["bind"],
            "t": ev["t"],
            "origin": ev["origin"],
            "regim": forsok["regim"],
            "drop_u": ev["drop_u"],
            "stall_reason": ev["stall_reason"],
            "meta_utfall": utfall,
            "navmesh_stamp": (ev.get("tick") or {}).get("navmesh_stamp"),
            "graph_contract": (ev.get("tick") or {}).get("graph_contract"),
        })
    return out


def finalize_handelse(ev: dict, hid: str) -> dict:
    stall_reason = ev["stall_reason"]
    if ev["klass"] != "stall":
        stall_reason = None
    elif stall_reason is None:
        stall_reason = "unknown"
    return {
        "id": hid,
        "forsok_id": ev["forsok_id"],
        "arm": ev["arm"],
        "ben": ev["ben"],
        "cykel": ev["cykel"],
        "klass": ev["klass"],
        "cell": ev["cell"] if ev["cell"] is not None else "unknown",
        "lank": ev["lank"] if ev["lank"] is not None else "unknown",
        "bind": ev["bind"] if ev["bind"] in ("stamped", "unknown") else "unknown",
        "t": q(ev["t"], 3),
        "origin": q_xyz(ev["origin"]),
        "regim": ev["regim"],
        "drop_u": q(ev["drop_u"], 1),
        "stall_reason": stall_reason,
        "meta_utfall": ev.get("meta_utfall"),
    }
