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
  `patch_clear` / `trial(start, target, attempts)` / `graph_dump(map, seed)`.
- **Auto-replant:** aktiv patch sparas och återplanteras automatiskt vid varje
  `server_up` (planterade länkar dör vid map-restart — nu osynligt).
- `graph_dump` installerar live-grafen som Movement Lab-overlay och
  returnerar viewer-URL.

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
- **`trial`** skriver nu ett bevisregister (jsonl per aktiv patch).
- **`promote(name, map)`** — experiment -> produktion i ett kommando: vägrar
  utan trial-bevis, skriver patch + proveniens + bevis till
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

## Roadmap

v1 live-viewer (WS + fork av qw-nav-viewer) · v2 motorgren
(plantcell-verb + SamplingPlan/p8) · v3 rex-custom-mesh-lane.
Se designdokumentet.
