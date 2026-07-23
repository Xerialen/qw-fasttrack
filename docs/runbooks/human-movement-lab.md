# Human Movement Lab — monitorera en människa live och gör gap-analys

Etablerad 2026-07-23 (första sessionen: RA-mellanledge + hexagon-hoppen).
Syfte: samsyn människa↔agent om hur en rutt/ett hopp görs, sedan gap-analys
mot navmesh/länkar/botkod. Människan spelar på en **botlös** lokal server;
agenten ser allt i data; ägaren ser allt i Movement Lab-viewern.

Kräver build med `players[]` i status-verbet och navmesh-bygge på botlösa
labbservrar (båda 2026-07-23, `rex-merge-trial`: control.rs `status_json`
players-array; population.rs bygger mesh när `rtx_control_port` är satt).

## Rigg (allt i WSL, systemd --user)

| Del | Port/unit | Start |
|---|---|---|
| Spelserver dm3, 0 bottar | 27530 / `fasttrack-server` | `core.server_up('dm3', bots=0, lib=<players-kapabel .so>)` |
| Kontroll | 27980 (proxy 27981) | ingår i servern |
| Live-brygga + viewer | ws 8093 / `fasttrack-live-bridge`, 8090 / `fasttrack-viewer` | `core.graph_dump('dm3', [192,-208,-176], '<namn>')` → `core.live_start('dm3', '<namn>')` |
| Replay-loop (för ägarens ögon) | ws 8095 / `fasttrack-replay` | `core.demo_replay_start('<qwd>', '<grafnamn>', speed=1.0)` |

Ägaren ansluter ezQuake: `connect 127.0.0.1:27530` (LAN: `192.168.86.20:27530`).
Live-vy: `http://127.0.0.1:8090/?graph=<namn>&live=8093` (+`&overlay=<namn>`).
Replay-vy: samma med `live=8095`. Viewern binder loopback — öppnas på pinnacle.

## Arbetsflödet

1. **Boot**: `server_up(bots=0)` → `graph_dump` → `live_start`. Verifiera med
   `scripts/ws_probe.py 5` (frames flödar, tom aktörslista).
2. **Människan spelar.** Bryggan attribuerar position→cell 15 Hz; nya
   mesh-luckor (mark utan cell / traversal utan länk) ackumuleras per aktör.
   Läs dem via proxyns `__missing__` eller följ live med
   `scripts/follow_live.py` (Monitor-vänlig: zonbyten + nya luckor + stopp).
3. **Precision = pmove-push** (default sedan 2026-07-23; mätgrindad).
   `core.live_start(..., push=True, record='<jsonl>')` ger auktoritativ
   FL_ONGROUND + servervelocity per serverframe — kontaktsekvens som DATA.
   Ingest: `demo_mesh.load_samples_jsonl(path)` →
   `extract(samples, authoritative_mask=mask)`. Fallback för builds utan
   `rtx_telemetry`: ägar-qwd (`/record`) → `core.demo_ingest`. Serverside-MVD
   spelas in som granskningsartefakt (`cmd record`), ingestas aldrig.
4. **Gap-analys → spec** i `route-lab/artifacts/nav-patches/dm3-<namn>-missing-spec.json`
   (`qw-missing-spec/1`). Etablerade fält utöver basen:
   - `canonical_jumps[]`: namngivna hopp (ägarens begrepp, t.ex. "norra tur")
     med `variations_live[]` (bryggdata, teknik-taggade) och
     `variations_demo[]` (ingest-data med v_req + källdemo), spridningar,
     `p8_link`-korsreferens där p8-kandidaten har certifierad motsvarighet.
   - `router_today`: Dijkstra på live-grafens JSON (cells/links med cost) för
     dagens omväg vs direkthoppet — kvantifierar genvägens värde.
   - `extreme_jumps_*`: ägarens ackumulerad-fart-hopp (800u+ är ÄKTA, se
     lärdomar) — inkludera, aldrig filtrera.
   - `owner_intent`: ägarens riktning/syfte med egna ord.
   - **Statusmärkning obligatorisk** (sols review 2026-07-23, se
     `docs/reviews/2026-07-23-sol-gap-spec-format-review.md`):
     `ready_candidate`/`chain_suspect`/`evidence_only` per variation;
     `takeoff_speed_actual < 0.98·v_req` ⇒ `chain_suspect`. `selected_candidate`
     är null tills exakt payload valts + ägarbekräftats. Spec-bygget ska bli
     `gap-spec build/check --ready` (deterministiskt CLI) — tills dess: följ
     reviewens krav manuellt.
