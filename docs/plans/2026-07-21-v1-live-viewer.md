# Plan: fasttrack v1 — live-viewer (bot i realtid på karta + navmesh)

**Rev 3.** Rev 2 efter sols planreview varv 1; rev 3 = Claudes skiljedom
efter varv 2 (iterationstaket: 2 varv, inga fler). **Avsnittet "Skiljedom
varv 2" sist i dokumentet ÖVERSTYR motsvarande punkter i uppgifterna** —
läs hela planen först, sedan skiljedomen.

**Ägaruppdrag (ordagrant):** "bygga en ny version av Quake movement lab där
du kan i realtid se både botten hoppa på banan och på navmeshen och de
element av navmeshen som använts live ska vara tydligt synliga." Kartagnostiskt.

Detta dokument är kontraktet: självbärande, utföraren behöver inte
sessionskontext. Utföraren rapporterar varje avvikelse från planen.

## Kontext för utföraren

- **qw-fasttrack** (`C:\Users\benya\projects\quakeworld\qw-fasttrack`, WSL:
  `/mnt/c/Users/benya/projects/quakeworld/qw-fasttrack`): prototyp-workspace.
  v0 finns: `fasttrack/core.py` (experimentserver spel 27530 / kontroll 27980 /
  QTV 29530, systemd-unit `fasttrack-server`, Nice=19), `fasttrack/mcp_server.py`
  (stdio-MCP, 11 verktyg). Servern kör rtx-modulen med en kontroll-TCP-kanal:
  newline-JSON, requests `"<id> <verb> <args>\n"`, svar `{"id":..,"ok":true,
  "data":{...}}`, events `{"ev":...}` på samma socket.
- **KONTROLLKANALENS HÅRDA BEGRÄNSNING** (verifierad: route-lab
  `plugins/qw-bot-control/skills/operate-qw-bot-lab/references/control-contract.md:5`,
  `ops/parity_readback.py:27`): en NY anslutning ersätter föregående
  eventmottagare. Endast EN klient åt gången kan lita på svar/events.
  Hela v1-designen (T3) följer av detta.
- **Viewern** (`qw-nav-viewer`) ligger i route-lab-repot:
  `C:\Users\benya\projects\quakeworld\route-lab\qw-nav-viewer` (Rust-crate i
  `nav-viewer/src/`). Rust→WASM, wgpu 29 + winit 30 + web-sys, byggs/servas
  med `trunk serve` (kanonisk instans på **8088** — får INTE störas).
  Overlays läses från `overlays/<NAME>-graph.json` via `?graph=NAME`
  (schema `qw-nav-graph/1`: `cells` [[x,y,z],..], `links`
  [[from_idx,to_idx,"Kind",cost],..], plus parallella `cell_ids`/`link_ids`).
  Viewern har egen `AGENTS.md` (fixture-/parser-test- och RUNBOOK-krav vid
  kontraktändring, `AGENTS.md:5`, `RUNBOOK.md:16`) — de kraven GÄLLER för T2.
- Research-fakta (verifierade 2026-07-21 + sol-review; fil:rad = läget då):
  - `gpu.rs:206,286`: celler = triangelytor, länkar = linjer — SEPARATA
    pipelines/buffers/draw-calls. Livelagret behöver därför TVÅ retained
    buffers (`live_surfaces` + `live_lines`), inte "en femte buffer".
  - `overlay.rs:45–274`: graf-overlay CPU-byggs; markörprimitiver
    cuboid/cross finns (`overlay.rs:239–271`).
  - `main.rs:45–93, 1604–1676`: EventLoopProxy → UserEvent → `user_event`
    → `request_redraw` — strömningsmönstret för WS-frames.
  - `main.rs:1570`: tangenten `F` är UPPTAGEN (ramar kartan). Follow-toggle
    tar en ledig tangent — kontrollera tangentkartan i main.rs och välj en
    obunden (förslag `L`); dokumentera valet.
  - `graph_data.rs:20–36`: serde-structen släpper `cell_ids`/`link_ids` —
    läggs till i T2. Faktiska overlays: `fasttrack-graph.json` bär 4621
    cell_ids / 50218 link_ids, u32 räcker.
  - `Cargo.toml:26`: web-sys-featurelistan SAKNAR `WebSocket`,
    `MessageEvent`, `CloseEvent`, `ErrorEvent` — T4 lägger till dem.
  - Overlay-kinds är lowercase i verkliga dumpar (`"walk"`, `"speedjump"`)
    medan viewern jämför `"Walk"`/`"SpeedJump"` (`graph_data.rs:7`,
    `overlay.rs:276`) — T2 normaliserar case vid parse (bonusfix, liten).
