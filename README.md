# qw-fasttrack

Ägarens fasttrack-workspace för navmesh-experiment. Prototyp — målet är
kortaste möjliga loop **mesh-edit → livetest → bevis** som MCP-verktyg,
kartagnostiskt (map och koordinater är alltid parametrar).

Design + research: `docs/design/2026-07-21-fasttrack-design.md` +
`2026-07-21-research-digest.md`.

## v0 (nu): fasttrack-mcp

Stdio-MCP-server (`fasttrack/mcp_server.py`, ren python3, inga beroenden)
som äger en egen rtx-experimentserver i WSL:

- Portblock: spel **27530** / kontroll **27980** / QTV 29530, systemd-unit
  `fasttrack-server` (Nice=19). Aldrig deckens eller orkestreringens portar.
- Verktyg: `server_up(map)` / `server_down` / `server_status` / `maps_list` /
  `ctl(command)` (rå kontrollverb-passthrough) / `patch_apply(qw-nav-patch/1)` /
  `patch_clear` / `trial(start, target, ...)` / `graph_dump(map, seed)`.
- **Auto-replant:** aktiv patch sparas och återplanteras automatiskt vid varje
  `server_up` (planterade länkar dör vid map-restart — nu osynligt).
- `graph_dump` installerar live-grafen som Movement Lab-overlay och
  returnerar viewer-URL.
- Alla producenter och konsumenter (`graph_dump`, `demo_ingest`, `live_start`,
  `demo_replay_start`, `missing_spec`) använder nu EN kanonisk katalog:
  `route-lab/qw-nav-viewer/overlays`, som 18089-sidecaren och trunk-proxyn
  faktiskt servar. Viewer-worktreet är endast käll-/buildkatalog.

## Demo -> mesh -> produktion

- **`demo_ingest(demo, map)`** — "den här spelarens qwd krävde den här meshen":
  markplatåer -> krävda celler, luftsegment -> krävda hopplänkar (dedupade,
  med uppmätt fart). Diffas mot en `qw-nav-graph/1`-dump (kör `graph_dump`
  först). Ut: coverage-sammanfattning, demo-meshen som viewer-overlay
  (täckta hopp = Jump, saknade = SpeedJump), och en färdig `qw-nav-patch/1`
  för de saknade hoppen. Regel 11.2 per konstruktion: bara placering/mål/fart,
  aldrig trajektorier/inputs. qwd tills vidare (mvd-parser saknas).
  Cell-diffen är validerad mot känd sanning (xersng.qwd flaggar exakt den
  omeshade z=163-hyllan). Hopp-diffen är strikt — den kräver en direkt länk
  mellan ändpunkterna, så bunnyhops längs gåbart golv överflaggas som saknade.
- **Trial v2** stoppar/håller botten, teleporterar och verifierar origin inom
  24u, tar `t0` direkt före `goto`-skrivningen och mäter första mottagna
  15 Hz-statusposition i `arrive_box`. `pass_time_s`, `streak_target` (5),
  `max_time_s` (8) och `attempts_cap` (30) ger konsekutiv streak-gate; fail
  nollställer streaken. JSONL-ledgern bär box/tidsgränser, graf-/patch-SHA,
  matchtag och readback av de tre förbjudna cvarerna plus `rtx_bot_bhop`.
- **`gap_to_proof(demo, map, seed, route, name?)`** — ägd, tidsbegränsad
  demo→gap→patch→bevis-kedja. Vägrar innan mutation om server- eller live-unit
  redan kör; clean-bootar utan patch, dumpar G0, ingestar mot G0, kör Trial v2
  A/B med exakt en `patch_apply`, och kör alltid `patch_clear` + ren restart
  även vid timeout/cancellation. Evidensbunten innehåller gaps, patch,
  per-försöks A/B (elapsed/streak/delta), graf-/patch-/BSP-proveniens och
  cvar-readback, plus SHA-manifest; avbrutna körningar märks `partial:true`.
- **`promote(name, map)`** — experiment -> produktion i ett kommando: vägrar
  utan komplett SHA-verifierad `gap_to_proof`-bunt och uppnådd patchad streak
  (legacy `ok>0` räcker inte), skriver patch + hela A/B-beviset till
  `route-lab/artifacts/nav-patches/` och utkastar hand-off för orkestratorns
  PR-lane. Commit lämnas till operatören (hint returneras).

Registrering (`~/.claude.json` → `mcpServers.fasttrack`): `wsl.exe -d
Ubuntu-24.04 -e python3 /mnt/c/.../qw-fasttrack/fasttrack/mcp_server.py`.
Ny session krävs för att verktygen ska synas.

Smoke: `wsl -d Ubuntu-24.04 -e sh -c 'cd .../fasttrack && nice -n 19 python3 smoke.py'`
(bootar dm3, applicerar det 20/20-bevisade SNG-hoppet som patch, kör 3
försök, dumpar grafen).

## v1: live-viewer + demo-replay (skapandeloopen)

- **`live_start(map, graph_name)` / `live_stop`** — single-owner-brygga
  (enda kontrollägaren; proxy 27981 som `core.Control` auto-routar genom
  via state-fil med nonce-ping) + WS 8093 → viewern på 8090
  (`?graph=<name>&live=<port>`). Livelager: bot som gul kub, aktiv cell
  gul, använda celler röd-bruna, använda länkar het gul→röd-gradient.
  `L` togglar follow-kamera. Utan `?live` = statisk vy som förut.
