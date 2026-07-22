# RUNBOOK: Från ägarens QWD till grön rutt (dm3-fasttrack-loopen)

*Skriven 2026-07-22 av sessionen som körde loopen två gånger: rutt A
(under-lifts→SNG, GRÖN 5-streak) och rutt B (SNG-spawn→SNG→mega, mesh
stängd, exekutorfel kvar). Detta är den exakta metoden, i sådan detalj att
vilken LLM som helst kan ta vid utan sessionens kontext. Allt körs mot den
lokala testservern — inget rör deck-portarna eller produktionsservrar.*

---

## 0. Miljö och invarianter (läs innan du kör NÅGONTING)

**Kör alltid Python-verktygen i WSL** (`Ubuntu-24.04`), från qw-fasttrack-
roten, med `nice -19`, och med BÅDA sys.path-raderna (ground_oracle ligger
i paketkatalogen — utan andra raden får du ModuleNotFoundError):

```sh
wsl -d Ubuntu-24.04 -e sh -c "cd /mnt/c/Users/benya/projects/quakeworld/qw-fasttrack && nice -n 19 python3 -c \"
import sys; sys.path.insert(0,'.'); sys.path.insert(0,'fasttrack')
from fasttrack import core, demo_mesh
# ... din kod ...
\""
```

**Portar:** testservern äger spel **27530** / kontroll **27980** / QTV
**29530**. RÖR ALDRIG 8765/8767 (deck), 8088 (kanoniska viewern),
27504/27506/27508/27516/27521 (orkestrering).

**Förbjudna cvars = 0 alltid:** `rtx_bot_ledgecap`, `rtx_walljump`,
`rtx_doublejump`. Trial-ledgern läser tillbaka dem varje försök
(fail-closed proveniens) — men verifiera själv om du bootar om.

**Regel 11.2:** ägardemos ger placering/målvärden (koordinater, v_req,
tider) — ALDRIG trajektorier/usercmds inklistrade i botkod.

**Serverboot** (auto-replantar aktiva patchen från
`~/.local/share/qw-fasttrack/active-patch.json`):

```python
core.server_up('dm3', lib='/mnt/c/Users/benya/projects/quakeworld/rex/target/release/librtx.so')
core.wait_ready()
```

**State-kataloger (WSL):** `~/.local/share/qw-fasttrack/` — `evidence/`
(trial-jsonl), `patches/` (sparade patchar), `active-patch.json` (det som
replantas vid boot), `active-graph.json` (kan vara INAKTUELL — lita aldrig
på den, dumpa färskt, se steg 3).

**Livelänkar att alltid kunna ge ägaren:** movement lab
`http://127.0.0.1:8090/?graph=<namn>&live=8093` (starta med
`core.live_start('dm3','<graf>')`); spelvyn `connect 192.168.86.20:27530`
(ezQuake) eller `qtvplay 192.168.86.20:29530`; browser-MVD efteråt via
LAN-spelaren `http://192.168.86.33:8095/demo-player/?demoUrl=/demos/files/...&map=dm3&from=1`
(fil till servexeri `/mnt/usb-ssd/`, chmod 644). **Nämner du servern i ett
svar ska länken stå med.**

---

## 1. Källdemot

