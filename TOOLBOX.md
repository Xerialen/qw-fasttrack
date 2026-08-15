# TOOLBOX.md — verktygslådan (fork, inte main)

Ett kommando-API, tre fronter. Paritet = kanonikaliserad JSON mot
`toolbox/obduktion/KONTRAKT.md` (CLI ↔ MCP). Webben är klient.

| Kommando | Spår | Status | CLI | MCP | Webb |
|---|---|---|---|---|---|
| `obducera --serie DIR` | I | v1 på `toolbox/i-obduktion` | `scripts/obducera.py` / `python3 -m toolbox.obduktion` | `obducera` (read-only) | ej ännu (fas: overlay efter vertikal slice) |
| `heatmap` | A | — | — | — | — |
| `stämpla` | A | — | — | — | — |
| `fixa` | D | — | — | — | — |

## obducera

Läser mät-JSONL (T1h- eller K-layout) + stämplar från spår A när de finns.
Utan stämpelfält: `cell`/`lank` = `"unknown"` — xyz gissas aldrig.
Default `--regim kedjad`.

```
python3 scripts/obducera.py --serie ~/lab/t1h --regim kedjad --out atgarder.json
```

Schema: `verktygslada/obducera/1`. Kontrakt: `toolbox/obduktion/KONTRAKT.md`.
Tester: `python3 -m unittest toolbox.obduktion.tests.test_obduktion`.

Återanvänder peak_drop_150-semantiken (samma reset som `timtest_ben`) och
stall-events-embryots per-cell-klustertanke (`match_snapshot._summarize`).
Live-riggen rörs inte.
