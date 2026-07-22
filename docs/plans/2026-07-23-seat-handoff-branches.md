# SÄTES-HANDOFF: procedur + exakt branchläge (dm3-operatören tar över)

*Skriven 2026-07-22 sen kväll av sessionen som körde rutt A till GRÖN och
rutt B till mesh-stängd. Profil-agnostisk: vilket säte som helst (annan
Claude-profil, annan LLM) ska kunna ta över härifrån utan sessionens
kontext. Ägaren = Xerial.*

## Läs i denna ordning

1. **`docs/runbooks/qwd-till-gron-rutt.md`** — HELA metoden (qwd →
   referens → gap → plantering → trial → telemetri → regression → botkod).
   Din arbetsloop står där; denna fil är bara läge + gränser.
2. `docs/solutions/2026-07-22-dm3-under-lifts-to-sng.md` — rutt A:s tolv
   rotorsaker + instrumenten. Felklasserna du kommer möta är oftast dessa.
3. `docs/plans/2026-07-23-route-b-sng-spawn-to-mega-handoff.md` — rutt B:
   uppdraget, källdemot, § LÄGE (analys klar, mesh stängd, tre exekutorfel).

## Exakt branchläge (alla verifierade pushade 2026-07-22)

### rex — `C:\Users\benya\projects\quakeworld\rex`
Remotes: `origin`=Xerialen/4on4, **`fork`=Xerialen/rtx** (vårt),
`upstream`=qw-ctf/rtx.

| Branch | HEAD | Pushad till | Innehåll |
|---|---|---|---|
| `focus-controller` | `04437e7` | `fork` ✅ | **Rutt A/B-exekutorn.** 32 commits ovanpå merge-basen `85626e0` med main. Kedjan i ordning: 205b9de sj_approach-bhop → 90aef52 fartgrind → 43a471c emissionsbound-fix → bf39fd5 leap 0,98+abort 0,6 → 05216ea+ff3da73 kurvad runway+cursor → 004f9a1 sjtrace/penalties-verb → 766d515+99081ce stegkant-defer+fasplanering → 25aa0ba+bb6bba1+07f6541 ovillkorlig displacement-invalidering → e610954 lip-hold ≤160u → 04437e7 plancell-verb. 216 tester gröna. Aktuella `librtx.so` på testservern är byggd härifrån. |
| `bsp-probe` | `0e94183` | `fork` ✅ | Basen: hull-1-probe-oraklet + secret-door-fixar. focus-controller står på denna. |
| `ra-tunnel-on-main` | `4f784f1` | `fork` ✅ (= lokala `codex/ra-tunnel-to-ra-main`) | **Fungerande RA-tunnel→RA-topp**, byggd på NUVARANDE main (drop-certen 408fb52 INGÅR). Draft-PR qw-ctf/rtx#6. Gate 40/40 (route-lab spår 1). |
| `main` | `408fb52` | — (spegel) | Uppström +59 commits före focus-basen, inkl. **408fb52 drop-certen** ("bhop look-ahead can't steer off a drop") som troligen löser rutt B-exekutorfel 2. OBS: behind upstream/main 17 — hämta innan merge. |
| övriga (`DM3`, `curl-c-fix`, `lifts-to-sng-mega`, `grid-bracket-*`, `codex/dm3-ra-oneshot`, `fix/netclient-combat`) | | | Andra spår/worktrees — **RÖR EJ.** |

### qw-fasttrack — `C:\Users\benya\projects\quakeworld\qw-fasttrack` (Xerialen/qw-fasttrack)
`main` @ `8fef923`, allt pushat. Ägarens experimentyta — säten arbetar HÄR
på ägarens order (route-lab STATE.md:s "RÖRS EJ"-regel gäller
självsvåldigt arbete, inte beställt).

### route-lab — viewer-branchen
`viewer-live-fasttrack` pushad till Xerialen/route-lab ✅ (playback-UI +
röda missing-lagret). Worktree: `route-lab-viewer-live\` (WSL-skapad —
git-kommandon mot den körs INIFRÅN WSL).

## Live-läget just nu (försvinner vid reboot — läs noga)

- Testservern KÖR på 27530 (WSL systemd-unit) med rutt A:s certifierade
  fokuspatch (auto-replantas från `active-patch.json`) **plus rutt B:s tre
  LIVE-planteringar som INTE auto-replantas**: brosprånget (länk 35690),
  trench-fallback (35688), SNG-hoppet (35689). Efter serverreboot:
  `core.patch_apply(json.load(open('.../patches/routeb-wip.json')))`
  (WSL: `~/.local/share/qw-fasttrack/patches/routeb-wip.json`).
- Livebryggan för movement lab är startad:
  `http://127.0.0.1:8090/?graph=routeb&live=8093`.
- Evidens: `~/.local/share/qw-fasttrack/evidence/` (rutt A `focusroute.jsonl`
  + baseline `nopatch.jsonl`; rutt B-trialerna ligger i samma ledger).

## Vad som är GJORT vs KVAR

**GJORT:** rutt A grön (5-streak 3,63–3,71, reproducerad ×4, MVD-bevis);
rutt B människoreferens (6,99 s, gräns 8,39), gap-diff (0 celler, hopp
stängda), routerns plan = människans rutt, regressionsvakt GRÖN.

**KVAR (i prioritetsordning):**
1. **Merge-trial** (ägaren har beställt proceduren, EJ startat): ny branch
   `merge-trial` från `focus-controller` i eget worktree, merga
   `fork/ra-tunnel-on-main`. Konflikter väntas i steer.rs/bhop.rs (32 vs 59
   commits, båda rör botrörelse) — focus-mekanismerna är facit vid tvekan.
   FÖRE bygget: frys nuvarande certifierade `librtx.so` med sha256 till en
   artefaktkatalog. Gates i ordning: cargo test → rutt A-acceptansen med
   merge-.so → RA-gaten 40/40 (route-lab drill-harness) → rutt B-trial.
   Rollback = `server_up(lib=<frysta .so>)`.
2. **Rutt B exekutorfel** (frame-bevisade, se § LÄGE i rutt B-handoffen):
   hoppfas-varians vid brosprånget; het hörning (drop-certen bör hjälpa —
   därav merge först); grop-livelock (billigast, störst trial-effekt).
3. Rutt B grön → MVD-bevis → browserlänk → måldom + promote.

## Hårda regler för sätet (ärvda, ej förhandlingsbara)

- Förbjudna cvars = 0; portlistan i runbooken; `nice -19`; regel 11.2.
- EN länk i taget + ruttforensik; regressionsvakt efter varje ändring.
- Rex-pushar till fork OK (stående ägar-OK 2026-07-22 "pusha våra
  framgångar"); PR mot uppström/nano = ägarbeslut.
- Klarspråk: röda trials är misslyckanden. Inga "genombrott" utan flyttat
  ägarmål.
- Nämns servern → ge länken (movement lab / connect / QTV / MVD-spelare).
- Telemetri före tuning; världen före controllern.
- sol via codex (exakt binär `C:\Users\benya\AppData\Roaming\npm\codex`):
  förbjud vault-skrivningar explicit och verifiera efteråt.

## Öppna ägarbeslut (blockerar respektive spår, fråga — gissa inte)

- Merge-trial-start (proceduren godkänd i samtal, avvakta "go").
- Rex uppströms: 7 kandidater till nano (listade i solutions-dokumentet).
- Closure-patchen rutt A (27 länkar, `xersng-close.json`) — kurering.
- RA-tunnel PR#6 scope (split rekommenderad).