- Kontrollkanalens relevanta verb (rtx-game/src/control.rs): `status`
  (per-bot `origin`/`speed`; INGET yaw, INGEN aktiv-rutt — bekräftat),
  `cell x y z`, `route ...`, `goto`, `teleport`. Events är terminala
  (`arrived`, `goto_stall`) — `goto` är ett request-verb, inte ett event.

## Hårda regler (får inte brytas)

1. Kanoniska instanser orörda: viewer-instansen på **8088** och route-labs
   huvudträd. Allt viewer-arbete i en **git-worktree** av route-lab på egen
   branch (T1), servad på **8090**. route-lab-baseline fångas före start
   (`git -C route-lab status --porcelain > baseline.txt` + start-SHA) och
   jämförs efteråt — kriteriet är NOLL DELTA MOT BASELINE, inte "rent träd"
   (huvudträdet är redan smutsigt).
2. Portar: viewer-dev **8090**; bryggans WS- och proxy-portar är
   KONFIGURERBARA med preflight (bind-test; vid upptagen port: nästa i
   spannet). Default WS **8093** (8091 är upptagen av benchwall-servern!),
   default kontroll-proxy **27981**. ALDRIG 8765/8767 (deck), aldrig
   27504/27506/27508/27516/27521 (orkestrering).
3. Allt tungt i WSL körs `nice -n 19` — inklusive `trunk serve` (T1/T5).
4. Inga ändringar i bot-/motor-kod (rtx-crates). Endast viewer (Rust/WASM)
   + ny python i qw-fasttrack.
5. Regel 11.2: inga trajektorier/usercmds in i bot-kod.
6. Kartagnostiskt: inga kartliteraler i BIBLIOTEKSKOD (live_bridge, core,
   viewer). Testfixturer/smokes får pinna dm3 (de är bevis, inte bibliotek)
   — undantaget är explicit.

## Arkitektur (3 delar, single-owner-design)

```
fasttrack-server (WSL, :27980 kontroll — EN eventmottagare!)
        ▲
        │  ENDA ihållande anslutningen
fasttrack/live_bridge.py  (ny; ensam kontrollägare medan den kör)
   ├── request-PROXY 127.0.0.1:27981 (newline-JSON, samma format):
   │     core.Control routar hit när bryggan kör (state-fil
   │     ~/.local/share/qw-fasttrack/live-bridge.json med portar+pid).
   │     Bryggan skriver om request-id:n (klient-id ↔ server-id-mappning),
   │     broadcastar server-EVENTS till ALLA proxyklienter (klienters
   │     wait_event filtrerar på namn som idag). Ser den ett `goto` passera
   │     → ny attempt: reset av `used`, attempt_id++.
   ├── telemetri: poll `status` ~15 Hz + `cell x y z` per bot → cell_id
   │     (hold-last-valid: oresolverad/luftposition behåller senaste cellen)
   └── WS-broadcast 127.0.0.1:8093 → viewern
        ▼
qw-nav-viewer (worktree-branch, trunk serve :8090, WASM)
        └─ livelager: bot-markör + aktiv cell + använda länkar
           (live_surfaces + live_lines retained buffers)
```

När bryggan INTE kör: state-filen borta → `core.Control` ansluter direkt
till 27980 exakt som i v0. Ingen v0-regression.

Frame-format (bryggan → viewern), version-stämplat:

```json
{"schema": "qw-live-frame/1", "seq": 1234, "t_mono": 12.345,
 "graph": {"name": "fasttrack", "cells": 4621, "links": 50218},
 "attempt_id": 3,
 "bots": [{"ent": 1, "pos": [x,y,z], "speed": 372.1,
           "cell_id": 4711,
           "used": {"cells": [4711, ...], "links": [50259, ...]}}]}
```

