# KONTRAKT: `obducera` åtgärdslista (verktygslada/obducera/3)

Schema **v3** (I-justering efter deepseek-korsreview). Ersätter v2.
Skrivet **före** v3-koden. Semantikändringar: fall binds till landning,
UT-peak återställs aldrig, stall utan origin emitteras inte.

Policy (Fable, efter slice-dom): `_last_known_before`-fallback gäller
både aldrig-landande fall och airborne-fastnad/timeout; `bind=fallback`.
Västväggs-missing förblir unknown. Attr binds inte.

Schema **v2** (bevarad): populationsmodellen — tre explicita
populationer, aldrig filtrerade räknare utan etikett. Kapning A76–79
är nämnaren N=75, inte händelseförlust.
Ägare: spår I (grok). Bindande för CLI, MCP och framtida webbklient.

Paritet (REVISION 1): samma anrop ger **byte-identisk kanonikaliserad JSON**.
Webben är klient av denna yta, inte paritetspart. Tid, absoluta sökvägar,
hostname och request-id får **inte** ingå i resultatet.

## Kommando

```
obducera --serie <dir> [--arm A|B] [--regim kedjad|alla|teleport]
         [--stamplar <dir>] [--ent 1] [--out -]
```

Default `--regim kedjad` (E-punkten: kedjad är evidensfiltret för
toppnivåns `handelser`/`kluster`/`atgarder`). Information kastas inte:
alla tre populationer redovisas alltid under `populationer`.

## Klasser (fältet `klass`, exakt dessa strängar)

| klass         | källa (ordning) |
|---------------|-----------------|
| `fall`        | peak_drop_150 på IN (Δz > 150 från löpande peak; peak återställs) |
| `avsett_drop` | UT-ben (`undanta=true`): högst en emission per försök vid första korsning; peak återställs **aldrig** (paritet `timtest_ben.py:98–107`) |
| `stall`       | `ev=bot_stall` / stall_recorder **med origin**; utan origin emitteras ingen händelse |
| `timeout`     | försöks-meta/summary `utfall=timeout` |
| `fastnad`     | försöks-meta `utfall` ∈ {`fastnad`, `fall_plus_fastnad`} |

Ingen annan klass emitteras. Lyckade försök utan detektorträff ger
noll händelser. `ogiltig_tic` / `kasserad` exkluderas helt (inte en
population — ogiltig data).

## Bindning (cell / länk) — gissa aldrig

**Primär input** är mät-JSONL (`t` + `players[].origin` / `on_ground`,
eller stall-kuvert). Spår A:s stämplade rader
(`{t, bot, cell, verdict, schema, graph_stamp}` — ingen `origin`/`players`)
är **sidovagn**, aldrig primär input. De läses via `--stamplar` eller
`*.stamp.jsonl` (radindex eller `t` avrundat till 3 decimaler) och
fogas på mät-tickar.

**Fall och avsett_drop binds per HÄNDELSE till LANDNINGEN**, inte
luft-triggerticken: första tick med `on_ground=true` efter Δz-slaget.
xyz → cell-id gissas aldrig.

**`_last_known_before`-fallback** gäller **två** klasser, samma funktion
(`_last_known_before` — sista grounded tick med cell ≠ unknown, inte
`.attr.json`):

1. **Aldrig-landande fall / avsett_drop** (spåret slutar airborne; ingen
   landningstick). Cell från sista grounded tick före Δz-slaget.
   `origin`/`t` från den ticken (ingen landningsplats finns).
2. **Airborne-fastnad / timeout** (sista origin-tick har
   `on_ground is not True`). Cell/länk från sista grounded tick före
   slutet. `origin`/`t` stannar på sista ticken (där kroppen fastnade).

I båda fallen är `bind` **`"fallback"`** — inte `"stamped"`. Det är
inte en landningscell. Attr är inte bindkälla.

**Västväggs-`missing` förblir unknown.** Sista tick `on_ground=true`
men GraphMatcher `missing` (cell `"unknown"`, typ z=128-väggen) är
en landning utan cell. Fallbacken appliceras **inte**. Att binda till
`prev_stamped` / `drop_from_cell` vore att gissa landningscell —
förbjudet. A:s `attr.cell_id` är unknown här; det får inte fyllas i.

