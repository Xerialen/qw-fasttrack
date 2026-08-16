# TOOLBOX.md — verktygslådan (fork, inte main)

Ett kommando-API, tre fronter. Paritet = kanonikaliserad JSON mot
`toolbox/obduktion/KONTRAKT.md` (CLI ↔ MCP). Webben är klient.

| Kommando | Spår | Status | CLI | MCP | Webb |
|---|---|---|---|---|---|
| `obducera --serie DIR` | I | v1 på `toolbox/i-obduktion` | `scripts/obducera.py` / `python3 -m toolbox.obduktion` | `obducera` (read-only) | ej ännu (fas: overlay efter vertikal slice) |
| `heatmap` | A | — | — | — | — |
| `stämpla` | A | — | — | — | — |
| `fixa` | D | — | — | — | — |
| `validera_klassning` | C | v1 på `toolbox/slice-merged` | `python3 -m toolbox.taxonomi` | ej ännu | — |

## obducera

Läser mät-JSONL (T1h- eller K-layout) + stämplar från spår A när de finns.
Utan stämpelfält: `cell`/`lank` = `"unknown"` — xyz gissas aldrig.
Default `--regim kedjad`.

```
python3 scripts/obducera.py --serie ~/lab/t1h --regim kedjad --out atgarder.json
```

Schema: `verktygslada/obducera/2`. Kontrakt: `toolbox/obduktion/KONTRAKT.md`.
Unknown-kluster bär `(arm, ben)`. Alltid tre populationer
(`alla_giltiga_N*`, `kedjad_N*`, `teleport_efter_fel_N*`) med etikett
på varje kluster/åtgärd. T1h kapas till N=min(n_hela).
Tester: `python3 -m unittest toolbox.obduktion.tests.test_obduktion`.

Återanvänder peak_drop_150-semantiken (samma reset som `timtest_ben`) och
stall-events-embryots per-cell-klustertanke (`match_snapshot._summarize`).
Live-riggen rörs inte.


## validera_klassning

Runda 2: klassningsfil (jsonl `id`, `klass`, `evidens{}`) mot kandidatfil.
Saknas obligatoriska evidensfält (rev 4) eller pekare in i kandidatens
källor ⇒ raden avvisas, förslag `okand_ingen_fix` + `missing_*`.

```
python3 -m toolbox.taxonomi --klassning klassning.jsonl \
    --kandidater kandidater-blind.jsonl --out rapport.json
```

Tester: `python3 -m unittest toolbox.taxonomi.tests.test_validera_klassning`.
Klassar inte.
