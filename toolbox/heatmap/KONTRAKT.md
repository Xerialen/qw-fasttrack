# KONTRAKT: `heatmap` utdata (verktygslada/heatmap/1)

Schema **v1**. Ägare: spår D (qwen). Bindande för kommandot
`toolbox/heatmap/heatmap.py`. GPU-fri, ren filtransformation:
(obducera-v2-utdata, graf-JSON) → (SVG, kanonisk JSON-sammanfattning).

Inga servrar, ingen riggkontakt. Indatafilerna är de enda källorna;
inget hämtas, inget tidsstämplas.

## Kommando

```
python3 heatmap.py --obduktion <fil.json> --graf <graf.json>
                   --population <etikett> --klass <klass|alla>
                   --out-svg <fil.svg> --out-json <fil.json>
```

- `--population`: exakt en populationsetikett ur obducera-v2-filens
  `populationer` (t.ex. `kedjad_N75`). Saknas etiketten: fel, exit 2.
- `--klass`: en av obducera-v2:s fem klasser (`fall`, `avsett_drop`,
  `stall`, `timeout`, `fastnad`) eller `alla`.
- `--graf`: graf-JSON med schema `qw-nav-graph/1` (`cells`, `grid`,
  `cell_ids`). `cell_ids` är en 1:1-lista mot `cells`: `cell_ids[i]`
  är det numeriska id:t för `cells[i]`.

## Selektion

Kluster beaktas ur `populationer[<population>].kluster` där
`klass` matchar (`alla` → alla klasser). Kluster med
`cell == "unknown"` **ritas inte** på kartan; de samlas i en
textruta i SVG:n (`okänd cell: N kluster`). Alla övriga kluster
måste ha ett cell-id som finns i grafens `cell_ids`; okänt
cell-id är ett fel (exit 2) — heatmap gissar aldrig cell.

Per cell sammanförs alla valda kluster:
`räknare = summa kluster.n_forsok`,
`kluster_id:n = {kluster_id: n_forsok, ...}`.

## SVG-utdata

- Alla grafens celler ritas svagt (bas, opacitet 0.25, färg efter
  höjdband som i referensverktyget — mörkblå lågt, ljus cyan högt).
- Celler med minst ett valt kluster färgas **över** basen i
  intensitetsskala efter `räknare` (misslyckade försök):
  linjär interpolation `t = räknare / max_räknare` över valda
  celler (1 → 1.0), färgväg `#10314f` (t=0) → `#ffe22e` (t=1),
  RGB-komponenter avrundade till heltal. Opacitet 0.9.
- Varje färgad cell bär ett `<title>` med `cell <id> — <räknare>
  misslyckade försök, <n_kluster> kluster`.
- Textblock höger upp (fast position): population, klass, antal
  färgade celler, antal kluster på kartan, och textrutan
  `okänd cell: N kluster` (N = antal uteslutna unknown-kluster).
- Koordinater: samma teknikkonvention som referensen — Quake +x höger,
  +y "uppåt" i planet; SVG-y speglad. Cellen ritas som rect kring
  sitt medelpunkt (x,y) med bredden `grid * scale`.
- SVG:ingen tidsstämpel, ingen absolut sökväg, inget som ändrar
  mellan körningar på samma indata.

## JSON-sammanfattning (kanonisk)

Rotobjekt:

```
schema               "verktygslada/heatmap/1"
kommando             "heatmap"
population           <etikett>
klass                <klass | "alla">
graf                 graf-JSON:s fält "map" (basnamn, ej sökväg)
n_celler_totala      int   # grafens celler
n_celler_fargade     int
n_kluster_karta      int   # kluster med känd cell
n_kluster_okand      int   # kluster med cell == "unknown"
raknare_max          int   # högsta per-cell-räknare (0 om inga)
celler               [ Cell, ... ]   # ordning: cell-id stigande
```

`Cell`:

```
cell       sträng (grafens id, numeriska id utan decimal)
klass      sträng (klustrets klass; "blandad" om cellens kluster
           har skilda klasser — kan bara uppstå med --klass alla)
population sträng (samma som roten)
raknare    int
kluster_id:n   objekt {kluster_id: n_forsok, ...}  # nycklar lexikografiska
```

Fältet `kluster_id:n` skrivs med nyckeln `kluster_id:n` (kolon i
nyckeln, enligt order).

### Decimal- och serialiseringsregler

1. UTF-8, en avslutande LF, inga BOM.
2. `json.dumps(..., ensure_ascii=False, separators=(",", ":"),
   sort_keys=True)` — objektnycklar lexikografiska. Enda arrayen
   (`celler`) har **semantikordning: cell-id stigande** (heltalsordning
   när id:t är numeriskt).
3. **Inga flyttal i utdata.** Alla värden är int eller sträng.
   (Intensitetsberäkningen sker internt och påverkar bara SVG-fält
   med fast format; JSON-sammanfattningen bär ingen koordinat- eller
   färgdata.)
4. Id är strängar, numeriska cell- och kluster-id utan decimal.
5. Förbjudna fält: `generated_at`, `host`, `path` (absolut),
   `request_id`, `duration_ms`, tidsstämplar av alla slag.
6. Paritet: två körningar på samma indata ⇒ **byte-identiska**
   filer (SVG och JSON).
