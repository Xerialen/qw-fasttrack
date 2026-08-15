# KONTRAKT: obducera → stallkartan (verktygslada/dashadapter/2)

Schema **v2** (efter grok2 JUSTERAS). Ersätter v1:s I-klass→BotStall-mappning.
Skrivet **före** v2-koden. Ägare: spår I.

Adaptern är ingen ny renderare — den fyller `map-template.html` via
`parent.PROPOSAL_DATA`. Templaten utökas **additivt** på branchen
`toolbox/dashboard-i-classes` (`~/rtx-toolbox-dash`). `~/rtx-cost-exp`
rörs inte.

## Kommando

```
python3 -m toolbox.dashadapter --obducera FILE.json --out-snapshots FILE.json
                                 --map-template FILE.html
                                 [--out-html FILE.html] [--map-dir DIR]
```

`--map-template` är **obligatorisk**. Adaptern läser REASONS-nycklarna
ur filen. Saknas någon I-klass (`fall`, `fastnad`, `timeout`,
`avsett_drop`, `stall`) ⇒ **avbrott**, ingen tyst mappning till
BotStall-nycklar.

`--obducera` är kanonisk JSON från `obducera` v2/v3.

## Templatens datainterface

`map-template.html` läser **enbart** `parent.PROPOSAL_DATA`:

| nyckel | roll |
|---|---|
| `graph` | `{grid, cells[float×3 packed], cell_ids, links, linkKinds}` |
| `entities` | `{map, entities:[{kind,x,y,z,...}]}` |
| `snapshots` | lista snapshot-objekt |
| `linkgeo` | `{<link_id>: geometri}` (valfritt, `{}` ok) |

Inbäddning: `json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` + `<` → `\u003c`. Ingen sidofil.

### Snapshot.cells[]

```
cell, pos[x,y,z]|null, n, reasons{str:number}, links{str:number},
reason, samples[]
```

- **Höjd** = `visCount` = Σ `reasons[k]` för k ∈ templatens `REASONS`.
- **Färg** = `REASON_VAR[reason]`.
- **Position** = `cell.pos` (sätts alltid till centroid, 2 dec) — även
  när `cell` är ett mesh-id. Stapeln sitter vid händelsens locus, inte
  nödvändigtvis cellorigin på meshen.
- **Flera snapshots** = en per `populationer`-nyckel; `regime=id=label`.

### REASONS (additivt)

De fem BotStall-nycklarna är **orörda** (samma key/cssvar/label/tip).
Tillagda I-klasser med egna färger:

| key | default på? |
|---|---|
| `displacement` … `speedjump_stall` | ja (oförändrat) |
| `fall` | ja |
| `fastnad` | ja |
| `timeout` | ja |
| `stall` | ja |
| `avsett_drop` | **nej** (`off: true`) — inte åtgärdsklass; valbar i rälsen |

BotStall-snapshots som bara bär de fem gamla nycklarna ritar som förr.

## Mappning obducera → snapshot

**Ingen klassmappning.** `kluster.klass` skrivs rakt som `reason` och
som nyckel i `reasons`. Okänd klass ⇒ avbrott (inte fallback till
displacement).

| obducera | dashboard |
|---|---|
| `population` | `snapshot.regime`, `id`, `label` |
| `kluster.n_forsok` | `cell.n` och `reasons[klass]` |
| `kluster.klass` | `reason` = klass (nativ) |
| `kluster.cell` numerisk | `cell` som int |
| `kluster.cell==unknown` | `kluster_id`; `pos=centroid` |
| `kluster.centroid` | `pos` (alltid, 2 dec) |
| `kluster.lank` | `links` om ≠ unknown |
| `kluster.forsok_id` | `samples[].forsok_id` (max 8) |

Samma `(cell, klass)` inom en population slås ihop; unknown slås inte
ihop över `kluster_id`.

`.attr.json` / `stall_reason` används **inte**.

## Serialisering

`out-snapshots` = `{entities, graph, linkgeo, snapshots}`:

- UTF-8 + avslutande LF
- `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`
- inga `generated_at` / absoluta sökvägar / request-id

HTML är klient, inte paritetspart. Determinism = snapshots-bytes.

## Determinismtest

Samma `--obducera` + samma `--map-dir` + samma `--map-template`
två gånger ⇒ identiska snapshots-bytes. Fixtur: mini_serie.