**`.attr.json` är inte per-händelse.** Spår A:s `attribution.cell_id` /
`drop_landing_cell` är **en sammanfattning per FÖRSÖK**. Obducera
binder **per händelse**. Olika landningar i samma försök kan därför få
olika celler; det är inte en konflikt mot försökssammanfattningen, och
`.attr.json` får inte skriva över enskilda händelsers landningscell.
Klassningen läser **aldrig** `forsok["attr"]`.

Stämpelfält läses om de **finns på landningsticken** (eller sidovagn):

- cell: `cell_id` \| `cell`
- länk: `link_id` \| `link` \| `lank` \| `aktiv_lank` \| `chosen_link`
- `navmesh_stamp`, `graph_contract`

Saknas fältet, eller länk = `4294967295` (NOLINK): värdet är strängen
`"unknown"`. `bind` är en av:

| `bind` | När |
|---|---|
| `stamped` | `cell != "unknown"` och källan är landningstick, grounded endpoint eller stall-tick |
| `fallback` | `cell != "unknown"` men källan är `_last_known_before` (aldrig-landande fall **eller** airborne-fastnad/timeout) |
| `unknown` | `cell == "unknown"` (saknad stamp, airborne utan känd grounded, västväggs-missing) |

`"stamped"` betyder inte «fallback med cell». `"fallback"` betyder inte
landning. **xyz → cell-id är förbjudet i spår I.** GraphMatcher är spår A.

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

Varje kluster och varje åtgärdsrad bär **`population`** (etiketten
nedan). Räknare utan populationsetikett är kontraktsbrott.

## Kapning (T1h-nämnare)

När serien är T1h-layout (cykelkataloger med de sex benen
`ut_ring, in_ring, ut_tunnel, in_tunnel, ut_vast, in_vast`) är
`N = min(n_hela_A, n_hela_B)` över armar som har minst en hel cykel
(samma regel som `timtest_rapport.py`: första N hela cykler).
Försök med `cykel > N` tillhör **ingen** population — de är kapning
(A76–79 när B stannar på 75), inte en regim.

`kap`:

```
n                 int | null     # N, eller null om ingen cykelkapning
per_arm           {A?: int, B?: int}   # n_hela per arm
kastade_cykler    {A?: [int, ...], B?: [int, ...]}
```

K-layout / ofullständig fixtur utan hela cykler: `n = null`, ingen
cykel kastas.

## Populationer (terra: alltid tre, samma räknarstruktur)

`populationer` har **exakt tre** nycklar, alltid närvarande (tom
population har nollor + tomma arrayer):

| nyckel | medlemmar efter kap |
|---|---|
| `alla_giltiga_N{N}` | alla giltiga försök i kapad mängd |
| `kedjad_N{N}` | `start`/`regim` = kedjad |
| `teleport_efter_fel_N{N}` | `start` = teleport_efter_fel (intern regim `teleport`) |

När `kap.n` är null skrivs `Nall` i stället för talet (`alla_giltiga_Nall`,
…). T1h med N=75 ger exakt etiketterna `alla_giltiga_N75`, `kedjad_N75`,
`teleport_efter_fel_N75`.

Varje population:

```
population        etiketten (samma som nyckeln)
n_kap             int | null
n_forsok, n_handelser, n_kluster
n_fall, n_avsett_drop, n_stall, n_timeout, n_fastnad
bind_statistik    {stamplade, unknown}
handelser         [Handelse, ...]
kluster           [Kluster & {population}, ...]
```

Alla **åtta** räknare är alltid närvarande (`n_forsok`, `n_handelser`,
`n_kluster`, `n_fall`, `n_avsett_drop`, `n_stall`, `n_timeout`,
`n_fastnad`). `atgarder` ligger **inte** i
populationen — åtgärdslistan är evidensfiltrerad (default kedjad) på
rotnivå, och varje rad bär samma `population`-etikett.

`--regim kedjad` (default): rotens `handelser`/`kluster`/`atgarder` är
identiska med `populationer.kedjad_N{N}` (samma id). `--regim alla`
pekar roten på `alla_giltiga_*`. `--regim teleport` pekar roten på
`teleport_efter_fel_*`.

Jämför aldrig `kedjad_*`-räknare med paketets/facits alla-giltiga
huvudtal — de är olika populationer och bär olika etiketter.

## Åtgärdslistan

`atgarder` = kluster ur **evidenspopulationen** (default `kedjad_N{N}`)
med `klass` ∈ {`fall`, `fastnad`, `timeout`, `stall`} sorterade efter:

