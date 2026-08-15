"""Händelseklassning. peak_drop_150-paritet med timtest_ben.py:98–107."""
from __future__ import annotations

from .dump import cell_str, lank_str, q, q_xyz

PEAK_DROP = 150.0
BIND_OK = frozenset({"stamped", "unknown", "fallback"})


def _first_grounded_after(ticks: list[dict], start_i: int) -> dict | None:
    for tk in ticks[start_i + 1:]:
        if tk.get("on_ground") is True and tk.get("origin"):
            return tk
    return None


def _last_known_before(ticks: list[dict], start_i: int) -> dict | None:
    """Sista grounded tick före fallet; föredra en med cell ≠ unknown."""
    found = None
    found_stamped = None
    for tk in ticks[:start_i]:
        if tk.get("on_ground") is not True or not tk.get("origin"):
            continue
        found = tk
        cell = tk.get("cell") or "unknown"
        if cell != "unknown":
            found_stamped = tk
    return found_stamped or found


def _cell_of(tk: dict) -> str:
    return tk.get("cell") or "unknown"


def _bind_landing(ticks: list[dict], trigger_i: int, trigger: dict,
                  drop_u: float, klass: str) -> dict:
    """Landningstick om den finns; annars senaste kända cell före fallet.

    Fallback märks bind=fallback (inte stamped). .attr.json läses inte —
    per-försöksattribution får inte skriva över per-händelse-bindningen.
    """
    land = trigger if trigger.get("on_ground") is True else None
    if land is None:
        land = _first_grounded_after(ticks, trigger_i)
    if land is not None:
        o = land.get("origin") or trigger.get("origin")
        return {
            "klass": klass,
            "t": land.get("t"),
            "origin": list(o),
            "cell": land.get("cell") or "unknown",
            "lank": land.get("lank") or "unknown",
            "bind": land.get("bind") or "unknown",
            "drop_u": drop_u,
            "stall_reason": None,
            "tick": land,
        }
    prev = _last_known_before(ticks, trigger_i)
    src = prev or trigger
    o = src.get("origin") or trigger.get("origin")
    cell = src.get("cell") or "unknown"
    # Fallback bara när det faktiskt finns en känd grounded cell.
    bind = "fallback" if prev is not None and cell != "unknown" else (
        src.get("bind") or "unknown")
    return {
        "klass": klass,
        "t": src.get("t"),
        "origin": list(o) if o else None,
        "cell": cell,
        "lank": src.get("lank") or "unknown",
        "bind": bind,
        "drop_u": drop_u,
        "stall_reason": None,
        "tick": src,
    }


def peak_drop_events(ticks: list[dict], undanta_ut: bool) -> list[dict]:
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
                    ev = _bind_landing(ticks, i, tk, peak - z, "avsett_drop")
                    if ev.get("origin"):
                        out.append(ev)
                    emitted_avsett = True
                # peak orörd — samma som harnessens elif som aldrig tas
            else:
                ev = _bind_landing(ticks, i, tk, peak - z, "fall")
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


def _last_origin_index(ticks: list[dict]) -> int | None:
    for i in range(len(ticks) - 1, -1, -1):
        o = ticks[i].get("origin")
        if o and len(o) >= 3:
            return i
    return None


def endpoint_event(ticks: list[dict], klass: str) -> dict | None:
    """fastnad/timeout vid sista tick med origin.

    Slutar kroppen airborne: samma _last_known_before-fallback som
    aldrig-landande fall (cell från senaste grounded, bind=fallback).
    t och origin stannar på sista ticken (där kroppen fastnade).
    Grounded missing (västvägg z=128) förblir unknown — fallbacken
    gäller bara airborne-slut, inte missing-landning. attr läses inte.
    """
    i = _last_origin_index(ticks)
    if i is None:
        return None
    tk = ticks[i]
    o = list(tk["origin"])
    cell = tk.get("cell") or "unknown"
    lank = tk.get("lank") or "unknown"
    bind = tk.get("bind") or "unknown"
    src = tk
    if tk.get("on_ground") is not True:
        prev = _last_known_before(ticks, i)
        if prev is not None and _cell_of(prev) != "unknown":
            cell = _cell_of(prev)
            lank = prev.get("lank") or "unknown"
            bind = "fallback"
            src = prev
    return {
        "klass": klass,
        "t": tk.get("t"),
        "origin": o,
        "cell": cell,
        "lank": lank,
        "bind": bind,
        "drop_u": None,
        "stall_reason": None,
        "tick": src,
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
    cell = ev["cell"] if ev["cell"] is not None else "unknown"
    raw_bind = ev["bind"]
    if cell == "unknown":
        bind = "unknown"
    elif raw_bind == "fallback":
        bind = "fallback"
    elif raw_bind == "stamped":
        bind = "stamped"
    else:
        bind = "unknown"
    return {
        "id": hid,
        "forsok_id": ev["forsok_id"],
        "arm": ev["arm"],
        "ben": ev["ben"],
        "cykel": ev["cykel"],
        "klass": ev["klass"],
        "cell": cell,
        "lank": ev["lank"] if ev["lank"] is not None else "unknown",
        "bind": bind if bind in BIND_OK else "unknown",
        "t": q(ev["t"], 3),
        "origin": q_xyz(ev["origin"]),
        "regim": ev["regim"],
        "drop_u": q(ev["drop_u"], 1),
        "stall_reason": stall_reason,
        "meta_utfall": ev.get("meta_utfall"),
    }
