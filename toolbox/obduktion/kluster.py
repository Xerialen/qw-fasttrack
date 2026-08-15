"""Klustring per (cell, länk, klass); unknown bär även (arm, ben)."""
from __future__ import annotations

import math

from .dump import ATGARD_KLASSER, LOCUS_RADIE, q, q_xyz


def _dist(a, b) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _centroid(origins: list[list[float]]) -> list[float]:
    n = len(origins)
    return [sum(o[i] for o in origins) / n for i in range(3)]


def _has_origin(ev: dict) -> bool:
    o = ev.get("origin")
    return bool(o) and len(o) >= 3


def _handelse_sort_key(ev: dict):
    o = ev.get("origin") if _has_origin(ev) else (1e9, 1e9, 1e9)
    t = ev.get("t")
    tkey = t if t is not None else -1e99
    return (ev.get("forsok_id") or "", tkey, ev.get("klass") or "",
            o[0], o[1], o[2])


def tilldela_handelse_id(events: list[dict], prefix: str = "H") -> list[dict]:
    ordered = sorted(events, key=_handelse_sort_key)
    out = []
    for i, ev in enumerate(ordered, 1):
        row = dict(ev)
        row["_sort"] = i
        row["_id_prefix"] = prefix
        out.append(row)
    return out


def _spatial_split(evs: list[dict]) -> list[list[dict]]:
    """Greedy centroid-kluster, radie 64. evs redan samma (arm, ben, lank, klass)."""
    buckets: list[dict] = []
    for ev in evs:
        best_i = None
        best_d = None
        for i, b in enumerate(buckets):
            d = _dist(ev["origin"], b["centroid"])
            if d <= LOCUS_RADIE and (best_d is None or d < best_d
                                     or (d == best_d and i < (best_i or 0))):
                best_i, best_d = i, d
        if best_i is None:
            buckets.append({
                "members": [ev],
                "centroid": list(ev["origin"]),
            })
        else:
            b = buckets[best_i]
            b["members"].append(ev)
            b["centroid"] = _centroid([m["origin"] for m in b["members"]])
    return [b["members"] for b in buckets]


def klustra(handelser: list[dict]) -> list[dict]:
    """handelser ska redan ha kanoniska fält (id, origin avrundad)."""
    stamped: dict[tuple, list[dict]] = {}
    unknown: dict[tuple, list[dict]] = {}
    for ev in handelser:
        if ev["cell"] != "unknown":
            key = (ev["cell"], ev["lank"], ev["klass"])
            stamped.setdefault(key, []).append(ev)
        else:
            key = (ev.get("arm") or "?", ev.get("ben") or "?",
                   ev["lank"], ev["klass"])
            unknown.setdefault(key, []).append(ev)

    raw: list[list[dict]] = [stamped[k] for k in sorted(stamped)]
    for key in sorted(unknown):
        evs = sorted((e for e in unknown[key] if _has_origin(e)),
                     key=lambda e: e["id"])
        if evs:
            raw.extend(_spatial_split(evs))
    return [_kluster_from(members) for members in raw]


def _uniq_or_mixed(values: set[str]) -> str:
    if len(values) == 1:
        return next(iter(values))
    return "mixed"


def _kluster_from(members: list[dict]) -> dict:
    origins = [m["origin"] for m in members if _has_origin(m)]
    if not origins:
        return {
            "cell": "unknown", "lank": "unknown", "klass": members[0]["klass"],
            "bind": "unknown", "arm": "mixed", "ben": "mixed",
            "locus": [0.0, 0.0, 0.0], "centroid": [0.0, 0.0, 0.0],
            "spridning_u": 0.0, "n_handelser": len(members),
            "n_forsok": len({m["forsok_id"] for m in members}),
            "forsok_id": sorted({m["forsok_id"] for m in members}),
            "handelse_id": sorted(m["id"] for m in members),
            "atgard_kandidat": False,
        }
    c = _centroid(origins)
    sprid = max(_dist(o, c) for o in origins) if origins else 0.0
    cells = {m["cell"] for m in members}
    lanks = {m["lank"] for m in members}
    klasser = {m["klass"] for m in members}
    cell = members[0]["cell"] if len(cells) == 1 else "unknown"
    lank = members[0]["lank"] if len(lanks) == 1 else "unknown"
    klass = members[0]["klass"] if len(klasser) == 1 else "unknown"
    binds = {m["bind"] for m in members}
    bind = "stamped" if binds == {"stamped"} else "unknown"
    forsok = sorted({m["forsok_id"] for m in members})
    hids = sorted(m["id"] for m in members)
    atgard = klass in ATGARD_KLASSER
    centroid = q_xyz(c)
    return {
        "cell": cell,
        "lank": lank,
        "klass": klass,
        "bind": bind,
        "arm": _uniq_or_mixed({str(m.get("arm") or "?") for m in members}),
        "ben": _uniq_or_mixed({str(m.get("ben") or "?") for m in members}),
        "locus": centroid,
        "centroid": centroid,
        "spridning_u": q(sprid, 1),
        "n_handelser": len(members),
        "n_forsok": len(forsok),
        "forsok_id": forsok,
        "handelse_id": hids,
        "atgard_kandidat": atgard,
    }


def _kluster_sort_key(k: dict):
    flag = 0 if k["atgard_kandidat"] else 1
    return (flag, -k["n_forsok"], -k["n_handelser"],
            k["klass"], k["cell"], k["lank"], k.get("arm") or "",
            k.get("ben") or "",
            k["centroid"][0], k["centroid"][1], k["centroid"][2])


def numrera_och_prioritera(kluster: list[dict], prefix: str = "K"
                           ) -> tuple[list[dict], list[dict]]:
    ordered = sorted(kluster, key=_kluster_sort_key)
    numbered = []
    for i, k in enumerate(ordered, 1):
        row = dict(k)
        row["kluster_id"] = f"{prefix}{i:04d}"
        numbered.append(row)
    atgarder = []
    prio = 1
    for k in numbered:
        if not k["atgard_kandidat"]:
            continue
        row = dict(k)
        row["prio"] = prio
        atgarder.append(row)
        prio += 1
    return numbered, atgarder


def raknare(handelser: list[dict], kluster: list[dict], n_forsok: int) -> dict:
    klasser = ("fall", "avsett_drop", "stall", "timeout", "fastnad")
    counts = {f"n_{k}": 0 for k in klasser}
    for h in handelser:
        key = f"n_{h['klass']}"
        if key in counts:
            counts[key] += 1
    return {
        "n_forsok": n_forsok,
        "n_handelser": len(handelser),
        "n_kluster": len(kluster),
        **counts,
    }
