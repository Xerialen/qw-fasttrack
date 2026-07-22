# Spec: eliminera apex-artefakter i missing-ground-detektionen

**Status:** implementerad kandidat 2026-07-22; väntar oberoende review. Den
ursprungliga z=163,8-hypotesen och det ensidiga fönstrets fysikargument
korrigerades mot faktisk QWD-data, se avsnitt 8.
**Repo:** `qw-fasttrack` (`C:\Users\benya\projects\quakeworld\qw-fasttrack`, WSL-vy `/mnt/c/...`)
**Berörda filer:** `fasttrack/demo_mesh.py`, `fasttrack/live_bridge.py`, `fasttrack/tests/`
**Ägarkrav (ordagrant problem):** röda missing-cell-glyfer renderas svävande i luften i
Movement Lab. Ägaren: "plattor hör hemma på ytor". Bilden är korrekt — datan innehåller
falska markpunkter.

## 1. Problem

### 1.1 demo_mesh (drabbar demo_ingest, demo_replay, missing_spec — alla delar `grounded_mask`)

`demo_mesh.grounded_mask` (demo_mesh.py:58–67) klassar ett sample som "på marken" om
z-spridningen är < `GROUND_Z_TOL = 1.0` enheter över ett fönster på ±`GROUND_WINDOW = 2`
**samples**. En qwd samplar i klientens fps (~72 Hz för xersng.qwd) → fönstret är ±28 ms.

I toppen av ett Quake-hopp (gravitation 800, JUMP_VZ 270) är vertikalfarten ~0 och
z ändras bara 0,5·800·0,028² ≈ 0,31 u på 28 ms → fönsterspridning ≈ 0,62 u < 1,0.
**Varje hopps apex klassas som mark.** Apexpunkter i luften ⇒ ingen cell kan matchas ⇒
falsk "missing cell" som renderas svävande.

Belägg ur `route-lab/artifacts/nav-patches/dm3-xersng-full-missing-spec.json`
(cells_missing = 38):

- Punkter på z = 99,8 vid (250–375, 554–593). Golvceller i samma XY-område ligger på
  z = 56. Apex från stående origo 56: 56 + 270²/1600 = 101,6 ≈ 99,8 (skillnaden är
  sampeltiming kring apex). ⇒ apex-artefakter.
- Punkter på z = 219,8 nära hyllan z = 163,8: samma mönster en nivå upp.
- Klustret på z = 163,8 (hyllan) är ÄKTA fynd (spelaren stod på riktig omeshad mark)
  och ska överleva fixen oförändrat.

### 1.2 live_bridge (drabbar live server-läget)

`collect_frame` (live_bridge.py:547–552): när ingen cell alls kan matchas ökas
`unresolved_streak`, och vid streak ≥ 3 (15 Hz ⇒ 200 ms) stämplas `note_missing_ground`
på **aktuell position**. Streaken skiljer inte "står på omeshad mark" från "flyger över
omeshad mark" — ett bhop-skutt över ett omeshat område ger ≥ 3 unresolved ticks och
stämplar en missing-punkt mitt i luften. (Notera: över *meshad* mark träffar
airborne-guarden på rad 529–533 i stället, som kräver en upplöst cell — den skyddar inte
här.)

## 2. Icke-mål

- Vattentrampning/hiss-vila som felklassad mark (känd, accepterad begränsning — z-stabil
  på riktigt; dokumenteras, åtgärdas ej).
- Ingen ändring av länk-/traversal-detektionen (`MIN_AIR_S`, fuzzy-matchning, dedup).
- Ingen ändring av viewerns rendering (worktree `route-lab-viewer-live` rörs ej).
- Ingen omkalibrering av `GROUND_Z_TOL` (1,0 u behålls).

## 3. Fix

### 3.1 demo_mesh.grounded_mask: tidsbaserat, ENSIDIGT stabilitetsfönster

Ersätt ±2-samples-fönstret med tidsfönster `GROUND_WINDOW_S = 0.10` s och ensidig
stabilitet:

```
grounded(i) := spread(z över [t_i − 0.10 s, t_i]) < 1.0
            ELLER spread(z över [t_i, t_i + 0.10 s]) < 1.0
```

- **Apex:** båda sidorna innehåller ~4 u höjdändring (0,5·800·0,1² = 4,0 u) → båda
  fönstren spricker → INTE mark. Marginal 4× mot toleransen.
- **Riktig mark:** spikstabil åt minst ett håll → mark.
- **Varför ensidigt:** ett tvåsidigt fönster skulle underkänna de sista ~0,1 s före
  avstamp och första ~0,1 s efter landning (framtida/förfluten luft i fönstret) — vid
  460 ups är det ±46 u ⇒ tappade lip-celler och förskjutna takeoff-/landningspunkter,
  vilket skulle förändra jump-extraktionens (`extract`) beteende. Ensidigt bevarar
  platåkanterna exakt: sista mark-samplet före luft har stabil bakåtsida; första efter
  landning har stabil framåtsida.
