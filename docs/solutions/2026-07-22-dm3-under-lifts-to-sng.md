# LÖST: dm3 under-lifts → SNG inom 20 % av människotid (+ RA-tunnel→RA-topp-pekare)

*Skriven 2026-07-22 ~22:45 för nästa agent som tar över repot. Du hittade hit
via AGENTS.md → docs/current-stage.md — det är rätt väg; denna fil är den
kompletta lösningsredogörelsen. Allt nedan är verifierat med körd evidens.*

## Resultatet

Ägarens tid (xersng.qwd, instans t=60,12): **3,18 s**. Acceptans: 5 raka
bot-körningar ≤ 3,82 s (=3,18+20 %) på testservern. **UPPNÅTT och
reproducerat ×4** (tre trialer + en MVD-inspelad): bästa trial 9/10 pass,
tider 3,64–3,71, snabbaste enskilda 3,377. Inspelningen:
`servexeri:/mnt/usb-ssd/non-games/xerbot/xerbot-sng-streak2.mvd` — spelas i
webbläsare: `http://<hubb-LAN>:8095/demo-player/?demoUrl=/demos/files/non-games/xerbot/xerbot-sng-streak2.mvd&map=dm3&from=1`

**Acceptanskommandot (exakt):**
```python
core.trial([551,604,56], [-512,448,96], settle_s=6.0,
           arrive_box=[-632,328,16,-392,568,176],
           pass_time_s=3.82, streak_target=5, max_time_s=8.0, attempts_cap=15)
```
Evidensledger: `~/.local/share/qw-fasttrack/evidence/focusroute.jsonl` (WSL)
— varje rad har full proveniens (graf-sha, patch-sha, cvar-readback med
förbjudna cvars=0). Baseline: `nopatch.jsonl` 0/10.

## Slutekvationen (memorera denna)

- Ankomstfart ≥430 ups vid avstampskanten ⇒ pass 3,64–3,78, deterministiskt.
- 400–430 ⇒ hoppet landar men totaltid ~3,96 (miss).
- <400 ⇒ recovery 5+ s.
- Fysikgolv: hopp ≥~402 ups landar ALLTID (verifierat, inga gropfall).

## De tolv rotorsakerna, i fem lager (alla krävdes)

### Lager 1 — navmesh-data
1. **Generatorns emissionsgräns dubbelmarginaliserad** (v_req≤408 trots att
   planeraren tillåter ≤469) — fixad, rex `43a471c`. Plattformshoppet
   (v_req≈437) kunde aldrig existera nativt.
2. **Kandidatselektionen** behåller lägsta v_req per riktningssektor —
   pit-drops slår plattformsmål; hoppet emitteras ändå inte nativt (öppet,
   kräver dz-klassdiversitet i solvern).
3. **Kantremsor saknar celler** (ståbarhetsmarginalen) — människan bygger
   sista farten där. Verktyg byggt: `plancell`-verbet (rex `04437e7`) +
   Cell-kind i patch_apply (fasttrack/core.py).
   Lösning här: länken planterades via `planlink` med exakta demovärden:
   `from [123,610,56] takeoff [-137,739,120] to [-302,535,120] v_req 440` +
   **curl-cvars MÅSTE sättas** (annars styr default-gain-12-korrigeringen
   flygbågen mot osatta mål): gain 12, entry (−220,637), switch 160,
   landing (−302,535).
   *(NOT 2026-07-23: historisk text — gällde en tidig focus-iteration.
   Slutbuilden 04437e7 har inga aim-fält alls; gain-12-default +
   luftsikte mot landningen räcker, se runbooken steg 5 och
   findings-log § curl-diskrepans.)*

### Lager 2 — exekutorn (rex branch `focus-controller`, pushad till `Xerialen/rtx` 2026-07-22)
4. **sj_approach** (`205b9de`): Walk/Step-legs inom 16 legs före en
   SpeedJump får committed bhop, fartgrindad ≥RUN_UP_SPEED 280 (`90aef52`).
   16 är optimum — 24 kilar i trappsvängar (`625d4ba`).
5. **Leap-band** (`bf39fd5`): hoppa endast vid ≥0,98·v_req (hopp i
   0,90–0,98-bandet föll i gropen); abort-oraklet (plan-mark-modell,
   felpredikterar trappor) degraderat till nödbroms 0,6.
6. **Kurvad runway** (`05216ea` + `ff3da73`): A*-cellväg till takeoff-cellen
   följs med korridor-lookahead (projektionscursor — exakt cellmatch fryser
   vid raddrift); beeline-sikte först ≤96u/fri sikt.
7. **Lip-hold-fel** (`e610954`): (a) hold-vid-kant seglade av klippan i
   400+ ups (DETTA var "gropfallen", inte korta hopp); dot-testet
   (to_edge·v<0) bundet ≤160u från lip (triggade annars mitt på runwayn
   under uppstartssväng).