- `seq` monotont ökande; `t_mono` = bryggans monotona klocka (sekunder
  sedan brygga-start) — latensmätning görs i bryggan (se T6), inte via
  klockjämförelse i browsern.
- `graph` = namn + counts som mismatch-guard mot viewerns laddade graf
  (matchar de inte → viewern visar varning, ritar inget livelager).
- `used` är PER BOT, deduplicerad och sorterad; nollas vid nytt `goto`
  för den boten (attempt_id++).
- INGET yaw-fält (status exponerar inte yaw); markören är axisaligned.
- INGET route-fält i v1: aktiv-rutt-data finns inte i motorn och
  motorändringar är förbjudna här. "Använda element" (kravets kärna)
  kommer från cellbyten + länkattribution.

Länkattribution (deterministisk regel): när en bots resolverade cell byter
A→B och grafen har en länk A→B ackumuleras länk-id:t. Saknas direktlänk
(15 Hz kan hoppa över mellanceller i luften) hålls A som "pending" i max
1.0 s; varje nytt cellbyte A→C testas tills direktlänk hittas eller
tiden går ut (då ackumuleras bara cellen). Regeln enhetstestas mot en
INSPELAD statussekvens (fixture från ett riktigt SNG-hopp).

## Uppgifter i ordning

### T0 — Repo-kontraktet
- Fyll `docs/current-stage.md` (stage: v1 live-viewer, mål = ägaruppdraget
  ovan), skapa `docs/success-criteria.md` (peka på detta dokuments
  success-kriterier) och `docs/testing-and-validation.md` (smoke + fixtures
  + skärmdumps-checklista). Kort — prototypnivå, men AGENTS.md-gaten ska
  vara uppfylld.
- **Verifiering:** filerna finns, `git status` visar dem staged/committade.

### T1 — Worktree + baslinje
- Fånga baseline: `git -C /mnt/c/.../route-lab rev-parse HEAD` + `git
  status --porcelain` → spara i `qw-fasttrack/docs/plans/
  2026-07-21-v1-baseline.txt`.
- `git -C route-lab worktree add ../route-lab-viewer-live -b
  viewer-live-fasttrack`.
- Kopiera (INTE symlänka — undvik att otrackade dumpar följer med i
  commits) `qw-nav-viewer/overlays/fasttrack-graph.json` +
  `xersng-req-graph.json` till worktreens overlays. Dessa får ALDRIG
  committas på viewer-branchen (lägg i worktree-lokal
  `.git/info/exclude`).
- `nice -n 19 trunk serve --port 8090` i worktreens viewer-katalog.
- **Verifiering:** `?graph=fasttrack` på 8090 renderar som 8088
  (skärmdump båda).

### T2 — Graf-id:n in i viewern
- `graph_data.rs`: `#[serde(default)] pub cell_ids: Vec<u32>` +
  `pub link_ids: Vec<u32>`; vid laddning byggs HashMaps id→index. Guard:
  längdmismatch mot cells/links ELLER dubblett-id → varning i konsolen,
  tomma maps (livelagret blir inaktivt i stället för fel).
- Normalisera kind-case vid parse (acceptera `"walk"`/`"Walk"` lika) —
  åtgärdar den befintliga lowercase-mismatchen.
- Viewer-kontraktskrav (dess AGENTS.md): uppdatera parser-fixture +
  parser-test för de nya fälten (inkl. mismatch-fallet) och RUNBOOK-notis.
- **Verifiering:** `cargo test` grönt i worktreen; browserkonsolen loggar
  `live-id maps: 4621 cells, 50218 links` för `?graph=fasttrack`.

### T3 — Bryggan `fasttrack/live_bridge.py` + core-routning
- Ren python3 stdlib (asyncio; WS-servern implementeras minimalt själv —
  RFC6455 server-handshake + textframes är ~60 rader; ingen pip-install).
