#!/usr/bin/env python3
"""GPU-fri SVG-heatmap + kanonisk JSON-sammanfattning.

Laser (1) en obducera-v2-utdatafil och (2) en graf-JSON, och skriver
en SVG-heatmap (celler fargade efter misslyckade forsok per vald
population/klass) samt en kanonisk, deterministisk JSON-sammanfattning.

Ingen server, ingen riggkontakt, ren filtransformation.

  python3 heatmap.py --obduktion <fil.json> --graf <graf.json>
                     --population <etikett> --klass <klass|alla>
                     --out-svg <fil.svg> --out-json <fil.json>

Kontrakt: verktygslada/heatmap/1 (se KONTRAKT.md i denna katalog).
"""
import argparse
import json
import sys

SCHEMA = "verktygslada/heatmap/1"
KOMMANDO = "heatmap"

# Intensitetsskala (kontrakt): #10314f (t=0) -> #ffe22e (t=1).
LO = (0x10, 0x31, 0x4F)
HI = (0xFF, 0xE2, 0x2E)

PAD = 40
W = 1600
BASE_OPACITY = "0.25"
HEAT_OPACITY = "0.9"


def die(msg, code=2):
    print(f"heatmap: {msg}", file=sys.stderr)
    sys.exit(code)


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        die(f"kan inte lasa {path}: {e}")