Ägarens demos: `C:\nQuake\qw\matchinfo\demos\` (WSL:
`/mnt/c/nQuake/qw/matchinfo/demos/`). **Endast .qwd** — MVD bär inga
inputs. Verifiera parse och omfång direkt:

```python
samples = demo_mesh.load_samples('/mnt/c/nQuake/.../demot.qwd')
# sample = (t, x, y, z, ...) — indexera flexibelt, fältantalet varierar
t0, t1 = samples[0][0], samples[-1][0]
print(len(samples), t1-t0, samples[0][1:4], samples[-1][1:4])
```

Ett bra ägardemo är inspelat FÖR rutten: en ren instans, start→mål, inga
omtag. Är demot längre: hitta instansen via landmärkes-närmanden (steg 2).

## 2. Människoreferensen (kalibrering FÖRE mekanism — hoppa aldrig över)

Tre tal ska fram: **rörelsestart**, **deltider vid landmärken**, **mål-
touch**. Acceptansen = (mål − rörelsestart) × 1,20.

```python
# rörelsestart: första samplet med XY-fart > 50 ups
# landmärkes-touch: min över samples av hypot(dx,dy)+|dz|*0.5
# mål-touch: första samplet inom 40u XY och 24u z från målet
```

Sedan **fartprofil** var 0,5 s (pos + XY-fart) — den talar om var människan
är het (440–490), var hen bromsar (hörn ~360), och var flygfaserna ligger.

**Flygsegment i detalj** (för hoppgeometri): dumpa varje sample i
tidsfönstret runt ett hopp med `demo_mesh.grounded_mask(samples)`.
**VARNING — läsfälla:** z-värden 120+~45 under "luft" är HOPPBÅGARS APEX,
inte geometri. Tro aldrig att det finns en högre plattform bara för att
människan är på z 165 mitt i en bhop-serie. Avstampet = sista låga
markkontakten före stigningen; landningen = första MARK-samplet efteråt.

## 3. Gap-analys mot LIVE-grafen

**Dumpa alltid färskt** — grafen på disk kan vara från ett annat serverläge:

```python
core.graph_dump('dm3', [x,y,z], out_name='<ruttnamn>')   # seed = ruttstart
graph = json.load(open('/mnt/c/.../route-lab/qw-nav-viewer/overlays/<ruttnamn>-graph.json'))
ex = demo_mesh.extract(samples)
d = demo_mesh.diff_vs_graph(ex, graph)
# d['cells_missing'] är ett ANTAL; punkterna i d['cells_missing_points']
# per-hopp: ex['jumps'][i]['covered'] efter diff-anropet
```

**Tolka diffen — tre klasser av "saknade hopp":**
1. **Äkta saknad länk** (flygfas över gap/upp på plattform) → plantera.
2. **Sammansmält bhop-serie** (`air_s` > ~0,8 s eller stor z-stigning över
   trappor) → INTE en länk; människan bhoppar över nativa Walk/Step-celler.
   Exekutorn (sj_approach/fasplanering) äger detta, inte meshen.
3. **Redan-planterat som omflaggas** → coverage-matcharen är segmentmedveten
   (`seg_near`) sedan 333e820; ser du omflaggning ändå är snappningen >80u.

## 4. Ruttforensik (vad planerar routern IDAG?)

```python
core.ctl('teleport 1 <startx> <starty> <startz>'); time.sleep(0.3)
core.ctl('goto 1 <målx> <måly> <målz>'); time.sleep(1.0)
legs = (core.ctl('route 1').get('data') or {}).get('legs')
# skriv ut alla legs med kind != 'walk' — det är hoppen/stegen som räknas
```

Gör detta FÖRE plantering (baseline-plan), EFTER varje plantering
(föroreningskontroll), och när trial-beteendet inte matchar förväntan.
Målet: planen ska vara **människans rutt** — jämför mot fartprofilen.

## 5. Kuraterad plantering — EN länk i taget

**Kontrollverben** (via `core.ctl`):

| Verb | Syntax | Noter |
|---|---|---|
| `planlink` | `planlink fx fy fz ox oy oz tx ty tz v_req` | from=RUNWAYSTART, o=avstamp, t=landning |
| `plancell` | `plancell x y z` | ståbar kantcell; kopplar Walk/Step åt båda håll |
| `unlink` | `unlink <länk-id>` | tombstone — enda säkra borttagningen ("remove" timeoutar) |
| `route` | `route <bot>` | aktuell plan |
| `sjtrace` | `sjtrace <bot>` | per-frame-ringbuffer under speedjump — dumpa DIREKT efter händelsen |
| `penalties` | `penalties <bot>` | aktiva länkstraff |
| `curl` | `curl sx sy sz tx ty tz` | M2-solvern: bästa (v0, heading, gain) för ett hopp |

**Planteringsregler (alla köpta med blod):**
- **`from` är runwaystarten, inte en punkt nära avstampet.** Boten bygger
  fart längs from→takeoff. Från STILLASTÅENDE krävs ~300u+ runway för
  440-klass; med buren fart (ruttkedja) räcker kortare. Lägg `from` PÅ
  människans anflygningslinje (läs fartprofilen).
- **Kolla snappningen i svaret**: `from_cell`/`tgt` ska ligga ≤~15u från
  demovärdena. Snappar det >80u fel — flytta koordinaterna, planterar om.
- **v_req = människans medianfart vid avstampet**, avrundat uppåt lite.
  Leap-grinden är 0,98·v_req; för högt = abort, för lågt = gropfall.
- **Curl-mål-cvars behövs INTE** i denna build (entry/switch/landing-cvars
  är döda; endast `rtx_jump_curl_gain` global gain finns — planterade
  länkar får gain 12 by default och luftsikte mot länkens landning).
- **Routern kan rata din länk** (kostnad): flytta `from` längre bak så
  länken ersätter fler gå-legs, eller acceptera nativ länk om planen redan
  är människoformad. Verifiera empiriskt med `route`, gissa inte kostnader.
- **ALDRIG bulkplantering.** 27 länkar på en gång förstörde rutt A-routingen
  (0/15). En länk → ruttforensik → nästa.
- Planteringar är **LIVE-only** — de dör med servern. Spara varje kuraterat
  set som `~/.local/share/qw-fasttrack/patches/<namn>.json`
  (qw-nav-patch/1) så `core.patch_apply(json.load(...))` kan återställa.

**Geometri-sondering** när BSP:n är okänd (sänkor, kanter, plattformsmått):
teleportera boten och läs var den landar — `z` efter 0,4 s är golvet:

```python
core.ctl('teleport 1 <x> <y> 140'); time.sleep(0.4)
print(core.ctl('status')['data']['bots'][0]['origin'])   # z<100 ⇒ hål/sänka
```

## 6. Trial-loopen (acceptansmallen)

```python
r = core.trial([startx,starty,startz], [målx,måly,målz],
               settle_s=6.0,                      # världsvila — hissar/platar cyklar
               arrive_box=[x0,y0,z0,x1,y1,z1],    # ±~100u runt målet
               pass_time_s=<människotid*1.2>,
               streak_target=5, max_time_s=<~2x gräns>, attempts_cap=8)
