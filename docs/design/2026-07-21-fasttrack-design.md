# qw-fasttrack — design (godkänd av ägaren 2026-07-21)

**Uppdrag:** ägarens fasttrack-workspace för navmesh-experiment. Målet är
kortaste möjliga loop **mesh-edit → livetest → bevis**, exponerad som
MCP-verktyg så att en agent itererar i sekunder — inte procedurer.
Första leveransen inkluderar en ny Movement Lab-version med realtidsvy:
botten på banan OCH på navmeshen, med live-använda meshelement tydligt
markerade.

Forskningsunderlag: `2026-07-21-research-digest.md` (fyra parallella
research-pass över motorn, rex-klienten, friktionen och viewern).

## Princip

Egen isolerad stack. Procedurerna i route-lab (granskningsordrar,
atomisk patch-export, 60s-polls, rundgränsdömning) existerar för att
skydda den delade MAIN/DEV-planen — här finns ingen delad yta, så de
utgår. Fysik + säkerhet behålls (se Regler).

## Komponenter

### 1. fasttrack-mcp (kärnan — Python, stdio-MCP)
Äger en dedikerad rtx-experimentserver (egen systemd-unit i WSL, eget
portblock, ALDRIG deckens portar 8765/8767 eller orkestreringens
27504/06/08/21). Verktygsyta:

- `server_up / server_down / server_restart` — lifecycle med
  **auto-replant**: sessionens aktiva patch återplanteras automatiskt
  efter map-restart (planterade länkar dör vid restart; plantering är
  append-only och läcker → periodisk restart behövs ändå).
- `mesh_plant_link / mesh_plant_rj / mesh_unlink` — direkta
  kontrollsocket-verb (planlink/planrjraw/unlink), trial-guard-medvetna.
- `patch_apply(qw-nav-patch/1)` — hela patchar direkt, ingen ceremoni.
- `bot_teleport / bot_goto / bot_fly / trial(n)` — loopade försök med
  strukturerade utfall per försök (JSONL + summering). Mall: sng-trial-
  harnessen (20/20-beviset 2026-07-21, route-lab/artifacts/sng-trial/).
- `graph_dump` — dumpar live-grafen till viewer-overlay automatiskt.
- Livebrygga: pollar `status` + `route` ~15 Hz → WebSocket → viewern.

### 2. Live-viewern (fork av route-lab/qw-nav-viewer)
Rust→WASM (wgpu+winit). Tillägg (~250–350 rader, inga nya crates):
- WS-klient via web_sys (feature-flagga) → `UserEvent::LiveFrame`
  (samma mönster som befintliga fetch→proxy→redraw).
- Egen FEMTE GPU-buffer för live-lagret (botmarkör, het aktuell leg,
  planerad rutt, tonande spår) — det statiska 120k-länkslagret byggs
  ALDRIG om på live-vägen.
- `link_ids`/`cell_ids` finns redan i graf-JSON men släpps av serde —
  två fält + två HashMap:ar ger stabil id→segment-mappning med guard
  mot grafversion-mismatch.
- Follow-kamera återanvänder frame()-matematiken; HUD-etikett via
  befintlig projektionsväg.

### 3. Motorexperiment-gren (egen fork av qw-ctf/rtx)
Experiment som sedan kan PR:as uppströms via hand-off:
- **`plantcell`-verb** (~40–80 rader, bekräftat contained): `add_cell`
  finns privat och håller cells/adjacency/grid korrekt;
  `rebuild_derived` täcker reach+LOD; övriga sidovektorer läser säkra
  defaults. Ger live-plantering av NY ståbar geometri (t.ex. omeshade
  mikrohyllor som z=163-hyllan på dm3).
- **SamplingPlan-wiring** (~30–60 rader cvar-gated): trär `plan` genom
  `build_navmesh` så en server kan karva 8-pitch-zoner vid start (p8
  live). OBS: dubblar byggkostnad (bygger legacy-grafen också).
- Notera: full graf-hotswap är L (lossless serialisering saknas helt;
  `qw-nav-graph/1` är lossy — inga traversal-payloads) — INTE v1-scope.

### 4. Rex-spåret (valfritt, S)
rtxerial-klienten bär sin navmesh som INBÄDDAD artefakt
(`rtxerial.nav.v1`, go:embed, ingen BSP-cross-check vid load).
Formatskift från `qw-nav-graph/1` är ~15 rader (links tuple→objekt,
schema-namn, cosmetics). `go build` + peka seatens `artifactPath` på
binären → offlinebyggd mesh (p8) styr en livebot via
`movement_autopilot mode=route`. Begränsning: styr INTE brain-driven
matchnavigation (hjärnan karvar egen mesh från BSP) — det är M/L och
utanför scope tills vidare.

## Faser

- **v0:** fasttrack-mcp kring det som finns idag: serverlifecycle,
  länknivå-edits, patch_apply, trial-looper, auto-replant, graph_dump.
  Inga motorändringar. Loopen kollapsar till sekunder direkt.
- **v1:** live-viewern (WS + fork). Ursprungsuppdraget — loopens ögon.
- **v2:** motorgrenen: plantcell + SamplingPlan → cellnivå-edits och
  p8-servrar live via MCP.
- **v3:** rex-custom-mesh-lanen för offlinebyggda meshar.

## Regler som GÄLLER även här (fysik + säkerhet + ägarabsoluter)

- Förbjudna cvars: `rtx_bot_ledgecap` + `rtx_walljump` +
  `rtx_doublejump` pinnade 0 + readback-verifierade (permanent labban).
- Resurscontainment: `nice -n 19` på allt tungt (delad speldator);
  tunga byggen via heavy-lock eller LANISTER (med capture-företräde
  fail-closed).
- Regel 11.2: människodemos styr ruttform/platsval/målvärden — ALDRIG
  trajektorier/usercmds/råkoordinater in i bot-kod.
- Egna portar; aldrig deckens defaultport (8765-incidenten 2026-07-21:
  cross-säte-run.ps1 dödades av orkestratorn).
- Klarspråk i rapporter; trial-resultat på idealiserade startvillkor är
  inte dömda rundor.

## Vad som INTE går att fly (fysik)

Kall kompilering (~100 CPU-min), navmeshbygge ~10 min (dm3 full),
trial-guard-serialisering inom en driver, planterade länkars död vid
rebuild (hanteras med auto-replant).