def cell_color(t):
    r = int(LO[0] + (HI[0] - LO[0]) * t)
    g = int(LO[1] + (HI[1] - LO[1]) * t)
    b = int(LO[2] + (HI[2] - LO[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def zcolor(z, minz, maxz):
    t = 0.0 if maxz == minz else (z - minz) / (maxz - minz)
    r = int(20 + 40 * t)
    g = int(40 + 150 * t)
    b = int(70 + 120 * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def select_clusters(obd, population, klass):
    """Returnerar (karta, unknown, cellinfo).

    karta:    {cell-id-int: {"raknare": int, "kluster": {id: n},
                             "klasser": set(), "n_kluster": int}}
    unknown:  [kluster, ...] med cell == "unknown"
    """
    pops = obd.get("populationer", {})
    if population not in pops:
        die(f"population '{population}' finns inte; "
            f"tillgangliga: {sorted(pops)}")
    kluster = pops[population].get("kluster", [])

    karta = {}
    unknown = []
    for k in kluster:
        if klass != "alla" and k.get("klass") != klass:
            continue
        n = int(k.get("n_forsok", 0))
        cell = k.get("cell")
        if cell == "unknown" or cell is None:
            unknown.append(k)
            continue
        try:
            cid = int(cell)
        except ValueError:
            die(f"kluster {k.get('kluster_id')}: ej-numerisk cell '{cell}'")
        e = karta.setdefault(
            cid, {"raknare": 0, "kluster": {}, "klasser": set(), "n_kluster": 0})
        e["raknare"] += n
        e["kluster"][str(k["kluster_id"])] = n
        e["klasser"].add(k.get("klass"))
        e["n_kluster"] += 1
    return karta, unknown


def svg_text(lines, x, y, line_h=18):
    parts = [f'<g class="info" font-family="ui-monospace,Menlo,Consolas,monospace" '
             f'font-size="14" fill="#cfe3ff">']
    for i, ln in enumerate(lines):
        esc = ln.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(f'<text x="{x:.1f}" y="{y + i * line_h:.1f}">{esc}</text>')
    parts.append("</g>")
    return parts


def build_svg(graph, karta, unknown, population, klass,
              n_celler_totala, n_kluster_karta):
    cells = graph["cells"]
    grid = float(graph.get("grid", 32.0))

    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    zs = [c[2] for c in cells]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    minz, maxz = min(zs), max(zs)
    span_x = maxx - minx + grid
    span_y = maxy - miny + grid
    scale = (W - 2 * PAD) / span_x
    H = int(span_y * scale + 2 * PAD)
    cs = grid * scale

    def sx(x):
        return PAD + (x - minx) * scale

    def sy(y):
        return PAD + (maxy - y) * scale

    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
                 f'viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    parts.append(f'<rect width="{W}" height="{H}" fill="#07101b"/>')

    # Bas: alla celler svagt, fargade i hojdband.
    parts.append('<g class="cells">')
    for c in cells:
        parts.append(
            f'<rect x="{sx(c[0]) - cs / 2:.1f}" y="{sy(c[1]) - cs / 2:.1f}" '
            f'width="{cs:.1f}" height="{cs:.1f}" fill="{zcolor(c[2], minz, maxz)}" '
            f'opacity="{BASE_OPACITY}"/>')
    parts.append("</g>")

    # Heatmap: valda celler i intensitetsskala efter raknare.
    max_r = max((e["raknare"] for e in karta.values()), default=0)
    parts.append('<g class="heat">')
    for cid in sorted(karta):
        e = karta[cid]
        t = 1.0 if max_r == 0 else e["raknare"] / max_r
        c = cells[cid]
        title = (f"cell {cid} — {e['raknare']} misslyckade forsok, "
                 f"{e['n_kluster']} kluster")
        parts.append(
            f'<rect x="{sx(c[0]) - cs / 2:.1f}" y="{sy(c[1]) - cs / 2:.1f}" '
            f'width="{cs:.1f}" height="{cs:.1f}" fill="{cell_color(t)}" '
            f'opacity="{HEAT_OPACITY}"><title>{title}</title></rect>')
    parts.append("</g>")

    # Textruta (fast position, hoger upp).
    lines = [
        f"population: {population}",
        f"klass: {klass}",
        f"fargade celler: {len(karta)} av {n_celler_totala}",
        f"kluster pa kartan: {n_kluster_karta}",
        f"okand cell: {len(unknown)} kluster",
    ]
    parts.extend(svg_text(lines, W - PAD - 360, PAD + 14))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_summary(graph, karta, unknown, population, klass):
    def klass_for(e):
        ks = sorted(e["klasser"])
        return ks[0] if len(ks) == 1 else "blandad"

    celler = []
    for cid in sorted(karta):
        e = karta[cid]
        celler.append({
            "cell": str(cid),
            "klass": klass_for(e),
            "population": population,
            "raknare": e["raknare"],
            "kluster_id:n": e["kluster"],
        })

    return {
        "schema": SCHEMA,
        "kommando": KOMMANDO,
        "population": population,
        "klass": klass,
        "graf": graph.get("map", "unknown"),
        "n_celler_totala": len(graph["cells"]),
        "n_celler_fargade": len(karta),
        "n_kluster_karta": sum(e["n_kluster"] for e in karta.values()),
        "n_kluster_okand": len(unknown),
        "raknare_max": max((e["raknare"] for e in karta.values()), default=0),
        "celler": celler,
    }


def canonical_json(obj):
    return (json.dumps(obj, ensure_ascii=False,
                       separators=(",", ":"), sort_keys=True) + "\n").encode(
        "utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--obduktion", required=True)
    ap.add_argument("--graf", required=True)
    ap.add_argument("--population", required=True)
    ap.add_argument("--klass", required=True)
    ap.add_argument("--out-svg", required=True)
    ap.add_argument("--out-json", required=True)
    a = ap.parse_args(argv)

    if a.klass != "alla" and a.klass not in (
            "fall", "avsett_drop", "stall", "timeout", "fastnad"):
        die(f"okand klass '{a.klass}'")

    obd = load_json(a.obduktion)
    if obd.get("schema") != "verktygslada/obducera/2":
        die(f"obduktion: forvantad schema verktygslada/obducera/2, "
            f"fann {obd.get('schema')!r}")
    graph = load_json(a.graf)
    if graph.get("schema") != "qw-nav-graph/1":
        die(f"graf: forvantad schema qw-nav-graph/1, "
            f"fann {graph.get('schema')!r}")

    karta, unknown = select_clusters(obd, a.population, a.klass)
    n_cells = len(graph["cells"])
    for cid in karta:
        if not 0 <= cid < n_cells:
            die(f"cell {cid} finns inte i grafen ({n_cells} celler)")

    svg = build_svg(graph, karta, unknown, a.population, a.klass,
                    n_cells, sum(e["n_kluster"] for e in karta.values()))
    with open(a.out_svg, "w", encoding="utf-8") as f:
        f.write(svg)

    summary = build_summary(graph, karta, unknown, a.population, a.klass)
    data = canonical_json(summary)
    with open(a.out_json, "wb") as f:
        f.write(data)

    print(f"skrev {a.out_svg} ({n_cells} celler, {len(karta)} fargade) "
          f"och {a.out_json} ({len(unknown)} okanda kluster)")


if __name__ == "__main__":
    main()
