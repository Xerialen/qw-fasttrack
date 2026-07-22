# HANDOFF TILL NÄSTA SESSION: Rutt B — SNG-spawn → SNG → MEGA

*Skriven 2026-07-22 ~23:00 av sessionen som löste rutt A. Ägarorder: "innan
vi är helt klara med hoppet behöver vi nästa del i vägen till mega. Den
andra vägen till SNG (och sen mega) som är snabbast när man kommer från SNG
spawns, och sen därifrån till megan (den sista delen är samma för denna
rutt och rutten vi just löste)."*

## Läs FÖRST

1. `docs/solutions/2026-07-22-dm3-under-lifts-to-sng.md` — hela lösnings-
   arsenalen för rutt A: slutekvationen, de tolv rotorsakerna, instrumenten,
   alla konstanter. ALLT där är återanvändbart; mekanismerna är generiska.
2. Denna fil.
3. `route-lab/docs/plans/STATE.md` § MEGA-MÅLET (10,0 s INKL hål-droppen;
   helfönsterdefinition `route-lab/docs/mega-window.md`; Milton 6,43 s =
   referens; gamla bottal 8,757 = delmätningar — CITERA ALDRIG).

## Uppdraget

- **Rutt B del 1:** SNG-spawns → SNG-vapnet, den SNABBASTE varianten när
  man kommer från SNG-spawnhållet (INTE under-lifts-vägen — det är rutt A).
- **Rutt B del 2:** SNG → megan. **Denna del är GEMENSAM med rutt A:s
  fortsättning** — löses den en gång gäller den båda rutterna. Sannolikt
  inblandad: hål-droppen (se mega-window-definitionen).
- Acceptansmodellen från rutt A återanvänds: människans tid ur källdemot
  +20 %, 5 raka, trial v2 med full proveniens, settle 6 s (världsvila —
  redovisas öppet; kolla särskilt vilka entiteter som cyklar längs rutt B).

## Källdemon

- **PRIMÄR: `C:\nQuake\qw\matchinfo\demos\xersngtomega1.qwd`** — inspelad
  av ägaren 2026-07-22 22:47 SPECIFIKT för rutt B. Verifierad parse:
  741 samples, EN ren instans på **9,6 s**, start (−880,−237,−16)
  [SNG-spawnområdet] → slut (−688,85,184) [uppe vid megan]. Notera:
  9,6 s < mega-målets 10,0-fönster. Ingen instansletning behövs — hela
  demot ÄR instansen.
- Referens i samma katalog: `milton_dm3_lift_to_sng_mega.qwd` (Miltons
  körning) — jämförelsematerial, INTE kalibreringskälla för acceptansen
  (ägarens tid styr).
- Sekundär: `data\owner-demos\xersngmega-20260720.qwd` samt
  `xersng.qwd` (rutt A-demot, kan innehålla B-varianter).
- dm3-spawnpunkter: se auto-memory `dm3-spawns-and-flowchart` (6 spawns med
  koordinater; ren karta = dm3spawns.png). Identifiera vilka spawns som är
  "SNG-spawns" ur den + demot.

## Arbetsrecept (beprövat i rutt A — följ det, hoppa inte steg)

1. **Människoreferens först** (kalibrering före mekanism!): extrahera
   instansens tid + fartprofil ur demot (qwd_dump-vägen; MVD saknar inputs).
   Median + snabbaste om flera instanser.
2. **Gap-analys:** `graph_dump` av serverns graf → `demo_ingest` på
   instans-segmentet → saknade celler/hopp. Coverage-matcharen är
   segmentmedveten sedan rutt A (demo_mesh.py seg_near).
3. **Patcha KURATERAT:** en länk/cell i taget med ruttforensik efter varje
   (route-verbet) — bulk-plantering av 27 länkar förorenade rutt A:s
   routing till 0/15. `plancell` finns för kantremsor (rex 04437e7).
4. **Trial-loop:** acceptanskommandot per rutt A-mall; vid varians —
   telemetri FÖRE tuning (`sjtrace`/`penalties`), och kolla VÄRLDEN
   (hissar/platar/dörrar längs rutten) före controllern.
5. Botkodsändringar: rex branch `focus-controller` (EJ pushad, ~21 commits,
   216 tester). Bygg vidare där; sol via codex för implementationspass
   (exakt binär: C:\Users\benya\AppData\Roaming\npm\codex; sol skriver
   ibland till vault utanför scope — säg uttryckligen nej och kolla ändå).

## Servern & miljön (oförändrat från rutt A)

- Boot: `core.server_up('dm3', lib='/mnt/c/Users/benya/projects/quakeworld/rex/target/release/librtx.so')`
  — ACTIVE_PATCH auto-replantas; just nu ligger rutt A:s certifierade
  fokuspatch där (jätteben v440 + curl-mål). Rutt B:s patch ska ADDERAS
  kurerat, inte ersätta — och testa att rutt A:s streak STÅR efter varje
  tillägg (regressionsvakt!).
- Portar (spel 27530/kontroll 27980/QTV 29530); rör aldrig 8765/8767/8088/
  27504/06/08/16/21; förbjudna cvars = 0 (ledgern verifierar).
- Viewer: 8090; demo-replay 8096; livebrygga live_start → 8093.
  Hubb-demospelare på LAN: http://192.168.86.33:8095/demo-player/?demoUrl=...
  (servera filer via servexeri /mnt/usb-ssd/, chmod 644).

## Kända fällor längs just denna väg

- **Hål-droppen** (del 2): fall = Drop-länkar; hård fallhöjd nollställer
  fartband (SAFE_FALL i banded_step) — människans drop-teknik kan behöva
  samma slags analys som trappserien fick i rutt A.
- **SNG-plattformens kantremsa**: rutt A slutade där; rutt B:s del 2 utgår
  därifrån — kantcellerna är fortfarande inte planterade (plancell finns
  men closure är okurerad). 3 av rutt A:s 5 residualhopp pekar dessutom på
  ännu en kantremsa vid RA-hyllan (landningar z=145,5).
- Lifts-lärdomen: om periodisk varians uppstår — världen först.

## Öppna ägarbeslut som kan påverka dig

- Rex-pushen (branch + 7 uppströmskandidater till nano).
- Closure-patchens kurering (27 länkar, xersng-close.json).
- PR-scope för RA-tunnel (route-lab spår 1, qw-ctf/rtx#6).
