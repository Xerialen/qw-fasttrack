"""Händelseklassning. peak_drop_150 återanvänds i samma semantik som harnessen."""
from __future__ import annotations

from .dump import q, q_xyz

PEAK_DROP = 150.0


def peak_drop_events(ticks: list[dict], undanta_ut: bool) -> list[dict]:
    """Samma reset-regel som timtest_ben.fall_peak_drop_150, men emitterar
    platsen där Δz slog. undanta_ut ⇒ avsett_drop i stället för fall."""
    out = []
    peak = -9e9
    for tk in ticks:
        o = tk.get("origin")
        if not o or len(o) < 3:
            continue
        z = float(o[2])
        if z > peak:
            peak = z
        elif peak - z > PEAK_DROP:
            klass = "avsett_drop" if undanta_ut else "fall"
            out.append({
                "klass": klass,
                "t": tk.get("t"),
                "origin": list(o),
                "cell": tk["cell"],
                "lank": tk["lank"],
                "bind": tk["bind"],
                "drop_u": peak - z,
                "stall_reason": None,
                "tick": tk,
            })
            peak = z
    return out


def stall_events(ticks: list[dict]) -> list[dict]:
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
        reason = ev.get("reason")
        out.append({
            "klass": "stall",
            "t": ev.get("t", tk.get("t")),
            "origin": list(origin) if origin else [0.0, 0.0, 0.0],
            "cell": cell_from_ev(ev, tk),
            "lank": lank_from_ev(ev, tk),
            "bind": "stamped" if cell_from_ev(ev, tk) != "unknown" else "unknown",
            "drop_u": None,
            "stall_reason": reason if reason is not None else "unknown",
            "tick": tk,
        })
    return out


def cell_from_ev(ev: dict, tk: dict) -> str:
    from .dump import cell_str
    if ev.get("cell") is not None:
        return cell_str(ev.get("cell"))
    return tk.get("cell") or "unknown"


def lank_from_ev(ev: dict, tk: dict) -> str:
    from .dump import lank_str
    if ev.get("link") is not None:
        return lank_str(ev.get("link"))
    if ev.get("lank") is not None:
        return lank_str(ev.get("lank"))
    return tk.get("lank") or "unknown"


def endpoint_event(ticks: list[dict], klass: str) -> dict | None:
    """fastnad/timeout vid sista tick — gissar inte om det saknas ticks."""
    if not ticks:
        return None
    tk = ticks[-1]
    o = tk.get("origin") or [0.0, 0.0, 0.0]
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


def klassa_forsok(forsok: dict, ticks: list[dict]) -> list[dict]:
    events = []
    events.extend(peak_drop_events(ticks, forsok.get("undanta_ut", False)))
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
    # K-serien: utfall timeout redan hanterad; "ok" med falls ger bara peak_drop
    out = []
    for ev in events:
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
