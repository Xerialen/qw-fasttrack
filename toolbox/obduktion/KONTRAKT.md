# KONTRAKT: `obducera` åtgärdslista (verktygslada/obducera/2)

Schema **v2** (I3-fix, 2026-08-15). Ersätter `verktygslada/obducera/1`.
Skrivet **före** v2-implementation och före determinismtest mot v2.
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
K-seriens teleportförsök har `regim=teleport` och faller bort ur
`handelser`/`kluster`/`atgarder` under default — men **kastas inte**:
de redovisas i `exkluderade_regimer` (se nedan).

## Klasser (fältet `klass`, exakt dessa strängar)

| klass         | källa (ordning) |
|---------------|-----------------|
| `fall`        | peak_drop_150 (Δz > 150 från löpande peak), **inte** UT-undantaget |
| `avsett_drop` | samma detektor på UT-ben med `undanta=true` (filnamn `ut_*` eller meta) |
| `stall`       | rad/event med `ev=bot_stall` eller stall_recorder-kuvert; `reason` bevaras |
| `timeout`     | försöks-meta/summary `utfall=timeout` |
| `fastnad`     | försöks-meta `utfall` ∈ {`fastnad`, `fall_plus_fastnad`} |

Ingen annan klass emitteras. Lyckade försök utan detektorträff ger
noll händelser. `ogiltig_tic` / `kasserad` exkluderas helt (varken täljare,
evidens eller `exkluderade_regimer` — de är ogiltig data, inte en regim).

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

## Klustring (v2-nyckel)

Officiell nyckel för precision/recall när cell är stämplad:
`(cell, lank, klass)`.

När `cell="unknown"` är nyckeln **`(arm, ben, cell, lank, klass)`**
där `arm` är sidan (A/B) och `ben` är rutten (`in_ring`, `ut_vast`, …).
Kluster får **aldrig** blanda A/B-sidor eller skilda rutter i unknown-läge.
Därefter rumslig split (greedy närmaste-centroid, radie **64.0** u) inuti
samma nyckel. Ordning: händelser sorterade `(forsok_id, t, klass, origin)`.

`spridning_u` = max avstånd från centroid (underlag för "falska hopslagningar").

Varje kluster bär `arm` och `ben`: det unika värdet om alla medlemmar
delar det, annars strängen `"mixed"` (kan bara uppstå på stämplade
kluster som inte splittas på sida/rutt).

## Åtgärdslistan

`atgarder` = kluster **ur den filtrerade (default kedjad) mängden** med
`klass` ∈ {`fall`, `fastnad`, `timeout`, `stall`} sorterade efter:

1. `n_forsok` fallande
2. `n_handelser` fallande
3. `kluster_id` stigande

`avsett_drop` finns i `handelser` och `kluster` men **inte** i `atgarder`
(`atgard_kandidat=false`).

`prio` är 1-baserat löpnummer i den sorterade åtgärdslistan (1 = högst).

## Exkluderade regimer (v2, Fables beslut på I3)

Kedjad-filtret förblir default. Försök som filtret tar bort (t.ex.
`teleport` / `teleport_efter_fel` under `--regim kedjad`) klassas och
klustras **identiskt** men landar i sektionen `exkluderade_regimer`,
aldrig i `handelser`/`kluster`/`atgarder`.

Sektionen har samma räknarstruktur som huvudutfallet:

```
n_forsok          int
n_handelser       int
n_kluster         int
bind_statistik    {stamplade, unknown}   # ticks i de bortfiltrerade försöken
per_regim         { <regim>: Raknare, ... }   # lexikografiska nycklar
handelser         [Handelse, ...]        # id-prefix X
kluster           [Kluster, ...]         # kluster_id-prefix XK
```

`Raknare`:

```
n_forsok, n_handelser, n_kluster,
n_fall, n_avsett_drop, n_stall, n_timeout, n_fastnad
```

Alla nio räknare är alltid närvarande (0 om tomt). Vid `--regim alla`
är sektionen närvarande men tom (alla noll, tomma arrayer, tom `per_regim`).

`atgarder` finns **inte** i sektionen — åtgärdslistan är evidensfiltrerad.

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
   `kluster_id`, `arm`, `ben`. Numeriska cell/länk-id skrivs utan decimal
   (`"48136"`).
5. Behållna händelser: `handelse_id` = `H` + 4-siffrig sekvens.
   Exkluderade: `X` + 4-siffrig (egen räkning, samma sortering).
   Behållna kluster: `K` + 4-siffrig. Exkluderade: `XK` + 4-siffrig.
6. Arrayer `forsok_id` och `handelse_id` inuti ett kluster: lexikografiskt unika.
7. Förbjudna fält i kanonisk utdata: `generated_at`, `host`, `path` (absolut),
   `request_id`, `duration_ms`. `serie` är katalogens **basnamn**, inte sökväg.

## Rotobjekt

```
schema               "verktygslada/obducera/2"
kommando             "obducera"
serie                basnamn
arm                  "A" | "B" | "AB"
regim                det filter som kördes
graph_contract       "qw-nav-graph/1" | "unknown"
navmesh_stamp        objekt | "unknown"
bind_statistik       {stamplade, unknown}   # ticks i BEHÅLLNA försök
filter               {regim, n_forsok_in, n_forsok_behallna, n_forsok_exkluderade}
handelser            [Handelse, ...]
kluster              [Kluster, ...]
atgarder             [Kluster & {prio: int}, ...]
exkluderade_regimer  objekt (se ovan)
```

`navmesh_stamp` är `"unknown"` om ingen rad (behållen eller exkluderad)
bar fältet; annars **ett** värde om alla stämplade rader är lika, annars
`{"status":"mixed"}`.

## Handelse

`id, forsok_id, arm, ben, cykel, klass, cell, lank, bind, t, origin,
regim, drop_u, stall_reason, meta_utfall`

- `cykel`: int eller `null`.
- `drop_u`: satts för `fall`/`avsett_drop`, annars `null`.
- `stall_reason`: satts för `stall`, annars `"unknown"` om klassen är stall
  utan reason, annars `null`.
- `t`: händelsetid (triggande tick). `fastnad`/`timeout` använder sista
  tickens `t`.

## Kluster / åtgärd

`kluster_id, cell, lank, klass, bind, arm, ben, locus, centroid, spridning_u,
n_handelser, n_forsok, forsok_id, handelse_id, atgard_kandidat`
plus `prio` på åtgärdsraden.

`locus` = centroid avrundad till 2 decimaler (samma tal som `centroid`).

## Determinismtest (får köras först efter detta kontrakt committats)

Samma `--serie` + flaggor två gånger ⇒ identiska bytes (inkl. avslutande LF).
Fixtur: syntetisk miniserie under `toolbox/obduktion/tests/fixtures/`,
**inte** T1h-rådata (T1h är utvecklingskörning, inte orakel).
