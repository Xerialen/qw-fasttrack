# qw-fasttrack

**The measurement bench for [qw-ctf/rtx](https://github.com/qw-ctf/rtx) development.**

rtx is a Rust bot engine for QuakeWorld: navmesh generation and a movement
executor (bunny-hop, speed jumps, combat) shipped as a game library on an
mvdsv server. Developing it raises a question the engine repo itself cannot
answer: *how do you know a movement change actually works?* Watching the bot
play is not evidence. qw-fasttrack exists to make rtx development empirical.

This repo contains **no bot code**. It is a pure-Python harness (stdlib
only) that owns a dedicated rtx experiment server and drives it over the
engine's control port.

## What this adds to rtx development

**Bookable trials instead of impressions.** `core.trial()` teleports the
bot, issues a goto, and measures arrival from received 15 Hz status
positions against an arrive-box — with streak targets, time bars, and
fail-closed provenance (graph SHA, active-patch SHA, cvar readback) attached
to every run. A movement claim becomes *"5/5 inside the box under the human
corpus median, from a freshly restarted server"*, not *"looks good"*.

**Live mesh surgery without recompiling.** `planlink` / `plancell` /
`unlink` edits against the running graph, wrapped in a patch format
(`qw-nav-patch/1`) that auto-replants on every server restart. The
edit → trial → evidence loop runs in seconds, so nav-graph hypotheses are
tested at the pace they are formed. Curl-profiled plants (entry aim, switch
distance, landing aim as plant-time cvars) let a *curved* human jump be
expressed as a single certified link.

**The Human Movement Lab.** A human plays on a bot-less rtx server; a live
bridge attributes every position to a mesh cell at 15 Hz (or authoritative
per-frame pmove telemetry with `push=True`) while a browser viewer renders
the graph live. Demo/pmove ingest turns the session into *gap specs* —
formal records of what the human did that the mesh or executor cannot —
which become the engine's evidence-driven backlog. Findings from this loop
have already landed in rtx branches as control verbs, bot-less mesh builds,
trial instrumentation and executor fixes.

**Regression gates.** The gate runners under `scripts/` encode acceptance
criteria as hard pass/fail streaks with penalty hygiene between attempts, so
engine changes can be re-checked against previously certified routes.

**Scar tissue.** `docs/runbooks/` records the operational lessons that cost
real debugging time — the single-reader control port, link IDs not being
stable across restarts, penalty memory conditioning behavior, plant flight
physics (`distance = v_req × airtime`), the library-deploy traps. New
sessions (human or agent) start from these instead of rediscovering them.

Evidence produced here is archived in the companion repo
[route-lab](https://github.com/Xerialen/route-lab): route specs, curated nav
patches, corpus baselines, and the booked gate results.

## Layout

| Path | What |
|---|---|
| `fasttrack/core.py` | The harness: server lifecycle, control client, trial v2, patch apply, live bridge/viewer, demo ingest |
| `fasttrack/mcp_server.py` | Stdio MCP wrapper exposing the same tools to agents |
| `scripts/` | Gate runners and geometric link-curation tools |
| `docs/runbooks/` | Operating procedures + accumulated scars (start with `human-movement-lab.md`) |
| `docs/TOOLS.md` | Model-agnostic tool manifest (English) |
| `docs/solutions/`, `docs/findings-log.md` | Solved problems and open questions, with evidence |

Runs under WSL/Linux (systemd user units, Linux sockets). Requires an rtx
build with the control port enabled; maps and server binaries come from your
own environment, not this repo. MIT license. Working language of most prose
is Swedish; `docs/TOOLS.md` is the English entry point.

---

## Operativ referens (svenska)

### MCP-servern

Stdio-MCP (`fasttrack/mcp_server.py`, ren python3, inga beroenden) som äger
en egen rtx-experimentserver i WSL:

- Portblock: spel **27530** / kontroll **27980** (proxy 27981) / QTV 29530,
  systemd-unit `fasttrack-server` (Nice=19).
- Verktyg: `server_up(map)` / `server_down` / `server_status` / `maps_list` /
  `ctl(command)` (rå kontrollverb-passthrough) / `patch_apply(qw-nav-patch/1)` /
  `patch_clear` / `trial(start, target, ...)` / `graph_dump(map, seed)`.
- **Auto-replant:** aktiv patch återplanteras vid varje `server_up`.
  OBS: länk-ID:n är INTE stabila över omstarter — removes måste kurateras
  geometriskt per boot (se `scripts/hexagon_curate.py` som mall).
- **`server_up` utan `lib=` deployar DEFAULT_LIB** — ge alltid explicit
  `lib=` när riggen kör en specifik motorgren.

### Demo → mesh → produktion

- **`demo_ingest(demo, map)`** — "den här spelarens qwd krävde den här
  meshen": markplatåer → krävda celler, luftsegment → krävda hopplänkar.
  Diffas mot en `qw-nav-graph/1`-dump. Regel 11.2 per konstruktion: bara
  placering/mål/fart, aldrig trajektorier/inputs.
- **Trial v2** — stop/hold, teleport+verifiera, mät första 15 Hz-position i
  `arrive_box`; streak-gate med JSONL-ledger som bär graf-/patch-SHA och
  cvar-readback.
- **`gap_to_proof(demo, map, seed, route)`** — ägd demo→gap→patch→bevis-
  kedja med clean-boot, G0-dump, A/B-trial runt exakt en `patch_apply`.
- **`promote(name, map)`** — experiment → produktion; vägrar utan komplett
  SHA-verifierad bevisbunt; skriver till `route-lab/artifacts/nav-patches/`.

### Live-viewer + demo-replay

- **`live_start(map, graph_name)`** — single-owner-brygga (proxy 27981,
  auto-routning i `core.Control`) + WS 8093 → viewer på 8090
  (`?graph=<namn>&live=8093`). `push=True` ger pmove-telemetri per
  serverframe med `record=` till JSONL.
- **`demo_replay_start(qwd, graph_name)`** — människodemo på meshen utan
  spelserver (WS 8095); allt meshen saknar glöder rött.

### Regler som gäller även här

Förbjudna cvars (`rtx_bot_ledgecap`/`rtx_walljump`/`rtx_doublejump`) pinnade
0; `nice -19` på allt tungt; regel 11.2 (människodemos = kalibrering, aldrig
trajektorier in i botkod); egna portar; **en svarsläsare på kontrollporten**
(allt via `core.ctl()`/proxyn).
