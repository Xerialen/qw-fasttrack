# TOOLBOX.md — verktygslådan (fork, inte main)

Inventering enligt planen §7 (rannsakan-läxan: det som inte indexeras
försvinner). Integrationslinjen är `toolbox/slice-merged` i
`Xerialen/qw-fasttrack`. Syskonverktyg som ännu inte är inmärgade
pekar ut sin egen branch + commit.

Paritet = kanonikaliserad JSON (CLI ↔ MCP när MCP finns). Webben är
klient, inte paritetspart. Tid, absoluta sökvägar, hostname och
request-id får inte ingå i resultatet.

**Denna fils commit är indexets stämpel** för verktygen på
`slice-merged`. Syskon-HEAD:ar nedan är pinnade.

| Verktyg | Spår | Bor | Commit (pin) |
|---|---|---|---|
| `obducera` | I | denna worktree `toolbox/obduktion/` | `slice-merged` HEAD |
| `dashadapter` | I | denna worktree `toolbox/dashadapter/` | `slice-merged` HEAD (landad `e7a84f4`) |
| `validera_klassning` | C | denna worktree `toolbox/taxonomi/` | `slice-merged` HEAD (landad `3f8c641` matchskärpning) |
| `heatmap` | D/qwen | `~/ft-toolbox-h` `toolbox/heatmap-cli` | `da501f4` |
| `stamp.py` | A | `~/ft-toolbox-a` `toolbox/a-stampling` | `3031053` |
| B-körgrind | B | `~/rtx-toolbox-b` `toolbox/b-planner-telemetry` | se § B |
| dashboard I-klasser | I | `~/rtx-toolbox-dash` `toolbox/dashboard-i-classes` | `356c110` |

---

## obducera

**Syfte.** Batch-obduktion: mät-JSONL (T1h- eller K-layout) → händelser
(`fall` / `avsett_drop` / `stall` / `timeout` / `fastnad`) → kluster →
prioriterad åtgärdslista. GraphMatcher/A-stämplar via `--stamplar`;
xyz → cell gissas aldrig. Default `--regim kedjad` (E).

**Stämplat läge.** `--stamplar DIR` fogar A:s rader
`{t,bot,cell,verdict,schema,graph_stamp}` på index, annars `t` 3 dec.
Avvikande stamp ⇒ cell/länk nollställs. `plan` släpps rått (B).
`.attr.json` läses men binds inte. Airborne-fastnad/timeout som slutar
i luften binds via `_last_known_before` (`bind=fallback`);
västväggs-`missing` förblir unknown.

**Populationer (alltid tre).** `alla_giltiga_N*`, `kedjad_N*`,
`teleport_efter_fel_N*`. T1h kapas till N=min(n_hela) (A76–79 kastas).
Unknown-kluster bär `(arm, ben)` — blandar inte sida/rutt.

**Anrop.**

```
python3 -m toolbox.obduktion --serie ~/lab/t1h --stamplar ~/lab/t1h/stampad \
    --regim kedjad --out atgarder.json
```

**Kontrakt / schema.** `verktygslada/obducera/3` —
`toolbox/obduktion/KONTRAKT.md`. (v3 = I-justering + slice 2.1;
heatmap läser v2 och v3.)

**Tester.** `python3 -m unittest toolbox.obduktion.tests.test_obduktion
toolbox.obduktion.tests.test_slice_adapter`

---

## heatmap-CLI

**Syfte (smal roll).** Statiska bevisbilder: GPU-fri filtransformation
(obducera-JSON + graf-JSON) → SVG + kanonisk JSON-sammanfattning.
Ingen server, ingen rigg, ingen live-heatmap. Unknown-cell ritas inte.

**Kompatlista (`OBDUCERA_COMPAT`).** Läser `verktygslada/obducera/2`
och `/3`. Annat schema ⇒ exit 2 med listan i felmeddelandet.

**Anrop** (worktree `~/ft-toolbox-h`):

```
python3 toolbox/heatmap/heatmap.py --obduktion FILE.json --graf GRAF.json \
    --population kedjad_N75 --klass alla --out-svg out.svg --out-json out.json
```

**Kontrakt / schema.** `verktygslada/heatmap/1` —
`toolbox/heatmap/KONTRAKT.md` @ `da501f4`.

**Tester.** Fixturer i `toolbox/heatmap/fixtures/`. H4: 2× CLI,
byteidentisk SVG/JSON (kimi-qa).

**Branch.** `toolbox/heatmap-cli` — inte inmärgad i slice-merged.

---

## dashadapter

**Syfte.** Fyller stallkartans `map-template.html` via
`parent.PROPOSAL_DATA`. Ingen ny renderare.

**v2.** Native I-klassnycklar (`fall`, `fastnad`, `timeout`,
`avsett_drop`, `stall`). `--map-template` obligatorisk; saknas någon
I-nyckel i REASONS ⇒ avbrott (ingen tyst BotStall-mappning).
`avsett_drop` är `off:true` i visCount-listan.

**Anrop.**