- Fönstret uttrycks i sekunder och skalas därmed korrekt för godtycklig demo-fps
  (72/77/högre). Vid färre än 2 samples inom 0,1 s åt ena hållet används de samples som
  finns (kant av demon); ett ensamt sample utan grannar inom fönstret åt något håll
  räknas INTE som mark.

Konstanten `GROUND_WINDOW` (samples) tas bort; `GROUND_WINDOW_S = 0.10` ersätter.
Docstring uppdateras med apex-motiveringen (0,1 s ⇒ 4 u ⇒ 4× tolerans).

### 3.2 live_bridge: streaken kräver per-tick z-stabilitet

I `_actor_aux` läggs `prev_z` till. `unresolved_streak` ökas bara om
`abs(z − prev_z) < 2.0` u för det aktuella ticket; annars nollställs streaken.

- **Stående på omeshad mark:** dz ≈ 0 per tick → streak växer → missing efter 3 ticks
  (oförändrat beteende för det äkta fallet).
- **Flygande över omeshad mark:** vid 15 Hz (66 ms/tick) ger även apexnära ticks
  |dz| ≈ 1,7–3,5 u och stigande/fallande faser ≥ 6 u — tre KONSEKUTIVA ticks med
  |dz| < 2,0 kan inte inträffa i en ballistisk båge (apexen spänner högst ett tickpar).
  Tröskeln 2,0 (inte 1,0) för att tåla nätverksjitter i positionsrapporteringen;
  ballistikmarginalen är ändå ≥ 3× vid omgivande ticks.
- `prev_z` uppdateras varje tick oavsett gren.

### 3.3 Omexport av förorenad artefakt

`route-lab/artifacts/nav-patches/dm3-xersng-full-missing-spec.json` är genererad med
buggen och ska ersättas (samma namn, ny körning) efter fix. Ingen annan konsument har
hunnit läsa den (hand-off ej skickad).

## 4. Verifiering (mätning + kriterier)

1. **Enhetstest, syntetisk parabel** (`fasttrack/tests/test_demo_mesh_grounded.py`, ny):
   72 Hz-samples: platå på z=56 (1 s) → hopp (JUMP_VZ 270, g 800, ~0,68 s luft) → platå
   på z=56 (1 s).
   - Alla platåsamples ≥ 1 sample in från demokanten: `grounded == True`, inklusive
     SISTA samplet före luft och FÖRSTA efter landning (kantbevarandet).
   - Samtliga luftsamples inkl. apex: `grounded == False`.
2. **Enhetstest, bryggstreak** (utöka `fasttrack/tests/test_link_attribution.py`):
   mata `collect_frame`-logikens streakvillkor (bryt ut till hjälpfunktion om nödvändigt
   för testbarhet) med (a) 3 ticks konstant z utan cell → missing stämplas;
   (b) 5 ticks ballistisk z-sekvens utan cell (dz 6→3→1,7→−1,7→−3) → ingen missing.
3. **Regression på riktig demo:** kör `missing_spec` på xersng.qwd mot
   `fasttrack`-grafen. Kriterier:
   - Inga missing-cell-punkter vars z ligger > 40 u över närmsta använda/befintliga
     cell-z i samma 64u-XY-omgivning (automatisk kontroll i ett engångsskript eller
     assert i testet — metoden dokumenteras i PR-texten).
   - z=163,8-klustret (hyllan) finns kvar.
   - `cells_missing` sjunker från 38 (förväntat ≈ 15–25; exakt tal rapporteras).
4. **Visuellt:** starta om `fasttrack-replay-final` (8096, speed 8, no-loop),
   skärmdump av slutläget: alla röda glyfer vilar på ytor. Bifogas rapporten.
5. **Grönt bestånd:** befintliga tester (`test_link_attribution.py`,
   `test_mcp_protocol.py`) opåverkade gröna.

## 5. Antaganden

- xersng.qwd samplar ~72 Hz; fixen får inte anta exakta fps (tidsfönster, se 3.1).
- 40 u-gränsen i verifiering 3 speglar bryggans airborne-tröskel; den är ett
  verifieringsmått, inte en ny runtime-parameter.
- `demo_replay.build_timeline` och `demo_ingest`/`missing_spec` konsumerar
  `grounded_mask` oförändrat — fixen i 3.1 räcker för alla tre.
- Rule 11.2 opåverkad: utdata förblir placerings-/målvärden, inga trajektorier in i
  botkod.

