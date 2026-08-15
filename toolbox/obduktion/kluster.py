"""Klustring per (cell, länk, klass); rumslig split när cell är unknown."""
from __future__ import annotations

import math

from .dump import ATGARD_KLASSER, LOCUS_RADIE, q, q_xyz


def _dist(a, b) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _centroid(origins: list[list[float]]) -> list[float]:
    n = len(origins)
    return [sum(o[i] for o in origins) / n for i in range(3)]


def _handelse_sort_key(ev: dict):
    o = ev.get("origin") or [0, 0, 0]
    t = ev.get("t")
    tkey = t if t is not None else -1e99
    return (ev.get("forsok_id") or "", tkey, ev.get("klass") or "",
            o[0], o[1], o[2])


def tilldela_handelse_id(events: list[dict]) -> list[dict]:
    ordered = sorted(events, key=_handelse_sort_key)
    out = []
    for i, ev in enumerate(ordered, 1):
        row = dict(ev)
        row["_sort"] = i
        out.append(row)
    return out


def klustra(handelser: list[dict]) -> list[dict]:
    """handelser ska redan ha kanoniska fält (id, origin avrundad)."""
    stamped: dict[tuple, list[dict]] = {}
    unknown: list[dict] = []
    for ev in handelser:
        if ev["cell"] != "unknown":
            key = (ev["cell"], ev["lank"], ev["klass"])
            stamped.setdefault(key, []).append(ev)
        else:
            unknown.append(ev)
    unknown.sort(key=lambda e: e["id"])

    raw: list[list[dict]] = list(stamped.values())
    # greedy närmaste-centroid, radie 64, samma (klass, lank)
    buckets: list[dict] = []
    for ev in unknown:
        best_i = None
        best_d = None
        for i, b in enumerate(buckets):
            if b["klass"] != ev["klass"] or b["lank"] != ev["lank"]:
                continue
            d = _dist(ev["origin"], b["centroid"])
            if d <= LOCUS_RADIE and (best_d is None or d < best_d
                                     or (d == best_d and i < (best_i or 0))):
                best_i, best_d = i, d
        if best_i is None:
            buckets.append({
                "klass": ev["klass"],
                "lank": ev["lank"],
                "members": [ev],
                "centroid": list(ev["origin"]),
            })
        else:
            b = buckets[best_i]
            b["members"].append(ev)
            b["centroid"] = _centroid([m["origin"] for m in b["members"]])

    raw.extend(b["members"] for b in buckets)
    return [_kluster_from(members) for members in raw]


def _kluster_from(members: list[dict]) -> dict:
    origins = [m["origin"] for m in members]
    c = _centroid(origins)
    sprid = max(_dist(o, c) for o in origins) if origins else 0.0
    cells = {m["cell"] for m in members}
    lanks = {m["lank"] for m in members}
    klasser = {m["klass"] for m in members}
    # stamped-grupper är homogena; unknown-grupper också per konstruktion
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
    # åtgärdskandidater först (samma ordning som atgarder), sen övriga
    flag = 0 if k["atgard_kandidat"] else 1
    return (flag, -k["n_forsok"], -k["n_handelser"],
            k["klass"], k["cell"], k["lank"],
            k["centroid"][0], k["centroid"][1], k["centroid"][2])


def numrera_och_prioritera(kluster: list[dict]) -> tuple[list[dict], list[dict]]:
    ordered = sorted(kluster, key=_kluster_sort_key)
    numbered = []
    for i, k in enumerate(ordered, 1):
        row = dict(k)
        row["kluster_id"] = f"K{i:04d}"
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