1. `n_forsok` fallande
2. `n_handelser` fallande
3. `kluster_id` stigande

`avsett_drop` finns i `handelser` och `kluster` men **inte** i `atgarder`
(`atgard_kandidat=false`). `prio` är 1-baserat (1 = högst).

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

   Avrundning: vanliga runda-halv-jämn (`round` i IEEE, Python 3).
   Heltal förblir heltal. `null` tillåts bara där schemat säger Optional.

4. Identiteter är strängar: `cell`, `lank`, `forsok_id`, `handelse_id`,
   `kluster_id`, `arm`, `ben`, `population`. Numeriska cell/länk-id
   skrivs utan decimal (`"48136"`).
5. Id-prefix per population: `alla_giltiga` → `G`/`GK`; `kedjad` →
   `H`/`K`; `teleport_efter_fel` → `X`/`XK`. Rotens listor återanvänder
   evidenspopulationens id (ingen andra numrering).
6. Arrayer `forsok_id` och `handelse_id` inuti ett kluster: lexikografiskt unika.
7. Förbjudna fält i kanonisk utdata: `generated_at`, `host`, `path` (absolut),
   `request_id`, `duration_ms`. `serie` är katalogens **basnamn**, inte sökväg.
8. `populationer`-objektets nycklar är de tre etiketterna, lexikografiskt
   via `sort_keys` (`alla_giltiga_*`, `kedjad_*`, `teleport_efter_fel_*`).

## Rotobjekt

```
schema               "verktygslada/obducera/3"
kommando             "obducera"
serie                basnamn
arm                  "A" | "B" | "AB"
regim                det filter som styr rotens listor
graph_contract       "qw-nav-graph/1" | "unknown"
navmesh_stamp        objekt | "unknown"
bind_statistik       {stamplade, unknown}   # ticks i evidenspopulationen
kap                  se ovan
filter               {regim, n_forsok_in, n_forsok_behallna,
                      n_forsok_exkluderade, n_forsok_fore_kap}
handelser            [Handelse, ...]          # evidenspopulationen
kluster              [Kluster & {population}]
atgarder             [Kluster & {prio, population}]
populationer         { etikett: Population, ... }   # alltid tre
```

`n_forsok_in` = giltiga efter kap (alla_giltiga). `n_forsok_behallna` =
evidenspopulationen. `n_forsok_exkluderade` = giltiga efter kap som
inte är evidens (teleport under kedjad-default). `n_forsok_fore_kap` =
giltiga före cykelkapning.

`navmesh_stamp` är `"unknown"` om ingen rad i någon population bar
fältet; annars **ett** värde om alla stämplade rader är lika, annars
`{"status":"mixed"}`.

## Handelse

`id, forsok_id, arm, ben, cykel, klass, cell, lank, bind, t, origin,
regim, drop_u, stall_reason, meta_utfall`

- `cykel`: int eller `null`.
- `drop_u`: satts för `fall`/`avsett_drop`, annars `null`.
- `stall_reason`: satts för `stall`, annars `"unknown"` om klassen är stall
  utan reason, annars `null`.
- `t`: händelsetid (triggande tick). `fastnad`/`timeout` använder sista
  origin-tickens `t` även vid `bind=fallback` (cellen är äldre, platsen
  är slutet).
- `bind`: `stamped` \| `fallback` \| `unknown` (se §Bindning).

## Kluster / åtgärd

`kluster_id, cell, lank, klass, bind, arm, ben, population, locus,
centroid, spridning_u, n_handelser, n_forsok, forsok_id, handelse_id,
atgard_kandidat` plus `prio` på åtgärdsraden.

`locus` = centroid avrundad till 2 decimaler (samma tal som `centroid`).

## Determinismtest (får köras först efter detta kontrakt committats)

Samma `--serie` + flaggor två gånger ⇒ identiska bytes (inkl. avslutande LF).
Fixtur: syntetisk miniserie under `toolbox/obduktion/tests/fixtures/`,
**inte** T1h-rådata (T1h är utvecklingskörning, inte orakel).

## REVISION 2.1 (slice-integration, opus5; RÄTTAD av Fable vid integrationsmergen) — ADDITIV

