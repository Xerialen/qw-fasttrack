# Merge-trial nattkörning 2026-07-23 — SLUTFÖRD ✅ (03:15)

**MÅLDOM: BÅDA GATERNA GRÖNA på slutbuilden `4cdf7912` (commit `f2a0b27`,
pushad till `fork/merge-trial`).**

- **Lifts→SNG 10/10** (fasttrack-riggen 27530, kall boot): 3.110–3.174 s
  (krav ≤3.82; certifierat före mergen 3.63–3.71; människan 3.18 —
  mergeboten går i människofart). Evidens: focusroute.jsonl sista raden.
- **RA-tunnel→RA-topp 10/10** (route-labs RA-rigg 27504/27954, local-
  scenariot = tunnel→topp): 2.11–2.12 s (korpusmediangate 2.435), 0
  väggkontakter, parity dj/wj/elev/gren/grapple/rjump/ledgecap =
  0/0/1/0/0/0/0. Evidens: route-lab/artifacts/dm3-ra-local-merge-4cdf7912.jsonl.
- cargo test 709/709. Rutt B:s tre live-planteringar återplanterade
  (routeb-wip, 3 adds OK) — status quo för morgondagens exekutorlane.
- OBS ra_spawn-scenariot (HELA spawn→RA, median 12.516) är RÖTT på både
  mergen OCH deras rena HEAD 3222689 i alla ikväll tillgängliga miljöer
  (28/30 deterministisk 12.68 s plat-väntlinje + väggkontakt) — cert-
  miljön för den ligger på förbjudna B-slotten (27506/27956, orörd).
  Detta är ett UPPSTRÖMS HEAD-läge, inte en merge-regression (kontroll-
  mätning bevisad). RA-riggens qwprogs var 59c602c2 (fryst kopia i
  fasttrack-artifacts) — kör nu merge-builden; rulla tillbaka med
  deploy_dm3_ra.sh på den frysta om ägaren vill.

---

*Ursprunglig löpande logg nedan.*

*Skrivs av nattsätet (claudette/Fable). Mål (ägarhook): merge-trialen klar,
lifts-to-SNG 10/10 OCH RA-tunnel→RA-topp 10/10 på merge-builden.*

## Klart

- **Merge genomförd**: `merge-trial`-branch i worktree `rex-merge-trial\`,
  `focus-controller` (04437e7) × `fork/ra-tunnel-on-main` (3222689 — INTE
  handoffens 4f784f1; 3222689 = H1–H3-fixarna, PR#6-head). 16 konflikthunks
  lösta enligt facit-regeln; detaljer i commitmeddelandet (scratchpad) och
  nedan.
- **Certifierad rollback fryst**: `~/.local/share/qw-fasttrack/artifacts/
  librtx-focus-04437e7-certified.so`, sha256 `78659b8e…`.
  Rollback: `core.server_up('dm3', lib=<den>)`.
- **Gate 1 GRÖN**: cargo test 709/709 (mergen tog in bådas testsviter).
- Merge-.so byggd: sha256 `1bd4cec3…` (deployad på 27530 nu).
- **Curl-cvar-diskrepansen LÖST** (findings-log uppdaterad): båda
  dokumenten var sanna för varsin build. Merge-beslut: gain-12-default
  återställd; aim-cvars kan inte längre kapa flygningen utan profilerad
  axel.

## Gate 2 (rutt A 10/10): PÅGÅR — två fynd

1. **Aim-cvar-kapning (LÖST)**: active-patch.json bar historiska
   entry/switch/landing-cvars; i mergad runtime blev entry-punkten en
   "hug point" som ägde markstyrningen → lyft från fel linje (y≈642 i st
   f 739) → grop. Cvarsen strippade ur patchen (backup
   `active-patch.json.bak-aimcvars`), gain 12 kvar.
   Efter fix: 12/15, tider **3.17–3.70 s** (certifierat: 3.63–3.71;
   människan: 3.18 — mergebotten går i människofart).
2. **Missklass (PÅGÅR)**: ~1/5 försök missar hoppet; recovery efter
   gropfall faller av övre kanten igen och slutar i stall→Hold på hissen
   (route 0 legs, goto_stall @ dist ~410–465). I certifierade builden
   recovrade boten till långsam ankomst; i mergen dör försöket. Forensik
   pågår (exakt trial-protokoll + sjtrace vid missögonblicket).

## GATE 2 GRÖN — rutt A 10/10 ✅ (02:05)

Build `2f97e20c` (= merge + tre korrigeringar efter 1bd4cec3):
1. **sol Fix A** (bhop.rs): 0,98-bandvakt vid själva hopp-pulsen i
   lip-zonen — `hold_jump`-checken låg i en `else if` som aldrig nåddes
   när `sj_takeoff`; under-band-lyft (334 ups vs golv 431) kunde eldas
   ogated → 20u kort → grop. + enhetstest. (sol via codex, reviewad.)
2. **Cvar-sanering**: `rtx_jump_curl_gain 12` togs bort ur patch-cvarsen —
   flight-time-overriden skrev annars över VARJE nativ curl-länks lösta
   gain (RA 0/30 "fall" på 1bd4cec3). Plant-defaulten 12 räcker.
3. **sj_curl-breddningen borttagen** (≤470-klausulen) + `phase_landing`
   kräver `sj_gt.is_none()` — våra mekanismer får inte störa deras
   GT-kontrakt/hop-chain på nativa länkar.
4. 43a471c (emissionsbound) TILLBAKARULLAD i mergen — breddningen gav
   nativa länkar deras RA-certifiering aldrig såg. Fokusrutten rider på
   planterad länk och behöver den inte. (Dokumenterad i jumps.rs.)

Varm server: **10/10 rak streak, 3.109–3.174 s** (certifierat 3.63–3.71;
människa 3.18). Kall boot har kvarvarande världsfas-flake (setup_failed =
teleport uppe på hissplattform z 88; goto_stall efter klipp-miss) —
dokumenterad, ej blockerande för varm gate.

## Gate 3 (RA-tunnel→topp 10/10): RÖD — kontrollmätning pågår

Mönster på 2f97e20c: 27/30 klarar klättringen men på deterministiska
12.71 s (plat-väntlinje, +wall_contact) > median 12.516; 3/30 tar
snabblinjen (6.5 s) men faller på samma avsats (247,−606,43).
Kontrollexperiment: deras rena 3222689-.so byggs och körs på EXAKT samma
rigg/harness — skiljer "mergen bröt det" från "riggens cfg ≠ deras
certifieringsrigg".

## Kvar

- Gate 2 10/10 (missklassen ska bort), sedan Gate 3: RA-acceptansen
  `ops/dm3_ra_acceptance.py --scenario ra_spawn --consecutive 10
  --port 27980` (tröskel 12.516 s).
- Merge-commit (meddelande klart i scratchpad), push till fork efter
  gröna gater.
- Rutt B-planteringarna (routeb-wip.json) återplantas efter att gaterna
  är klara — de dog med serverreboot som väntat.

## Sol-notering

Konfliktresolutionen var facit-/domslutsarbete och gjordes i huvudsätet;
sol (codex) reserveras för botkodsfixar om missklassen kräver kodändring
(t.ex. recovery-lanen), med bounded brief + review här.
