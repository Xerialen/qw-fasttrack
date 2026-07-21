# Research-digest 2026-07-21 — underlag för fasttrack-designen

Fyra parallella research-pass (read-only) samma kväll. Citat = file:line
i respektive repo vid research-tillfället.

## A. Motorns live-mutationsyta (ra-on-main + nav-ab)

- Kontrollkanalens alla verb: status, links, prep, teleport, goto, rj,
  fly, hold, stop, ra_trial, set, get, cmd, cell, route, curls, probe,
  curl, planlink, planrj, planrjraw, unlink (`rtx-game/src/control.rs`
  parse ~319, exec 468–519). Geometri-mutation = ENDAST
  planlink/planrj/planrjraw/unlink.
- `plant_speed_jump` = push_link (inkrementell adjacency, aldrig stale)
  + side-table (`rtx-nav/src/navmesh/mod.rs:1407,713`).
  `rebuild_derived` (mod.rs:1420) = ENBART build_reachability +
  build_lod. Ledge/hazard/water-flaggor byggs ej om (behöver BSP) men
  läses via `.get().unwrap_or(default)` — inga paniker, nya
  celler/länkar läser säkra defaults.
- **plantcell är contained (S–M, ~40–80 rader):** `add_cell` finns
  privat (mod.rs:1600–1607), uppdaterar cells+adjacency+grid korrekt;
  reach+LOD täcks av rebuild_derived; enda designfrågan är vilka länkar
  som syntetiseras (samma nearest()-mönster som planlink).
- `unlink` = +100000 kostnads-surcharge (nav_edit.rs:87–107), ingen
  removal/reindex; reversibel först vid map-restart. Plantering är
  append-only → plant/unlink-cykler läcker en död länk per varv;
  periodisk `map`-restart krävs för reclaim.
- Serialisering: `nav_dump` + grid_bracket_build skriver
  `qw-nav-graph/1` — LOSSY (inga RJ-fire-params/hook/plat/gate-payloads;
  bracket-varianten bär dock speed_jump_payloads). Ingen load-path
  finns; NavGraph saknar serde. Full hotswap = L (swap-slotten finns i
  poll_navmesh_build, kostnaden är formatet).
- SamplingPlan-wiring in i live-servern: ~30–60 rader i 2 filer
  (cvar-gated pitch, träd plan genom build_navmesh); 120–200 rader med
  manifest-loader. `build_with_sampling` bygger BARA skelettet — splices
  + flaggor + derived körs efteråt (som grid_bracket_build gör:
  438–440). Dubblar byggkostnaden (legacy-graf byggs också som vittne).

## B. Rex-klientens navmesh-väg (dragonbot + match-deck)

- rtxerial LADDAR inbäddad artefakt (go:embed dm3-rtx-nav.json,
  `cmd/rtxerial/main.go:25–26,55`) — karvar INTE från BSP. Loadern
  validerar bara schema=="rtxerial.nav.v1" + länkindex i range
  (`nav.go:34–50`) — ingen BSP/commit-cross-check.
- MEN: med Nano-brain kopplad (deckens normalläge) styr HJÄRNANS egen
  BSP-karvade mesh matchrörelsen (`controller.go:294–298`); inbäddade
  klientmeshen styr autopilot mode=route + legacy no-brain.
- Formatgap qw-nav-graph/1 → rtxerial.nav.v1: ~15 rader (links
  tuple→objekt, schemanamn, cosmetics; grid ignoreras).
- Per-seat-pinning finns: `artifactPath` i bot-spec → content-addressed
  pin (`control_deck.py:1403–1466`). Två seats med olika meshar i samma
  session är redan en egenskap. `client_build` bygger INTE go-binären —
  manuell `go build` krävs.
- movement_* -verktygen: lease-gated (exklusiv, TTL max 300s,
  LOCAL_ONLY i tre lager), mcp_server.py är enkeltrådad blockerande
  stdio-proxy (en lång call blockerar allt).

## C. Friktionsboken (route-lab)