```
python3 -m toolbox.dashadapter --obducera FILE.json --out-snapshots snaps.json \
    --map-template map-template.html [--out-html out.html]
```

**Kontrakt / schema.** `verktygslada/dashadapter/2` —
`toolbox/dashadapter/KONTRAKT.md`. Templat-tillägg på
`toolbox/dashboard-i-classes` @ `356c110` (`~/rtx-toolbox-dash`).

**Tester.** `python3 -m unittest toolbox.dashadapter.tests.test_dashadapter`

---

## validera_klassning

**Syfte.** Evidensplikt före taxonomirunda 2. Tar klassnings-JSONL
(`id`, `klass`, `evidens{}`) mot kandidatfilen. Saknas rev 4-fält
eller pekare som inte träffar kandidatens `kallor` ⇒ avvisad rad,
förslag `okand_ingen_fix` + `missing_*`. Klassar inte.

**Matchning (skärpt `3f8c641`).** `_fil_match`: exakt sökväg eller
suffix på `/`-gräns. Inte substring (`fil="O"` mot
`WORK_LOGS/grok-stallceller.md §2` avvisas).

**Anrop.**

```
python3 -m toolbox.taxonomi --klassning klassning.jsonl \
    --kandidater WORK_LOGS/taxonomi-kandidater-blind.jsonl --out rapport.json
```

**Kontrakt / schema.** `verktygslada/taxonomi-validering/1` +
`verktygslada/taxonomi-klassning/2`. Kravtabell:
`toolbox/taxonomi/krav.py` (mot utkastet `verktygslada/taxonomi/4`).

**Tester.** `python3 -m unittest toolbox.taxonomi.tests.test_validera_klassning`

---

## stamp.py / graphstamp-kontraktet

**Syfte.** Offline A-stämpling av K/T1h-JSONL. A äger rotfälten;
nyckeln `plan` skrivs aldrig.

**Tvånivåidentitet** (`WORK_LOGS/graphstamp-kontrakt.md` i
buzz-4on4-workspacen; A äger, B speglar):

| nivå | fält | algoritm | plats |
|---|---|---|---|
| 1 | `graph_stamp` | FNV-1a-64 över `map ++ LE32(cells,links,rj_links)` | varje JSONL-rad, decimalsträng |
| 2 | `graph_content_hash` | SHA-256 över kanonisk C/L-inventering | PlanContract + `.attr.json`, **aldrig** per rad |

Gyllene dm3 T1h: `graph_stamp("dm3", 5978, 48208, 0) =
13090435456435551592`. Radlager: sentinel `4294967295`;
domlager: `"unknown"`.

**Anrop** (worktree `~/ft-toolbox-a`):

```
python3 fasttrack/stamp.py --graph DUMP.json --map dm3 \
    --cells 5978 --links 48208 --rj 0 --in RAW.jsonl --out STAMP.jsonl \
    [--attr ATTR.json]
```

**Kontrakt / schema.** Rad: `qw-nav-graph/1`. Attribution 1373:
landning 1376, inte start (test `test_attribution_1373.py` @ `6bcb5a1`
och senare).

**Tester.** `python3 -m unittest fasttrack.tests.test_graphstamp
fasttrack.tests.test_attribution_1373` (plus GroundVerdict-sviten).

**Branch.** `toolbox/a-stampling` @ `3031053` — inte inmärgad i
slice-merged.

---

## B-körgrind (rtx, inte detta repo)

Pekare: `~/rtx-toolbox-b` branch `toolbox/b-planner-telemetry`,
katalog `testsuite/tools/`. Kontrakt: `testsuite/tools/B-KORGRIND.md`.
Instans: `toolbox-b-test`, ctl **27995**, spel 27590.

| Skript | Syfte | Anrop |
|---|---|---|
| `b_v296_replay.py` | rå V296-återspelning, ingen dom | `python3 b_v296_replay.py --port 27995 --n 10 --out ~/lab/v296-replay.jsonl` |
| `b_regressionsdiff.sh` | noll PlanTick/PlanContract med cvarer av + signatur | `./b_regressionsdiff.sh --port 27995 --out ~/lab/b-regress/tbx` |
| `b_overhead.sh` | serverklocka/väggtid av vs på, tröskel 1 % | `./b_overhead.sh --port 27995 --secs 60` |

Schema på tråden: `qw-nav-graph/1` PlanTick/PlanContract. Tester bor i
`crates/rtx-game` / `crates/rtx-ctlproto` (`plan_row_due`,
`phase_prev`, `Cause`/`AttestedCause`). C2-startfördelning: se
B-KORGRIND.md (flagga 3-doknot).

---

## Övrigt på slice-merged

| Yta | Roll |
|---|---|
| `toolbox/obduktion/mcp_hook.py` | MCP-hook, samma JSON som CLI |
| `map-template.html` REASONS | utökas på dashboard-branchen, inte här |

`fixa` (spår D) är inte byggt som lådkommando på denna linje.
`pris_vreq` i taxonomin är o-certifierad (Fable).