- Bryggan är ENSAM kontrollägare: en ihållande anslutning till 27980.
  Proxy-lyssnare på 127.0.0.1:27981 (konfig `--proxy-port`), WS på 8093
  (konfig `--ws-port`); båda med bind-preflight → nästa lediga port i
  +1..+9-spannet; valda portar skrivs till state-filen
  `~/.local/share/qw-fasttrack/live-bridge.json` (`{"pid","proxy","ws"}`),
  som tas bort vid ren nedstängning.
- Proxy-semantik: klientens `"<cid> verb args"` → bryggan mappar cid→eget
  sid, skickar till servern, svarar klienten med dess cid. Server-events
  broadcastas till alla proxyklienter (dagens `wait_event` filtrerar på
  namn — beteendekompatibelt; begränsning: events är inte per-klient-
  adresserade, dokumentera). `goto`-requests detekteras i förbifarten →
  reset av den botens `used`, attempt_id++.
- `core.Control.__init__`: om state-filen finns och pid lever → anslut
  till proxy-porten i stället för 27980. Annars oförändrat v0-beteende.
- Telemetriloop: `status` ~15 Hz; per bot `cell`-uppslag med
  hold-last-valid + länkattribution enligt regeln ovan (id-mappning läses
  från `--graph` = sökväg till `<name>-graph.json`).
- CLI: `--control 27980`, `--graph PATH`, `--ws-port 8093`,
  `--proxy-port 27981`, `--once` (en frame till stdout, exit).
- Enhetstest `fasttrack/tests/test_link_attribution.py`: matar
  attributionslogiken med en inspelad statussekvens-fixture (spela in
  under ett riktigt SNG-hopp; fixturen committas) och asserterar att den
  planterade länkens id ackumuleras exakt en gång per attempt.
- **Verifiering:** (1) enhetstestet grönt; (2) med server+bot uppe:
  `--once` skriver giltig frame med `cell_id` ≠ null; (3) bryggan igång +
  `core.trial(attempts=1)` i annan process: trialen fungerar genom proxyn
  (arrived-event når den) OCH en WS-testklient ser frames med växande
  `used.links` under hoppet — detta är regressionstestet för blocker 1/2.

### T4 — Viewerns WS-klient + livelager
- `Cargo.toml`: lägg `WebSocket`, `MessageEvent`, `CloseEvent`,
  `ErrorEvent` till web-sys-features.
- `?live=<port>` (frånvaro = ingen WS = exakt dagens beteende). Klienten
  ansluter DIREKT till `ws://127.0.0.1:<port>` — localhost→localhost,
  ingen CORS, ingen Trunk-proxy (struken efter review). onmessage →
  parse → `proxy.send_event(UserEvent::LiveFrame(frame))` → uppdatera
  livelagret → `request_redraw`. INGEN ControlFlow::Poll — redraw drivs av
  inkommande frames (sparar CPU/GPU när inget händer).
- Graph-guard: frame.graph.name/counts mot laddad graf; mismatch →
  overlay-text "live: graph mismatch", inget livelager.
- Rendering: två nya retained buffers `live_surfaces` (aktiv cell: ljus
  fylld markering; used.cells: dämpad variant) + `live_lines`
  (used.links: het gul→röd, tydligt skild från statiska kind-färger;
  bot-markör som cuboid-linjer på pos). Buffrarna byggs om per frame —
  de är små (≤ några hundra element); den statiska grafbuffern rörs aldrig.
- Follow-kamera: ledig tangent (förslag `L`, verifiera mot tangentkartan
  main.rs) togglar följning av bot 0 via befintlig frame()-matematik.
- **Verifiering:** med server + brygga + trial-loop: browservyn visar
  botten röra sig, cellhighlight följer, hopplänken färgas het när den
  tas. Skärmdumpar: (a) bot mitt i hopp med het länk, (b) follow-läge,
  (c) `?live` utelämnad = statisk vy; (c) diffas mot T1-baslinjens
  skärmdump (ingen visuell skillnad).

