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
5. Botkodsändringar: rex branch `focus-controller` (~21 commits, 216 tester;
   pushad till fork `Xerialen/rtx` 2026-07-22 tillsammans med basen
   `bsp-probe`). Bygg vidare där; sol via codex för implementationspass
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

## LÄGE 2026-07-22 sen kväll: analys KLAR, mesh STÄNGD, exekutorn kvar

Steg 1–3 i receptet är genomförda (samma session som skrev handoffen):

- **Människoreferens:** rörelsestart +0,922, SNG +5,234, mega +7,909 →
  **hela rutten 6,99 s (gräns 8,39)**, del 1 4,31 s, del 2 2,68 s.
  Fartprofil: 440–491 genom gången/språnget; sänker till ~360 i hörnet.
- **Gap-analys (färsk graf `routeb`):** 0 celler saknas; 4/5 hopp saknades.
  "Hoppet" uppför trappan = bhop över nativa Step-länkar (inget att plantera).
- **Kuraterade planteringar (LIVE + `patches/routeb-wip.json`, EJ i aktiva
  patchen):** brosprånget from(−928,320) takeoff(−911,633) to(−710,845)
  v460 (90° högercurl, människans flygbana); SNG-hoppet from(−525,675)
  takeoff(−522,437) to(−522,251,176) v445 (runway SÖDER om sänkan);
  trench-SJ som fallback (routern föredrar NATIV jump (−576,800)→(−544,672)
  över sänkan y≈688–788/z84 — den nativa räcker).
  **Routerns fullruttsplan är nu människans rutt exakt** (36 legs: Steps →
  brosprång → hörn → nativ sänk-jump → SNG-SJ → avsats → nativ jump → mega).
- **Regressionsvakt:** rutt A-streaken STÅR med allt planterat (5-streak,
  3,63–3,69 s, 2026-07-22 ~23:30). Kuraterat = ingen förorening.
- **KVAR — tre exekutorfel (frame-bevisade, alla botkod/focus-controller):**
  1. **Hoppfas-varians vid brosprånget:** grundad vid linjen ⇒ perfekt lyft
     (454–478); i hopbåge vid linjen ⇒ tidigt lyft från apex → gapfall.
     Samma klass som trappserien — aktiv fasplanering (99081ce) täcker inte
     platt runway före SJ.
  2. **Het hörning efter landning:** 380–480 ups genom走 gånglegs skär
     hörn → av plattformskanten (ledge-brake griper inte). Människan
     saktar till ~360 där.
  3. **Grop-livelock:** efter fall studsar boten mot vägg på stället i
     10+ s utan recovery-repath (varje miss blir timeout i stället för
     långsam återhämtning). Billigaste fixen med störst trial-effekt.
  Fullrutt 0/8 över tre trialkonfigurationer; bästa observerade delsträckor
  i pace med människan (spawn→språnglandning ~4,0 s vs människans 3,9).
  focus-controller saknar dessutom mains drop-cert 408fb52 ("bhop look-ahead
  off a drop") — merge av main är ägarbeslut (uttalat: SENARE, inte nu).

## Öppna ägarbeslut som kan påverka dig

- Rex uppströms: branchen är pushad till forken (2026-07-22); kvar är
  beslutet om de 7 uppströmskandidaterna till nano (PR eller ej).
- Closure-patchens kurering (27 länkar, xersng-close.json).
- PR-scope för RA-tunnel (route-lab spår 1, qw-ctf/rtx#6).