5. **Visa förståelsen i viewern**: skriv `qw-nav-overlay/1` till
   `route-lab/qw-nav-viewer/overlays/<namn>.json` — rj-start/rj-goal-markörer
   på faktiska takeoff/landningar (reps i namnen) + polylines (demospår eller
   schematiska bågar) — och loopa relevant qwd via `demo_replay_start`. Ge
   ägaren URL med `graph+overlay+live`. Bekräfta med ägaren att det är rätt
   hopp INNAN spec:en låses.

## Arv från lifts-to-SNG-lösningen (2026-07-22) — gäller ALLTID här

- **Kuratera per länk.** Bulk-plantering av 27 länkar förorenade fokusruttens
  routing (0/15). Plantera EN länk → trial → nästa. Aldrig hela patch-filen.
- **Emissionstaket.** Så länge 43a471c är tillbakarullad (merge-builden) kan
  generatorn inte nativt emittera hopp över ~408 v_req — allt över det MÅSTE
  planteras. Kandidatselektionen (lägsta v_req per sektor) gör dessutom att
  drop-länkar slår korsningar även med höjt tak.
- **Slutekvationen.** Ankomstfarten vid avstampskanten avgör allt (leap-band
  0,98·v_req). Extrahera människans faktiska avstampsfart ur demon
  (`takeoff_speed_actual` i specen, landnings-verifierad mätning) och jämför
  mot ingest-v_req: **systematisk inflation avslöjar hop-kedjor** som
  grounded-masken missat — plantera då den korta kedjelänken (p8-klass), inte
  den långa enhopps-tolkningen.
- **Trial-protokoll vid plantering**: `core.trial(...)` med `settle_s=6.0` på
  dm3 (hisscykler), evidensledger med proveniens, förbjudna cvars läses 0.

## Regel 11.2

Placeringar, v_req och timing ur ägardemos är kalibreringsbevis och får ligga
i specar/patchar. Trajektorier/usercmds går ALDRIG in i botkod — de får bara
visualiseras (overlay/replay är review-ytor).

## Ärr (lärdomar 2026-07-23)

- **EN svarsläsare på 27980.** Proba ALDRIG kontrollporten direkt (nc etc.)
  medan graph_dump/brygga kör — svaren interfolieras över anslutningarna och
  dumpen hänger/dör på timeouts. Allt går via `core.ctl()` (auto-routar till
  proxy 27981 när bryggan lever) eller väntar tills kanalen är fri.
- **Ägarens outliers är data.** 800–980u-traversals = ackumulerad bhop-fart,
  ägarverifierade. Verifiera mot geometri (tele-ändpunkter) i stället för att
  avfärda på distans.
- **Två tekniker per korsning**: rim-till-rim-kedja (korta hopp, två perfekta
  landningar) vs full-clearance (ett svep golv-till-golv). Emission bör sikta
  på full-clearance. Klassa variationer per teknik.
- **Bryggans z är origin-z** (~fot + 25–35u över cell-z). Matcha i XY med
  generös z-tolerans.
- **Zombie-klient**: en dödad klientprocess ligger kvar i status/frames tills
  serverns timeout (≈45 s). Vänta ut den innan "tom server" bekräftas.
- **`wsl -e bash -c` + kommandosträng som börjar med `/mnt/...`** manglas av
  MSYS-pathkonvertering (→ `C:/Program`). Inled med `cd /tmp &&` e.dyl.
- **Monitor-följare**: seeda sett-mängden med aktörens befintliga missing-
  lista innan rapportering (annars dumpas hela backloggen som "nya" på första
  framen). `follow_live.py` gör det numera.
- **Ingen bot behövs för navmesh**: sedan population.rs-patchen byggs meshen
  på botlösa servrar när kontrollporten är satt; `wait_ready(expect_bots=False)`.
- 15 Hz-bryggans uppgradering till 77 Hz är loggad som öppen fråga i
  `docs/findings-log.md` (RTT-multiplikation vs server-side push).

## Ärr från iterationsloopen (2026-07-23 em, RA tunnel→topp)

- **`unlink` kör INTE `rebuild_derived()`** — bara `planlink` gör det. Efter
  varje remove-batch: replanta valfri egen länk (unlink + planlink) för att
  tvinga om reachability/LOD-tabellerna, annars planerar routern på inaktuella.
- **`graph_dump` exporterar tombstonade länkar** (dump-verktyget ignorerar
  removed-flaggan). Id-uppslag mot dump efter unlinks är opålitliga — verifiera
  alltid mot motorn (`unlink <id>` svarar "already unlinked", `penalties <bot>`).
- **puppet-`goto` ≠ `ra_trial`**: puppet-routern exekverar nativa speedjumps
  som produktionsexekutorn vägrar fail-closed; goto-stallvakten är rak-XY mot
  slutmålet och falskstallar rutter som passerar under målet (RA-golvet).
  Mät item-mål med `ra_trial` (rörelsebaserad 1 s-stall, äkta pickup).