### T5 — MCP-verktyg `live_start`/`live_stop`
- `core.py` + `mcp_server.py`: `live_start(map, graph_name)` →
  (1) startar bryggan som systemd-run-unit `fasttrack-live-bridge`
  (Nice=19) med `--graph overlays/<graph_name>-graph.json`;
  (2) startar viewern som unit `fasttrack-viewer` (`nice -n 19 trunk
  serve --port 8090` i worktreens viewer-katalog) om 8090 inte redan
  svarar — bryggan ÄGER inte viewern om den redan kör manuellt;
  (3) läser state-filen och returnerar
  `http://127.0.0.1:8090/?graph=<name>&live=<ws-port>`.
  `live_stop()` stoppar bridge-uniten (+ viewer-uniten om vi startade
  den) och verifierar att state-filen försvann.
- **Verifiering:** MCP-protokolltest (tools/list visar 13 verktyg);
  `live_start` → URL svarar, `live_stop` → uniten borta, state-fil borta,
  `core.Control` går åter direkt mot 27980.

### T6 — E2E-smoke + latens + dokumentation
- `fasttrack/smoke_live.py` (testfixtur — FÅR pinna dm3, se regel 6):
  try/finally-strukturerad: server_up(dm3) → patch_apply (bevisade
  SNG-hoppet från `smoke.py`) → live_start → trial(3) genom proxyn →
  WS-testklient asserterar att ≥1 frame under trialen bär den planterade
  länkens id i `used.links` → finally: live_stop + server_down.
  Exit 0 + `LIVE-SMOKE: OK`.
- Latensmätning (kriterium 2): bryggan loggar per tick
  `t_status_reply - t_status_sent` (kontrollkanalens RTT) och
  WS-sändtid; smoke skriver ut p50/p95. Kriteriet operationaliseras som:
  p95(status-RTT + brygg-tick + WS-send) < 200 ms. Browserns renderlatens
  mäts inte (ingen gemensam klocka) — noteras som avgränsning.
- README-avsnitt "v1 live-viewer" + `docs/findings-log.md`-post
  (AGENTS.md-kravet) + fixture-notis i testing-and-validation.md.
- Commit i BÅDA repon: viewer-branchen `viewer-live-fasttrack` (endast
  src/fixture/RUNBOOK-ändringar — inga overlay-dumpar; verifiera med
  `git show --stat`) och qw-fasttrack main. INGEN push av
  route-lab-branchen utan ägarens OK.
- **Verifiering:** smoke exit 0 med output klistrad; skärmdumpar (a)–(c)
  bifogade; baseline-jämförelsen från T1 visar noll delta i huvudträdet.

## Globala success-kriterier

1. `smoke_live.py` exit 0 med `LIVE-SMOKE: OK` (körd, output klistrad i
   rapporten).
2. Uppmätt kedjelatens (status-RTT + tick + WS-send) p95 < 200 ms,
   utskriven av smoke.
3. Skärmdump (a) visar använda element (cell + länk) i het färg tydligt
   skilda från oanvända; verifierat okulärt mot färgskalan.
4. Skärmdump (c) utan `?live` är visuellt identisk med T1-baslinjen.
5. route-lab huvudträd: `git status --porcelain` efteråt == baseline-
   filen från T1 (worktree-registrering och viewer-branchen exkluderade).
6. Inga kartliteraler i bibliotekskod (grep `dm3` över
   `fasttrack/live_bridge.py`, `fasttrack/core.py`-diffen och
   viewer-diffen = träffar endast i smokes/fixtures/docs).
7. v0-regression: med bryggan nere fungerar alla 11 v0-MCP-verktyg
   oförändrat (server_status + trial 1x körs som kontroll).

## Explicita antaganden (rev 2)

- A1: `status`-poll 15 Hz är billig (lokal TCP). Degradera till 10 Hz vid
  behov — notera.
- A2: `cell`-uppslag per bot/tick är billigt (BFS-crawlen gör tusentals).
  Cache per positionskvant om det stör.
- A3 (OMSKRIVEN): kontrollkanalen har EN eventmottagare — därför är
  bryggan ensam ägare + proxy. Kortlivade v0-klienter routas genom
  proxyn via state-filen. Events broadcastas till alla proxyklienter.