8. **Stegkant-defer + aktiv fasplanering** (`766d515` + `99081ce`):
   luftburna hopp mot stegframsidor väggklipper farten; defer skjuter
   re-jump 1–8 frames så kontakter hamnar på stegtoppar; fasplaneringen
   simulerar 2–3 kontakter framåt (tvåkontaktsgeometri: 64u stigning >
   45,6u apex ⇒ exakt två kontakter i trappserien). Lyfte trappfart från
   kollaps 81–199 till 392–455.

### Lager 3 — tillståndsläckor mellan försök
9. **Straff (failed_links) och watchdog-progress-baseline överlevde
   teleport** när route_frozen (mid-traversal/airborne) — nästa försök
   PLANERADE omvägen (total korrelation straff↔42-legs-plan, mätt).
   Fix `bb6bba1`+`07f6541`+`25aa0ba`: displacement >200u/frame (=15 000
   ups, ingen legitim rörelse) invaliderar OVILLKORLIGT: rutt, sj-latch,
   failed_links, watchdog-baslinjer.

### Lager 4 — verktygskedjans egna buggar
10. **Soft-unlink** routades ändå; länk-id instabila — tombstone-unlink i
    alla routrar (`205b9de`).
11. **Coverage-matcharen** jämförde demo-avstamp mot länkens KÄLLCELL
    (runwaystart) — planterade länkar omflaggades som saknade; fixad med
    segmentmatchning (`seg_near` i fasttrack/demo_mesh.py).

### Lager 5 — världen
12. **HISSARNA.** Startpunkten ligger under dm3:s lifts; föregående försöks
    passage triggar plattformcykeln; nästa försöks bhop möter sänkt tak.
    Gav period-2-mönstret (varannan-pass) som överlevde alla rensningar.
    Åtgärd: `settle_s=6.0` mellan försök (världen vilar; MÄTTIDEN goto→box
    opåverkad — öppet redovisat val).

## Instrumenten som hittade allt (utan dem: omöjligt)

- `trial` v2: 15 Hz-mätning, arrive_box, streak, fail-closed proveniens.
- `sjtrace <bot>`: per-frame-ringbuffer under speedjump (t,pos,fart,fas,
  ground,clear,cursor,hold) — hittade lager 3+7.
- `penalties <bot>`: aktiva länkstraff — bevisade läckan.
- `plancell x y z` / `planlink ...`: cell-/länkplantering live.
- `demo_ingest`/`missing_spec`: demo → gap-lista → färdig patch.
- Viewern: rött = element människan använder som meshen saknar.

## Öppet / nästa beslut (ägarens)

- Rex `focus-controller` (~21 commits, 216 tester gröna) + `bsp-probe`
  PUSHADE till fork `Xerialen/rtx` 2026-07-22 (ägar-OK; ingen PR skapad).
  Kvarvarande beslut: uppströmskandidater till nano: 43a471c, tombstone-unlink,
  bb6bba1+07f6541, e610954, 05216ea, 766d515+99081ce.
- Gap-stängning HELA demot: celler 4→0 ✅; hopp 27→5 kvar (3 = trolig ny
  kantremsa vid RA-hyllan, 2 = plantering snappade >80u fel). VARNING:
  bulk-plantering av 27 länkar FÖRORENADE fokusruttens routing (0/15) —
  closure-patchar måste kurateras per länk. Merged patch:
  `~/.local/share/qw-fasttrack/patches/xersng-close.json`.
- Viewer-UX: docs/tickets/2026-07-22-viewer-source-selector.md.

## RA-tunnel → RA-topp (systerlösningen, annat repo)

Löst i **route-lab** (paraplyrepot, `Xerialen/route-lab`) som dess spår 1 —
läs `route-lab/docs/plans/STATE.md` (kanoniskt läge) + `route-lab/AGENTS.md`.
Kort: acceptansrutten är exakt RA-tunnelns deathmatch-spawn → RA-toppen;
gate **40/40 GRÖN**, harness-split `68cdcd7`, dbg-städ `636df9e`, H1–H3
åtgärdade `3222689`. Ligger som **draft-PR https://github.com/qw-ctf/rtx/pull/6**
(head `Xerialen/rtx:ra-tunnel-on-main`), blockerad ENBART av två ägarbeslut
(PR-scope expandera/splitta + H4 labbmaskineri — rekommendation SPLIT på
båda). Drill-evidens: `route-lab/artifacts/rtx-watch/drills-27956-ra-tunnel-on-main+cd86021.jsonl`.

## Full historik

Hela resan (30 iterationer, fem måldoms-sektioner med rådata) ligger i
`docs/plans/2026-07-22-toolbox-v2.md`. Sessionens iterationslogg med
frame-traces: scratchpad-filen refererad där.