## 6. Frågor till granskaren (navmesh-agenten)

1. **Fönster/tolerans (3.1):** är 0,10 s / 1,0 u rätt avvägning mot meshens egen
   kantsemantik (lip-celler, `STEP_HEIGHT`-platåer)? Finns kartfall (branta ramper,
   trappor i fart) där ensidig stabilitet felklassar åt något håll?
2. **Bryggtröskeln (3.2):** är |Δz| < 2,0 u per tick rimlig mot 15 Hz-jitter i
   positionsrapporteringen, eller finns bättre signal (t.ex. serverns onground-flagga
   om den går att exponera billigt)?
3. **Täckning:** missar specen någon konsument av `grounded_mask` eller av
   `unresolved_streak`-semantiken som skulle ändra beteende oavsiktligt?
4. **Verifiering 4.3:** är "> 40 u över närmsta cell-z i 64u-XY-omgivning" ett hållbart
   automatiskt kriterium för "svävar", eller finns legitima äkta fynd som skulle
   flaggas fel (höga tunna ytor utan celler i närheten)?

## 7. Utförandeordning

1. 3.1 + enhetstest 4.1 → grönt.
2. 3.2 + test 4.2 → grönt.
3. Verifiering 4.3–4.5, omexport 3.3.
4. Commit i qw-fasttrack (meddelande refererar denna spec), rapport med varvräkning.

## 8. Implementationsresultat och surfaced corrections

### 8.1 Korrigering 1: ensidigt fönster kan fortfarande korsa apex

Den rena 0,10 s-implementationen klarade den idealiserade parabeln men
misslyckades mot xersng.qwd: ett fönster kan börja före apex, passera
vändpunkten och sluta på samma höjd. Den verkliga sekvensen
`99.0, 99.5, 99.75, 99.875, 99.875, 99.75, 99.375, 99.0` har bara 0,875u
spread och klassades därför fortfarande som mark. Första realkörningen blev
46 missing cells med kvarvarande z=99/219/227-artefakter och förkastades.

Minimal korrigering: samma 0,10 s/1,0u ensidiga fönster behålls, men en sida
är inte stabil om dess inre peak ligger minst 0,5u över båda ändpunkterna.
Detta är ett apex-vändpunktsveto, inte en omkalibrering av toleransen.
Regressionen använder den exakta kvantiserade sekvensen ovan.

### 8.2 Korrigering 2: landningsplatån får inte lånas från luften

Den utökade syntetiska pinnen på 144 Hz hittade ytterligare ett ensidigt
randfall: sista luftsamplet `z=56.375` kunde använda framtidssidan
`56.375, 56.0, 56.0, ...` som stabil mark. En stabil sida kräver därför också
att steget närmast det aktuella samplet är mindre än 0,25u. Detta bevarar
sista riktiga golvsamplet före takeoff och första efter landing, men kapar den
fallande samplekedjan. I xersng tog det bort 17 falska fall-samples direkt
efter golvkanter; missing-cell-resultatet förblev samma fyra ytfynd.

### 8.3 Korrigering 3: z=163,8-klustret var inte mark

Planens antagande att z=163,8 var en äkta hylla motbevisades av råa samples.
Ett representativt varv stiger
`154.875 → … → 163.875 → 163.875 → … → 154.875` utan markkontakt; ett annat
har samma parabel över grafgolv z=120. Klustret var alltså samma +43,8u-apex
som z=99,8 över z=56, inte en yta. Att bevara det hade bevarat buggen.

### 8.4 Slutlig evidens

- `missing_spec`: 38 → **4** missing cells, z endast 40/56/120;
  `cells_required=182`, `jumps_required=26`, `jumps_missing=17`.
- Automatisk 64u-XY-kontroll: **0** punkter mer än 40u ovan närmaste
  befintliga cell-z; alla fyra har exakt samma-z-granne.
- Direkt replay-dedup: 42 → **9** cellglyfer; skillnaden 4/9 är att
  `missing_spec` medelvärdesklustrar före graph-diff medan replayn behåller
  första råsamplet per 32u-bucket. Alla nio ligger på ytor.
- Omexporterad artefakt:
  `route-lab/artifacts/nav-patches/dm3-xersng-full-missing-spec.json`,
  sha256 `82386b4f4f48ff0bf9d907ec652c820144e140a231df96d3478beba5a4c909d8`.
- Visuell realbrowser-evidens:
  `docs/evidence/2026-07-22-grounded-apex-surfaces.png` från replay 8096.
- `fasttrack-replay-final` startades om med den nya koden och lämnades aktiv
  på 8096, speed 8, no-loop.

Detta var implementationsvarv 1 med tre öppet redovisade self-corrections.