- A4: Ingen motorändring. Aktiv-rutt saknas i status → inget route-fält.
- A5: trunk/cargo-toolchain fungerar i WSL (8088-instansen byggs så
  idag). `cargo test` förutsätts körbar i worktreen.
- A6: Bryggans egen WS-implementation (stdlib) räcker för en klient på
  localhost; ingen TLS, ingen kompression, textframes only.

## Referens (utom scope, för framtida v1.5)

`qw-analyzer-dm3-routes` (branch `codex/dm3-route-analytics`):
ägargodkänd ruttaxonomi + korpus-medianer per rutt
(`dm3-route-stats.json`) — mänsklig baseline att visa bredvid
trial-resultat senare. Ingen kod därifrån i v1.

## Ändringslogg rev 2 (sol varv 1 → åtgärd)

- B1/B2 (en eventmottagare; goto-reset omöjlig): single-owner-brygga med
  request-proxy 27981 + core-routning via state-fil; goto detekteras i
  proxyn. T3 helt omskriven, regressionstest tillagt.
- B3 (8091 upptagen): default WS 8093, alla portar konfigurerbara med
  bind-preflight + spann.
- B4 (repo-kontraktet): nytt T0 + findings-log i T6.
- B5 (smutsig baseline): kriterium 5 = noll delta mot fångad baseline.
- M1 (frame-schema): seq/t_mono/graph-guard/attempt_id/per-bot used;
  yaw struket; route struket (M-fynd: finns inte i status).
- M2 (T2-kontrakt): pub-fält, dubblett/mismatch-guard, fixture +
  parser-test + RUNBOOK.
- M3 (buffers): två retained buffers live_surfaces/live_lines.
- M4 (F upptagen): ledig tangent, förslag L, verifieras mot koden.
- M5 (web-sys-features): explicit Cargo.toml-uppgift i T4.
- M6 (viewern startas inte): live_start startar/äger viewer-uniten
  vid behov.
- M7 (attribution ej deterministisk): hold-last-valid + pending-regel +
  enhetstest mot inspelad fixture.
- M8 (Trunk-proxy-förvirring): proxy struken; direkt-WS, ?live=<port>.
- M9 (kriterier verifieras ej): latensmätning i brygga/smoke;
  skärmdumpsdiff (c) vs baseline; kriterium 7 v0-regression.
- M10 (kartagnostik vs smoke): regel 6 skiljer bibliotekskod från
  testfixturer.
- M11 (nice på trunk): tillagt i T1/T5.
- Minors: kind-case-normalisering (T2), dedup/sortering av used (schema),
  redraw-på-frame i stället för Poll (T4), try/finally (T6),
  baseline-SHA + exclude av overlays i worktreen (T1/T6).

## Skiljedom varv 2 (rev 3 — ÖVERSTYR uppgifterna ovan)

Sols varv 2: B3/B4/B5 lösta; B1/B2 underkända; tre nya blockers + två
majors. Taket är nått — följande är Claudes bindande avgöranden.

### S1. Exklusivitet (B1 + major "handoff-barriär") — ACCEPTERAD RISK MED SPÄRRAR
Nyckelinsikt: `fasttrack/mcp_server.py` är ENKELTRÅDAD stdio — MCP-anrop
serialiseras per konstruktion, så `live_start` kan inte tävla med en
pågående `trial()` i samma session. Externa direktklienter utanför
core.Control är UTANFÖR KONTRAKT (dokumenteras). Spärrar som byggs:
- `live_start`-sekvens: starta bridge-unit → bryggan ansluter 27980, kör
  readiness (status OK + spot-check enligt S4) → skriver state-filen
  ATOMISKT (temp + rename) FÖRST då. Före state-filen går core-klienter
  direkt; efter går de via proxyn. Ingen övergångslucka i samma session
  tack vare MCP-serialiseringen.
- `graph_dump` (som shellar till dump_live_graph.py = direktklient med
  route-labs control_port_lock) SPÄRRAS medan bryggan kör: state-fil
  finns → felmeddelande "stoppa live-bryggan först". Byggs i T5.