RÄTTELSE (Fable, merge 94ff576): schemasträngen är `verktygslada/obducera/3` —
groks klusternyckeländring (population/sida/rutt vid unknown) ÄNDRADE betydelse
och bumpades korrekt före mergen; qwens heatmap accepterar [/2, /3] sedan
da501f4. Opus-textens `/2`-antagande gällde slice-branchens äldre bas och
utgår. Den additiva REGELN nedan gäller oförändrad framåt.

**Additiv regel (samma princip som B:s `p_*`-familj):** en konsument som möter
ett okänt rotfält ska **ignorera det**, aldrig fela. Nya fält får tillkomma utan
bump; ett fält som *ändrar betydelse* kräver bump.

### Nya rotfält

```
graph_stamp     sträng   # nivå 1, decimalsträng, eller "unknown" (armar skiljer sig)
stamp_kontroll  objekt   # {kalla, referens, per_arm, ok, avvikande, ostamplade, ovaliderad}
```

`stamp_kontroll.kalla` är `manifest` | `rader` | `konflikt` | `ingen`.
`stamp_kontroll.per_arm` är `{arm: {referens, ok, avvikande, ostamplade, ovaliderad}}`.

### Grafvalidering per rad (bindande, PER ARM)

Serien har **två referensgrafer** — en per arm (A och B bär olika stamp efter
per-arm-omstämplingen). Varje försök valideras mot **sin arms** referens:

1. `manifest.json` i `--stamplar` (eller i serien) — A:s `per_arm`-deklaration
   (`per_arm.A.graph_stamp`, `per_arm.B.graph_stamp`). Äldre manifest med en
   enda top-level `graph_stamp` gäller som wildcard för båda armarna.
2. Annars radernas `graph_stamp` **per arm**, men bara om armens rader är eniga.
3. **Intra-arm-konflikt** (två olika stamp inom samma arm) ⇒ den armen har
   ingen referens (`per_arm[arm].referens = "unknown"`). Två armar med olika
   stamp är **inte** en konflikt — det är designen.

Varje tick valideras mot **sin arms** referens. En rad som bär en **annan** graf
än sin arm får `cell` och `lank` nollställda till `"unknown"` och räknas som
`avvikande`. **Intra-arm-konflikt är FAIL-CLOSED**: den armens celler nollställs
till `"unknown"` (ingen av de blandade stampen betros) och räknas som
`ovaliderad` — inte `ok`, inte `avvikande`. Bindningen återskapas aldrig: ett
cell-id är bara ett namn på en cell *inom en graf*.

`ok` = validerad mot armens referens och matchade. `avvikande` = validerad och
avvek. `ovaliderad` = rad bar en stamp men armen saknade referens
(intra-arm-konflikt). `ostamplade` = rad utan `graph_stamp` (inte en avvikelse).
De fyra räknarna hålls isär just därför.

### A:s stämpelformat

Adaptern läser A:s radformat `{t, bot, cell, verdict, schema, graph_stamp}`:

- `schema` läses som `graph_contract` (efter det äldre namnet).
- `graph_stamp` normaliseras till decimalsträng (u64 > 2^53).
- `cell = 4294967295` är A:s sentinel för **luftburen** tick och blir
  `"unknown"` — boten står inte i någon cell. Det är något annat än en missad
  stämpling, och `verdict` är det som skiljer dem.
- Fogning mot rådataserien sker på radindex, med `t` avrundat till 3 decimaler
  som fallback.

### Genomsläppningar (ingen tolkning)

| Fält | Källa | Regel |
|---|---|---|
| `plan` | spår B | **rå** genomsläppning |
| `verdict` | spår A | rå genomsläppning |
| `attr` (per försök) | A:s `<ben>.attr.json` | läses av adaptern, **binds inte** här |

**`plan` får aldrig "städas".** B:s `runway`, `sj_progress` och `first_air_vz`
är signerade och bär sin frånvaro i egna `*_measured`-flaggor, just därför att
`-1.0` och `0.0` är giltiga avläsningar. En adapter som översätter dem till
`unknown` återinför exakt den bugg B redan har rättat — en bot en enhet förbi
läppen skulle bli en icke-mätning i just den zon V296 handlar om.
Testet `PlanPassthrough` vaktar detta.

`attr` bär A:s per-försöksattribution (`attribution.cell_id`,
`drop_from_cell`, `start_cell`). Den läses här men **binds inte**: kopplingen
fall → landningscell ägs av klassningen (spår I).