# r['rows']: outcome/elapsed/terminal_events per försök; evidens auto-skrivs
```

`settle_s=6.0` är obligatoriskt på dm3 (hisscykler från föregående försök
möter nästa försöks bhop — period-2-mönstret). Mättiden goto→box påverkas
inte; redovisa valet öppet.

## 7. Telemetri FÖRE tuning (när trials är röda)

Ordningen är helig: **titta → förstå → ändra**, aldrig tvärtom.

1. **Live-följning** (var bryter det?):
   ```python
   core.ctl('teleport 1 ...'); time.sleep(6); core.ctl('goto 1 ...')
   # polla status var 0,4 s: origin, speed, bhop-läge — skriv ut ändringar
   ```
2. **sjtrace** direkt efter en speedjump-händelse (ringbuffer, ~185 frames):
   fälten är [t, x, y, z, fart, fas, ground, clear, cursor, hold, _].
   Grundad vid avstampslinjen + fart ≥0,98·v_req = korrekt lyft.
3. **penalties** när routern planerar omvägar utan synbar orsak
   (straffläckor korrelerar totalt med omvägsplaner — rutt A lager 3).
4. **Felklasstaxonomin** (matcha innan du uppfinner nya):
   - fart < 0,98·v_req vid lip → runway/approach-problem (steg 5)
   - lyft från hopbågens apex i stället för linjen → hoppfas-varians (botkod)
   - het hörning av kant efter landning → ledge-brake/drop-cert (botkod)
   - studs-på-stället efter fall (10+ s) → recovery-livelock (botkod)
   - varannan-mönster / oförklarlig periodicitet → VÄRLDEN (hissar, platar)
     — kolla entiteter innan du rör controllern
5. **Världen före controllern. Alltid.**

## 8. Regressionsvakten (obligatorisk efter VARJE graf/kodändring)

Rutt A-acceptansen är det stående facit:

```python
core.trial([551,604,56], [-512,448,96], settle_s=6.0,
           arrive_box=[-632,328,16,-392,568,176],
           pass_time_s=3.82, streak_target=5, max_time_s=8.0, attempts_cap=15)
```

Streak 5 ska stå. Gör den inte det har din ändring förorenat något —
backa (unlink/patch_clear+replant) innan du fortsätter.

## 9. Botkodslanen (när meshen är klar men exekutorn fäller)

- Repo `C:\Users\benya\projects\quakeworld\rex`, branch `focus-controller`
  (pushad till fork `Xerialen/rtx`). Bygg i WSL:
  `cargo build --release` → `target/release/librtx.so`; deploja med
  `server_up(lib=...)`. Testsviten: `cargo test` (216 gröna är baseline).
- Nyckelmekanismerna och deras commits: se
  `docs/solutions/2026-07-22-dm3-under-lifts-to-sng.md` (tolv rotorsaker).
  Läs den INNAN du rör steer.rs/bhop.rs — de flesta "nya" fel är kända
  klasser.
- Implementationspass: sol via codex (claudex-flödet, exakt binär
  `C:\Users\benya\AppData\Roaming\npm\codex`); sol skriver ibland utanför
  scope — säg uttryckligen nej till vault-skrivningar och kontrollera ändå.
- Rex-branchar pushas till forken; PR mot uppström kräver ägar-OK.

## 10. Bevis och avslut

1. Grön streak → spela in MVD på servern, kopiera till servexeri
   `/mnt/usb-ssd/non-games/xerbot/`, chmod 644, ge LAN-spelarlänken.
2. Uppdatera måldomen i aktuell plan-/lösningsfil med rådata + commits.
3. Spara patchen (`patches/`), promota via `core.promote(...)` om rutten
   ska till route-lab.
4. Committa + pusha qw-fasttrack. Lösningsdokument läggs på
   re-entry-vägen: `AGENTS.md` → `docs/current-stage.md` → ⭐-blocket.

---

## Bilaga: rutt B-exemplet i miniatyr (2026-07-22)

Metoden ovan, tillämpad: `xersngtomega1.qwd` → referens 6,99 s (gräns
8,39) → diff: 0 celler, 4/5 hopp saknades → 1 var trappserie (klass 2),
3 planterades kuraterat (brosprånget −928,320→−911,633→−710,845 v460;
SNG-hoppet −525,675→−522,437→−522,251,176 v445; trench-fallback) → routern
fann dessutom nativ sänk-jump själv → plan = människans rutt exakt →
regressionsvakt GRÖN → trials 0/8 med tre frame-bevisade exekutorfel
(hoppfas-varians, het hörning, livelock) → botkodslanen. Detaljer:
`docs/plans/2026-07-23-route-b-sng-spawn-to-mega-handoff.md` § LÄGE.