- **`demo_replay_start(qwd, graph_name)` / `demo_replay_stop`** — spela
  upp en människodemo på meshen UTAN spelserver (WS 8095): använda
  element highlightas under spelarens rörelse; allt meshen SAKNAR glöder
  pulserande RÖTT med exakt geometri (ogrundade markpunkter, länklösa
  traverseringar) — samma diff som `demo_ingest`, som ger patchen.
- Replayservern har en ensam `playing|paused|stopped|finished`-koordinator.
  Textkommandon är `{"cmd":"play|pause|stop"}` och varje frame bär
  `playback.state/t`. Varje klient har en egen writer och en en-slots
  latest-frame-kö, så churn eller en klient som inte läser inte blockerar
  övriga handshakes/frames. Producenter utan `playback` är fortsatt giltiga.
- Offlinevägen totalsorterar samples (även lika timestamps), dedup-celler och
  hopp. `build_timeline` + `missing_spec` verifieras över olika
  `PYTHONHASHSEED` med hash av hela det kanoniska objektet.
- Missing-ground använder ett fps-oberoende 0,10 s ensidigt stabilitetsfönster
  med QWD-veton för apex-vändpunkter och vertikala steg in i en närliggande
  landningsplatå. Livebryggan kräver tre konsekutiva unresolved-ticks med
  |Δz| < 2u. Därmed renderas röda cellglyfer på ytor i stället för i luften.
- **FAS 3 / `bsp-probe`:** `demo_ingest` och `missing_spec` använder nu rex
  releasebinär som fysikorakel när `map` kan lösas till en BSP. Proben laddar
  kartan en gång, tar spelar-origin och spårar hull 1 högst 2u nedåt; ingen
  egen −24u-preoffset görs. `floor_z` är träffens origin-z minus 24u. Punkter
  i dörr-/plat-/train-volymer får `status=unknown`, faller tillbaka på
  heuristiken per punkt och listas explicit i `unknown_fallbacks`. Om processen
  kraschar eller svarar fel kastas hela den partiella klassningen och körningen
  görs om som ren heuristik med strukturerat `fallback_reason`.
- Binären hittas utan PATH-sökning: sätt explicit
  `FASTTRACK_BSP_PROBE=/absolut/sökväg/bsp-probe`, annars provas endast
  `/mnt/c/Users/benya/projects/quakeworld/rex/target/release/bsp-probe`.
  `FASTTRACK_BSP_PROBE_COMMIT` kan sättas för en extern kompatibel binär;
  rex-binären bäddar annars in byggcommitten och exponerar den via
  `--probe-commit`. Kartnamn löses i fasttracks skeleton
  (`~/.local/share/route-lab/nav-ab/qw/maps/<map>.bsp`); en explicit BSP-sökväg
  accepteras också. Output bär `method`, `bsp_sha`, `probe_commit` och flaggade
  per-punkt-fallbacks.
- Kända begränsningar (klarspråk): länkattributionen är geometrisk med
  tolerans (80u) och kan missa/överflagga i täta områden; `used`-listor
  växer obegränsat per attempt (reset vid goto); bottens ruttval är dess
  eget — smoken dömer app-egenskaper, inte ruttval (inspelning 2026-07-22
  visade att botten föredrar norra gångvägen från stillastående framför
  det planterade speedjumpet — fartbandsgate utan ansats, trolig orsak).

## Regler som gäller även här

Förbjudna cvars (`rtx_bot_ledgecap`/`rtx_walljump`/`rtx_doublejump`) pinnade
0 i cfg:en; `nice -19` på allt tungt; regel 11.2 (människodemos = kalibrering,
aldrig trajektorier in i bot-kod); egna portar.

## Bygg och verifiera bsp-probe

Den pinnade fixture som fasttrack-serverns skeleton använder är
`/home/xerial/.local/share/route-lab/nav-ab/qw/maps/dm3.bsp`; den är
byteidentisk med `/mnt/c/nQuake/qw/maps/dm3.bsp`, SHA-256
`aec9edbb727c0a206edc2c0688775ce8242c0d51e1ee7583c7126c76f7c3b2f1`.
Rusttestet använder den senare absoluta sökvägen och är avsiktligt inte
skippbart.

```sh
cd /mnt/c/Users/benya/projects/quakeworld/rex
PATH=$HOME/.cargo/bin:$PATH nice -n 19 cargo test -p rtx-nav --bin bsp-probe -- --nocapture
PATH=$HOME/.cargo/bin:$PATH nice -n 19 cargo build --release

cd /mnt/c/Users/benya/projects/quakeworld/qw-fasttrack
nice -n 19 python3 fasttrack/demo_replay.py \
  --demo /mnt/c/nQuake/qw/matchinfo/demos/xersng.qwd \
  --graph /mnt/c/Users/benya/projects/quakeworld/route-lab/qw-nav-viewer/overlays/fasttrack-graph.json \
  --map dm3 --summary-only
```

Utan `demo_replay.py --map` används uttryckligen heuristiken och en varningsrad
skrivs. `demo_mesh.py --map dm3` använder däremot samma parameter både som
kartnamn i artefakten och för oracle-discovery.

## Roadmap

v1 live-viewer (WS + fork av qw-nav-viewer) · v2 motorgren
(plantcell-verb + SamplingPlan/p8) · v3 rex-custom-mesh-lane.
Se designdokumentet.
