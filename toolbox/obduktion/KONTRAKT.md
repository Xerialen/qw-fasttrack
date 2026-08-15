# KONTRAKT: `obducera` åtgärdslista (verktygslada/obducera/1)

Skrivet **före** determinismtest och före produktionskod mot T1h.
Ägare: spår I (grok). Bindande för CLI, MCP och framtida webbklient.

Paritet (REVISION 1): samma anrop ger **byte-identisk kanonikaliserad JSON**.
Webben är klient av denna yta, inte paritetspart. Tid, absoluta sökvägar,
hostname och request-id får **inte** ingå i resultatet.

## Kommando

```
obducera --serie <dir> [--arm A|B] [--regim kedjad|alla|teleport]
         [--stamplar <dir>] [--ent 1] [--out -]
```

Default `--regim kedjad` (E-punkten: kedjad är evidensfiltret).
K-seriens teleportförsök har `regim=teleport` och faller bort under default.

## Klasser (fältet `klass`, exakt dessa strängar)

| klass         | källa (ordning) |
|---------------|-----------------|
| `fall`        | peak_drop_150 (Δz > 150 från löpande peak), **inte** UT-undantaget |
| `avsett_drop` | samma detektor på UT-ben med `undanta=true` (filnamn `ut_*` eller meta) |
| `stall`       | rad/event med `ev=bot_stall` eller stall_recorder-kuvert; `reason` bevaras |
| `timeout`     | försöks-meta/summary `utfall=timeout` |
| `fastnad`     | försöks-meta `utfall` ∈ {`fastnad`, `fall_plus_fastnad`} |

Ingen annan klass emitteras i v1. Lyckade försök utan detektorträff ger
noll händelser. `ogiltig_tic` / `kasserad` exkluderas helt (varken täljare
eller evidens).

## Bindning (cell / länk) — gissa aldrig

Stämpelfält läses om de **finns på den triggande raden** (eller dess
sidovagn `*.stamp.jsonl` / `--stamplar`, samma radindex eller `t` avrundat
till 3 decimaler):

- cell: `cell_id` \| `cell`
- länk: `link_id` \| `link` \| `lank` \| `aktiv_lank` \| `chosen_link`
- `navmesh_stamp`, `graph_contract`

Saknas fältet, eller länk = `4294967295` (NOLINK): värdet är strängen
`"unknown"`. `bind` är `"stamped"` endast när `cell != "unknown"`.
**xyz → cell-id är förbjudet i spår I.** GraphMatcher är spår A.

## Klustring

Officiell nyckel för precision/recall: `(cell, lank, klass)`.

När `cell="unknown"` splittas kluster dessutom rumsligt så att skilda
fallhärdar inte hopslås: greedy närmaste-centroid, radie **64.0** u,
samma (`klass`, `lank`). Ordning: händelser sorterade
`(forsok_id, t, klass, origin)` — deterministiskt.

`spridning_u` = max avstånd från centroid (underlag för "falska hopslagningar").

## Åtgärdslistan

`atgarder` = kluster med `klass` ∈ {`fall`, `fastnad`, `timeout`, `stall`}
sorterade efter:

1. `n_forsok` fallande
2. `n_handelser` fallande
3. `kluster_id` stigande

`avsett_drop` finns i `handelser` och `kluster` men **inte** i `atgarder`
(`atgard_kandidat=false`).

`prio` är 1-baserat löpnummer i den sorterade åtgärdslistan (1 = högst).

## Serialisering (byte-identitet)

1. UTF-8, en avslutande LF, inga BOM.
2. `json.dumps(..., ensure_ascii=False, separators=(",", ":"), sort_keys=True)`.
   Objektnycklar är alltså **lexikografiska**. Arrayer har semantikordning
   enligt detta kontrakt, inte nyckelsortering.
3. Decimaler **före** dump (inga råa binär-floatar i utdata):

   | fält | precision |
   |------|-----------|
   | `origin`, `centroid`, `locus` (xyz) | 2 decimaler |
   | `t` | 3 decimaler |
   | `drop_u`, `spridning_u` | 1 decimal |
   | andelar (`andel`) | 4 decimaler |

   Avrundning: vanliga runda-halv-jämn (`round` i IEEE, Python 3).
   Heltal förblir heltal. `null` tillåts bara där schemat säger Optional.

4. Identiteter är strängar: `cell`, `lank`, `forsok_id`, `handelse_id`,
   `kluster_id`. Numeriska cell/länk-id skrivs utan decimal (`"48136"`).
5. `handelse_id` = `H` + 4-siffrig nolla-utfylld sekvens i händelsesortering.
   `kluster_id` = `K` + 4-siffrig i klustersortering (samma nyckel som atgarder,
   därefter `avsett_drop`-kluster).
6. Arrayer `forsok_id` och `handelse_id` inuti ett kluster: lexikografiskt unika.
7. Förbjudna fält i kanonisk utdata: `generated_at`, `host`, `path` (absolut),
   `request_id`, `duration_ms`. `serie` är katalogens **basnamn**, inte sökväg.

## Rotobjekt

```
schema            "verktygslada/obducera/1"
kommando          "obducera"
serie             basnamn
arm               "A" | "B" | "AB"
regim             det filter som kördes
graph_contract    "qw-nav-graph/1" | "unknown"
navmesh_stamp     objekt | "unknown"
bind_statistik    {stamplade, unknown}
filter            {regim, n_forsok_in, n_forsok_behallna, n_forsok_exkluderade}
handelser         [Handelse, ...]
kluster           [Kluster, ...]
atgarder          [Kluster & {prio: int}, ...]
```

`navmesh_stamp` är `"unknown"` om ingen rad bar fältet; annars **ett** värde
om alla stämplade rader är lika, annars objektet
`{"status":"mixed"}` (aldrig gissad sammanslagning av olika stamp).

## Handelse

`id, forsok_id, arm, ben, cykel, klass, cell, lank, bind, t, origin,
regim, drop_u, stall_reason, meta_utfall`

- `cykel`: int eller `null` (K-serien har attempt-nr i `forsok_id`, cykel=null
  om inte `cykel` finns i meta).
- `drop_u`: satts för `fall`/`avsett_drop`, annars `null`.
- `stall_reason`: satts för `stall`, annars `"unknown"` om klassen är stall
  utan reason, annars `null`.
- `t`: händelsetid (triggande tick). `fastnad`/`timeout` använder sista
  tickens `t`.

## Kluster / åtgärd

`kluster_id, cell, lank, klass, bind, locus, centroid, spridning_u,
n_handelser, n_forsok, forsok_id, handelse_id, atgard_kandidat`
plus `prio` på åtgärdsraden.

`locus` = centroid avrundad till 2 decimaler (samma tal som `centroid` i v1).

## Determinismtest (får köras först efter detta kontrakt committats)

Samma `--serie` + flaggor två gånger ⇒ identiska bytes (inkl. avslutande LF).
Fixtur: syntetisk miniserie under `toolbox/obduktion/tests/fixtures/`,
**inte** T1h-rådata (T1h är utvecklingskörning, inte orakel).