- **Planterade länkar (planlink, curl_gain 12) exekveras av produktionen; nativa
  i samma geometri vägras.** Kuratera genom att ersätta trasiga nativa klasser
  med planterade payloads ur ägarfacit — inte genom att bara sänka kostnader.
- **Straffminnet villkorar beteendet**: failed-link-penalties (se `penalties`-
  verbet) styr replans; ett "fungerande" tillstånd efter timmar av trials kan
  bero på ackumulerade straff och överlever INTE serveromstart. Verifiera
  alltid gates på färskt omstartat tillstånd innan de bokförs.
- **Bot-iterationer kräver poll-brygga**: pmove-pushen exkluderar bottar
  (control.rs-filtret) — kör `live_start` utan `push` när ägaren ska se botens
  försök live.
- **Gate-verktyg**: `scripts/ra_gate.py <bot> <threshold> <streak>` driver
  ra_trial via proxyn (bryggan behåller sin kanal). Stora resultatevent
  (≤4096 samples) kan blockera kanalen i sekunder — generösa timeouts.
- **Fler trial-scenarier (2026-07-23 kväll)**: `ra_trial`-verbet har utöver
  RA-scenarierna även `sng_mega_w`/`sng_mega_s` — exakta SNG-tele-spawnsen
  (-880,-232,-16)/(-632,-680,-16) → SNG-megan (-720,80,160), hälsobaserad
  pickup-signal (≥199 hp + SUPERHEALTH + trigger konsumerad). Planned-drop-
  förbudet gäller bara RA-klättringen; mega-rutten får routa över planerade
  drops (fall >56u/stall 1s failar fortfarande). Driver med baselineprotokoll:
  `scripts/mega_gate.py <bot>` (completion 5/5 → rekordjakt → bekräfta 5/5 =
  ny baseline → 30 raka missar ⇒ senaste baseline).

## Metodlärdomar (dyraste felen 2026-07-23 — läs INNAN du felsöker routing)

1. **Instrumentera före teorin.** Varje rotorsak i dag kom ur ett live-
   instrument — `penalties <bot>` (straffbilden mid-run), samples-kolumnerna
   route_pos/link i ra_trial-resultatet, `initial_route`, unlink-felsvaret
   som motorprobe. INGEN kom ur kostnadsaritmetik. Timmar brändes på att
   räkna på dump-kostnader; produktionsprissättningen (banded + hazard +
   straff + jitter) syns inte i dumpen. Offline-Dijkstra på dumpen används
   för EXISTENS/FORM-frågor ("finns speedjump-fri väg?"), aldrig för
   "varför valde routern X".
2. **Grafredigerings-okänslighet = kodlane-signal.** Om trajektoria och
   tider är IDENTISKA efter en edit som borde ha påverkat (t.ex. borttag av
   länken beteendet ser ut att använda), sluta omedelbart med mesh-kirurgi —
   beteendet ägs av exekutor/pursuit-kod. Verifierat brutalt: 8688 + alla
   hyllhopp borttagna → exakt samma fall på hundradelen.
3. **Enumerera hela geometrifamiljen före borttag.** Nativa emissioner har
   tvillingar och dubbletter (41448/41449; 41166:s grannar). En-länk-i-taget
   blir whack-a-mole med en hel replan-cykel per varv. Sök på geometri-
   fönster (källcell-band → målcell-band), granska listan, ta klassen.
4. **Instrument är läges-bundna.** `route <bot>` visar stale/annan rutt
   medan ra_trial kör (item-trialen har eget ruttobjekt). Validera
   instrumentet i aktuellt läge innan du drar slutsatser ur det.
5. **Boka aldrig ett resultat utan omstartsverifiering.** Dagens "6/6 @
   11.39" var delvis villkorat av timmars ackumulerat straffminne och kom
   inte tillbaka efter omstart (blev 7/8 @ 11.6–11.9 + en hot-entry-krasch
   tills även de heta pit-hoppen kuraterats bort). Gate-siffror bokförs
   ENDAST från färskt omstartat tillstånd.

## Se även

- `docs/TOOLS.md` — **verktygsmanifestet** (engelska, modellagnostiskt):
  varje verktyg → processteg, för alla LLM:er inkl. Codex CLI
- `docs/runbooks/qwd-till-gron-rutt.md` — från qwd till certifierad rutt
- Skill `movement-lab` (`~/.claude/skills/movement-lab/`) — operatörsingång
- Specar: `route-lab/artifacts/nav-patches/dm3-ra-mellanledge-missing-spec.json`,
  `dm3-bowl-corridor-missing-spec.json` (referensexempel på formatet)
