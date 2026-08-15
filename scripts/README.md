# scripts/

Helper scripts — setup, data wrangling, validation, automation, one-off tooling.

- `ws_probe.py [N] [port]` — läs N `qw-live-frame/1`-frames från brygga (8093)
  eller replay (8095), digest per aktör. Rör aldrig kontrollkanalen.
- `follow_live.py [port]` — följ människan live tills hen stannar; glesa
  events (zonbyten, genuint nya mesh-luckor, stopp). Monitor-vänlig; seedar
  bort redan kända luckor. Se `docs/runbooks/human-movement-lab.md`.
- `ra_gate.py <bot> <threshold> <streak> [max] [jsonl]` — ägargaten RA-tunnel→RA-topp
  via ra_trial-verbet (proxy-säkert). JSONL-evidens per försök.
- `mega_gate.py <bot> [jsonl]` — ägarprotokollet SNG-spawns→mega (scenarierna
  sng_mega_w/sng_mega_s): completion 5/5 → rekordjakt → bekräfta 5/5 = ny
  baseline → 30 raka missar ⇒ senaste baseline gäller. JSONL per försök.
- `jump_receipt.py` — tail:ar pmove-JSONL:en och kvitterar varje hopp ≥150u
  live (takeoff→landning, distans, luftfas, serverfart) med grov
  tele-diskriminator. Används när ägaren registrerar hopp på beställning.
- `stall_recorder.py [--out FIL] [--lines N] [--bot N] [--max N]` — lyssnar på
  `bot_stall` (rtx styrvakthundarna: displacement / progress / speedjump_stall /
  air_commit_off / air_commit_timeout / prestrafe_deficit) och parar varje stall
  med `audit <bot> <lines>` hämtad direkt efteråt, en JSONL-rad per stall.
  Stallet säger var boten fastnade, auditsvansen vad den försökte precis innan —
  var för sig är de gissningar. Kräver en rtx-motor med BotStall-eventet.

Document how to run anything non-obvious in `docs/environment.md` (the runbook).
Changes here count as code changes for the documentation contract (see
`AGENTS.md`): update at least one relevant doc when you change behavior.
- `match_snapshot.py --secs N --label L --branch B --build SHA --out f.json` — följ en
  labbmatch: quad/pent-cykler (2 Hz), fart/stillastående (10 Hz), bot_stall-events;
  skriver snapshot-JSON för stall-diagnostik-artefakten. Arkiv:
  `~/.local/share/qw-fasttrack/evidence/snapshots/<datum>/`.
- `combat_lock.py --json <qw-analyze-full.json> [--out r.json]` — sekunder per spelare
  beskjuten inom POV (120°) utan att skjuta tillbaka (fönster 1.2 s). Kör qw-analyze
  `-view full -include positions,view` först.
- `obducera.py --serie DIR [--regim kedjad] [--arm A|B|AB]` — batch-obduktion (spår I): JSONL → klassade händelser → kluster → prioriterad åtgärdslista. Default evidensfilter `regim=kedjad`. Utan A-stämplar: cell/länk = unknown (gissas aldrig). Kontrakt: `toolbox/obduktion/KONTRAKT.md`. Samma JSON via MCP-verktyget `obducera` (read-only).
