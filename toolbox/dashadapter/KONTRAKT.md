# KONTRAKT: obducera → stallkartan (verktygslada/dashadapter/1)

Skrivet **före** implementation. Ägare: spår I (presentationsled).
Adaptern är ingen ny renderare — den fyller
`testsuite/dashboard/map-template.html` via `parent.PROPOSAL_DATA`.

## Kommando

```
python3 -m toolbox.dashadapter --obducera FILE.json --out-snapshots FILE.json
                                 [--out-html FILE.html]
                                 [--map-dir DIR] [--map-template FILE]
```

`--obducera` är kanonisk JSON från `obducera` v2/v3 (`sort_keys`, LF).

## Templatens datainterface (kartlagt, inte påhittat)

`map-template.html` läser **enbart** `parent.PROPOSAL_DATA`:

| nyckel | roll |
|---|---|
| `graph` | `{grid, cells[float×3 packed], cell_ids, links, linkKinds}` |
| `entities` | `{map, entities:[{kind,x,y,z,...}]}` |
| `snapshots` | lista snapshot-objekt |
| `linkgeo` | `{<link_id>: geometri}` (valfritt, `{}` ok) |

Inbäddning: JSON-literal i script (samma `json.dumps(sort_keys=True,
separators=(",", ":"), ensure_ascii=False)` + `<` → `\u003c` som
`build_dashboard.json_literal`). Ingen sidofil i runtime.

### Snapshot (fält templaten faktiskt läser)

```
id, run, time, date, label, branch, build, regime,
stats.{…, stall_firings?},
cells: [{ cell, pos[x,y,z]|null, n, reasons{str:number},
          links{str:number}, reason, samples[] }]
```

- **Höjd** på stapeln = `visCount` = summan av `reasons[k]` för k i
  templatenens `REASONS` (displacement, prestrafe_deficit,
  air_commit_off, air_commit_timeout, speedjump_stall). Nycklar utanför
  den listan **syns inte**.
- **Färg** = `REASON_VAR[dominantOn(reasons)]`.
- **Lista/sortering** använder `n` och `reason`.
- **Position** = `cell.pos` annars `ID2POS.get(cell)` ur grafen.
- **Flera snapshots** = klickbar lista; `regime` visas och
  varnar vid REF-jämförelse över olika regime. **Ingen annan
  populationsfilter-UI** — därför **en snapshot per population**.

## Mappning obducera → snapshot

En snapshot per nyckel i `populationer` (saknas den: en snapshot av
rotens `kluster`, regime=`regim`).

| obducera | dashboard |
|---|---|
| `population` / etikett | `snapshot.regime`, `id`, `label` |
| `kluster.n_forsok` | `cell.n` och `reasons[<mappad>]` |
| `kluster.klass` | mappas till REASONS-nyckel (nedan); originalet i `samples[].klass` |
| `kluster.cell` numerisk | `cell` som int (så `ID2POS` träffar) |
| `kluster.cell==unknown` | syntetiskt id `kluster_id`; `pos=centroid` |
| `kluster.centroid` | `pos` (alltid satt, 2 dec) |
| `kluster.lank` + n | `links` om lank ≠ unknown |
| `kluster.forsok_id` | `samples[].forsok_id` (lex, max 8) |

Samma `(cell, klass)` inom en population slås ihop (summa `n_forsok`);
unknown-celler slås **inte** ihop över `kluster_id` (rumslig split
behålls).

### Klass → REASONS (färg/höjd)

Templaten kan inte färga på I-klassnamn. Adaptern mappar:

| I-klass | REASONS-nyckel |
|---|---|
| `fall` | `air_commit_timeout` |
| `fastnad` | `displacement` |
| `timeout` | `air_commit_timeout` |
| `avsett_drop` | `prestrafe_deficit` |
| `stall` | `stall_reason` om den är en REASONS-nyckel, annars `speedjump_stall` |

`reason` på cellen = den mappade nyckeln (så pricken färgas).

## Serialisering

`out-snapshots` är **bara** `{graph, entities, snapshots, linkgeo}`
kanonikaliserat:

- UTF-8 + avslutande LF
- `json.dumps(ensure_ascii=False, separators=(",", ":"), sort_keys=True)`
- origin/pos 2 dec redan i obducera-centroid
- inga `generated_at` / absoluta sökvägar / request-id
- `graph`/`entities`/`linkgeo` kopieras med `sort_keys` (innehåll från
  kartkatalogen; samma katalog ⇒ samma bytes)

HTML är klient av samma objekt (ej paritetspart). Determinismtestet
jämför `out-snapshots`, inte HTML-bytes (kartkatalogens graf kan
skilja mellan maskiner).

## Determinismtest

Samma `--obducera` + samma `--map-dir` två gånger ⇒ identiska
snapshots-bytes. Fixtur: mini_serie-obducera, inte T1h.