### S2. Terminal-eventkorrelation (B2 + ny blocker 1) — ÄGARROUTNING
Proxyn broadcastar INTE terminala events. Regel:
- `arrived`/`goto_stall` routas ENBART till den proxyklient som skickade
  senaste `goto` för den boten (per-bot ägartabell; bär eventet inget
  bot-id routas till senaste goto-avsändaren globalt — dokumentera vilket
  som gällde efter inspektion av eventpayloaden i praktiken).
- Endast ETT utestående `goto` per bot tillåts genom proxyn; ett andra
  `goto` för samma bot övertar ägarskapet (gamla ägaren får inget — samma
  semantik som motorn själv har vid ny order).
- Övriga events (icke-terminala) broadcastas som tidigare.
- Bryggans egen telemetri (status/cell) konsumerar aldrig terminala
  events — den läser bara request-svar.

### S3. SID-rymd (ny blocker 2) — SPECIFICERAS
Proxyn har: EN central reader-task mot servern; global monoton
SID-räknare för ALLA utgående requests (interna status/cell + alla
proxyklienters); tabell `sid → (klientanslutning|INTERN, cid)`; posten
tas bort vid svar; svar vars klient kopplat ner KASTAS (logg); vid
klient-disconnect rensas dess pending-sids och ev. goto-ägarskap.
Enhetstestas i T3-testfilen (två samtidiga fejkkliente r mot en
fejkserver: id-mappning, disconnect-städning, sen-svar-kastning).

### S4. Graf-identitet (ny blocker 3) — DUBBEL KONTROLL
`name+counts` räcker inte (link-id:n är inte stabila över rebuilds):
- **Fil-fingerprint:** bryggan sha256:ar graf-JSON-BYTES den läste;
  frame bär `graph.sha256` (hex, förkortad 16 tecken). Viewern hashar
  samma bytes den fetchade (sha256 via en liten ren-Rust-implementation
  eller `js_sys`-crypto — utförarens val, ingen ny stor crate) och
  jämför. Mismatch → "live: graph mismatch", inget livelager.
- **Live-spot-check:** vid brygg-readiness slås 20 slumpvalda celler ur
  graf-filen upp via `cell x y z`; avviker något cell-id → bryggan
  VÄGRAR starta med tydligt fel ("graph stale vs live server — kör
  graph_dump om"). Detta fångar rebuild-drift som filhash inte ser.

### S5. State-filens giltighet (major) — NONCE + HÄLSOKOLL
State-filen skrivs atomiskt EFTER readiness och innehåller
`{"pid", "started_at", "nonce", "proxy", "ws"}`. `core.Control` som ser
filen: anslut till proxy-porten och skicka proxy-intern ping
(`"0 __ping__"` besvaras av BRYGGAN själv med `{"id":0,"ok":true,
"nonce":...}` utan server-rundtur); fel nonce/timeout ≤1 s → radera
state-filen, anslut direkt till 27980, logga varning. `live_stop`
raderar filen före unit-stopp.

### Konsekvensändringar i uppgifterna
- T3: += S2-eventroutning, S3-SID-spec + enhetstest, S4-spot-check,
  S5-ping/nonce. WS-frame: `graph.sha256` ersätter counts som guard
  (name+counts behålls som människoläsbar info).
- T4: viewerns guard jämför sha256 (S4).
- T5: `live_start`-sekvensen enligt S1; `graph_dump`-spärren; `live_stop`
  raderar state-fil först.
- T6: smoke lägger till negativtest: (i) `graph_dump` under live →
  förväntat fel; (ii) döda bryggan hårt (`kill -9`), verifiera att nästa
  `core.Control` faller tillbaka direkt + städar state-filen.

### Arbetsdelning för verifiering (gäller sols exekvering)
Sol utför alla bygg-/test-/smoke-steg som är terminalkörbara och
rapporterar output. VISUELLA verifieringar (skärmdumpar a–c, T1:s
8088/8090-jämförelse, follow-kameran) utförs av GRANSKAREN (Claude) i
exekveringsreviewn — sol ska se till att allt är uppe och körbart
(server, brygga, viewer-unit) och dokumentera exakta URL:er/kommandon
för granskarens visuella pass.