- Patchflödet idag: viewer-editor → draft-fil → ORKESTRATOR-GRANSKNING
  (minuter–timmar) → atomisk planlog-export till polled dm3-patch.json
  → DEV-driverns 60s-poll → apply i trial-gap (global trial-guard) →
  planlinks dör vid map-restart, drivern replanterar.
- Rebuild-cykel: bygge ~100 CPU-min kallt under heavy-lock (WAIT om
  hållen) + ~10 min navmeshbygge (grid-bracket 21427 celler = 10.7 min
  på vmonster) + parity-guard + drillar (max 20/hopp).
- route_smoke = offline A*-gate kandidat vs MAIN (sekunder, bra
  verktyg; gate-STATUSEN är procedur).
- Deck-lärdomar: EN kanonisk deck per host (min run.ps1 på 8765 dödades
  av orkestratorn — kanonisk deck kör 8767); sessions-nonce knuten till
  deck-PID; exklusiv movement-lease; enkeltrådad MCP-shim.
- Flybart (procedur, knutet till delade MAIN/DEV-planen):
  granskningsordrar, atomexport-ceremonin, poll-latens, rundgräns-
  dömning, artefaktrotation, route_smoke-som-gate, parity-rapportrader.
- EJ flybart: förbjudna cvars (ledgecap/walljump/doublejump),
  nice-containment, LANISTER-capture-företräde, regel 11.2,
  kompilering + navmeshbyggtid, trial-guard-serialisering.

## D. Viewer-arkitekturen (qw-nav-viewer)

- wgpu29+winit30+web-sys, retained buffers: mesh/liquid/surfaces/lines
  (`gpu.rs:21–24`), en render-pass. Graf-overlay CPU-byggs till
  surfaces+lines (`overlay.rs:45–274`); markörprimitiver
  (cuboid/cross) finns redan (overlay.rs:239–271).
- Eventloopen har exakt rätt strömningsmönster: EventLoopProxy →
  UserEvent → user_event → request_redraw (main.rs:45–93, 1604–1676).
  WS-onmessage → proxy.send_event är samma mönster som fetch.
- Ingen WebSocket idag; web_sys-features + serde finns —
  inga nya crates. "Live" idag = filpolling (live_overlays.py:18089,
  Trunk-proxy).
- KRITISKT: graf-JSON bär redan stabila `link_ids`/`cell_ids`
  (parallella arrays) som viewern SLÄPPER (saknade serde-fält,
  graph_data.rs:20–36). Två fält + två HashMaps ger robust
  id→segment-mappning + version-mismatch-guard.
- Rekommenderad integration: femte GPU-buffer för live-lagret (ALDRIG
  rebuild av statiska 120k-länksbuffern per frame), ControlFlow::Poll
  medan live, follow-kamera via frame()-matematiken, WS-proxy-stanza i
  Trunk.toml. Totalt ~250–350 rader över ~6 filer.

## Övrigt bevisläge samma dag (kontext)

- sng-trial 20/20: planterad direktlänk (from (−128,832,120), takeoff
  (−140,780,120), tgt (−303,526,120), v_req 460, tvåfas-curl
  gain 12 / entry (−235,675) / switch 160 / landing (−303,526)) —
  botten klarar hoppet varje gång med rätt geometri. Harness + rådata:
  route-lab/artifacts/sng-trial/.
- Människokalibrering: route-lab/artifacts/human-calib/
  dm3-stairs-sng-speedjump-xersng.json (tvåstegskedja via omeshad
  z=163-hylla; empirisk fartgräns steg 2 mellan 365 och 382 ups).
- z=163-hyllan omeshad även i p8 (området 8-förfinat men inga celler på
  hyllnivån) → trolig rotorsak: carvens lutnings-/rim-acceptans, inte
  pitch. p8-smoke = FAIL alla tre mål (kandidaten tappar speedjumps).
- Hand-offs i dumpen/bots/: benchwall-scoreboard (levererad+accepterad),
  hexagon-relayout, sng-speedjump (patch bevisad + generatororder).
