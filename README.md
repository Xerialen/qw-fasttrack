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

Registrering (`~/.claude.json` → `mcpServers.fasttrack`): `wsl.exe -d
Ubuntu-24.04 -e python3 /mnt/c/.../qw-fasttrack/fasttrack/mcp_server.py`.
Ny session krävs för att verktygen ska synas.

Smoke: `wsl -d Ubuntu-24.04 -e sh -c 'cd .../fasttrack && nice -n 19 python3 smoke.py'`
(bootar dm3, applicerar det 20/20-bevisade SNG-hoppet som patch, kör 3
försök, dumpar grafen).

## Regler som gäller även här

Förbjudna cvars (`rtx_bot_ledgecap`/`rtx_walljump`/`rtx_doublejump`) pinnade
0 i cfg:en; `nice -19` på allt tungt; regel 11.2 (människodemos = kalibrering,
aldrig trajektorier in i bot-kod); egna portar.

## Roadmap

v1 live-viewer (WS + fork av qw-nav-viewer) · v2 motorgren
(plantcell-verb + SamplingPlan/p8) · v3 rex-custom-mesh-lane.
Se designdokumentet.
