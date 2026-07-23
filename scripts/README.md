# scripts/

Helper scripts — setup, data wrangling, validation, automation, one-off tooling.

- `ws_probe.py [N] [port]` — läs N `qw-live-frame/1`-frames från brygga (8093)
  eller replay (8095), digest per aktör. Rör aldrig kontrollkanalen.
- `follow_live.py [port]` — följ människan live tills hen stannar; glesa
  events (zonbyten, genuint nya mesh-luckor, stopp). Monitor-vänlig; seedar
  bort redan kända luckor. Se `docs/runbooks/human-movement-lab.md`.
- `ra_gate.py <bot> <threshold> <streak> [max] [jsonl]` — ägargaten RA-tunnel→RA-topp
  via ra_trial-verbet (proxy-säkert). JSONL-evidens per försök.
- `jump_receipt.py` — tail:ar pmove-JSONL:en och kvitterar varje hopp ≥150u
  live (takeoff→landning, distans, luftfas, serverfart) med grov
  tele-diskriminator. Används när ägaren registrerar hopp på beställning.

Document how to run anything non-obvious in `docs/environment.md` (the runbook).
Changes here count as code changes for the documentation contract (see
`AGENTS.md`): update at least one relevant doc when you change behavior.
