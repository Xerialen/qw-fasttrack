# Tool Manifest — Human Movement Lab & Route Curation (end-to-end)

Model-agnostic. Every agent (Claude profiles, Codex CLI, GLM, Kimi, ...) gets
the full toolchain from this file — no Claude skills or MCP servers are
load-bearing anywhere in the chain. Claude profiles additionally have the
`movement-lab` skill, which is a *thin router* into these same repo docs; if
you are not Claude, you lose nothing by not having it.

Canonical process: `docs/runbooks/human-movement-lab.md` (read its **Ärr** and
**Metodlärdomar** sections BEFORE debugging routing — they encode the expensive
mistakes). Spec discipline: `docs/reviews/2026-07-23-sol-gap-spec-format-review.md`.
Everything below runs from WSL Ubuntu-24.04 with
`cwd = /mnt/c/Users/benya/projects/quakeworld/qw-fasttrack`.

---

## Stage 0 — Rig boot

| Tool | Use | Notes |
|---|---|---|
| `fasttrack.core.server_up(map, bots, lib)` | Boot the lab mvdsv server (game 27530, control 27980, QTV 29530) | `bots=0` for human-only monitoring; `bots=1` for bot iteration. Auto-replants the active patch on boot. Pass an explicit `lib` — `DEFAULT_LIB` may be older than the rig's current build. |
| `fasttrack.core.wait_ready(expect_bots=...)` | Block until navmesh ready (+ bot alive if expected) | Bot-less servers still build the mesh (control-port gate in population.rs). |
| `fasttrack.core.graph_dump(map, seed, name)` | Dump live graph → viewer overlay `<name>-graph.json` | **Caveat: exports tombstoned (unlinked) links.** Never trust dump link-ids after removals — verify against the engine (`unlink <id>` answers "already unlinked"). |
| `fasttrack.core.live_start(map, graph, push=, record=)` | Start bridge (ws 8093) + viewer (8090) | **Poll mode for bot work** (pmove push excludes bots). Push mode = precision human telemetry. |
| Viewer URL | `http://127.0.0.1:8090/?graph=<name>&live=8093[&overlay=<name>]` | Loopback-only; open on the host. |

## Stage 1 — Live monitoring (human plays)

| Tool | Use | Notes |
|---|---|---|
| `scripts/ws_probe.py [N] [port]` | Sanity: frames flowing, actor digest | Never touches the control channel. |
| `scripts/follow_live.py [port]` | Follow the human: zone changes, genuinely new mesh gaps, stop detection | Seeds away the known-gap backlog. |
| `scripts/jump_receipt.py` | Live per-jump receipts (≥150u) from the pmove JSONL | Includes teleporter discriminator (>120u/frame = tele, never a jump). |
| `core.ctl(...)` / proxy 27981 | ALL control traffic | **One reply-reader on 27980.** Never probe the control port directly while a dump/bridge runs. |

## Stage 2 — Precision evidence (pmove push)

| Tool | Use | Notes |
|---|---|---|
| `core.live_start(..., push=True, record='<jsonl>')` | Authoritative FL_ONGROUND + server velocity per frame | Default since 2026-07-23; owner-qwd + `core.demo_ingest` is the fallback for builds without `rtx_telemetry`. |
| `demo_mesh.load_samples_jsonl(path)` → `extract(samples, authoritative_mask=...)` | Ingest pmove evidence into gap candidates | Contact sequence is DATA, not inference. |
| `cmd record` / `cmd stop` (via `core.ctl`) | Server-side MVD for the owner's eyes | Review artifact only — never ingested. |

## Stage 3 — Gap analysis → spec

| Tool | Use | Notes |
|---|---|---|
| Offline graph queries (python over `<name>-graph.json`) | Existence/shape questions: "is there a speedjump-free path?", cell/link enumeration by geometry window | **Never for "why did the router choose X"** — production pricing (banded, hazard, penalties, jitter) is invisible in the dump. |
| Spec file | `route-lab/artifacts/nav-patches/dm3-<name>-missing-spec.json` (`qw-missing-spec/1`) | Status-mark everything (`ready_candidate`/`chain_suspect`/`evidence_only`); `selected_candidate` null until exact payload + owner confirmation in the viewer. |
| Overlays | `route-lab/qw-nav-viewer/overlays/<name>.json` (`qw-nav-overlay/1`) | rj-start/rj-goal markers + polylines; confirm with the owner BEFORE locking the spec. |
| `core.demo_replay_start(qwd, graph)` | Loop a demo in the viewer (ws 8095) for owner confirmation | |

## Stage 4 — Curation (planting & removal)

| Tool | Use | Notes |
|---|---|---|
| `core.patch_apply(patch, store=True)` | Apply `qw-nav-patch/1` (SpeedJump/JumpGap → `planlink`, Cell → `plancell`, RocketJump → `planrjraw`, removes → `unlink`) | Stored patch auto-replants on server restart. **Curate ONE link → trial → next.** Never bulk. |
| `planlink` (via patch) | Planted links get curl executor (gain 12) + trusted cost `runup/400 + airtime + 0.3` | Planted links are executed by the production executor; native links of the same geometry are refused fail-closed. Replace broken native classes with planted payloads from owner evidence — don't fight costs. |
| `unlink <id>` (via `core.ctl` or patch removes) | Tombstone a link | **Does NOT rebuild router tables.** End every removal batch with a replant (unlink + planlink of one of your own links) to force `rebuild_derived`. Enumerate the whole geometric family first (twins/duplicates exist). |
| Rule 11.2 | Placements/v_req from owner evidence are calibration data — OK in specs/patches. Trajectories/usercmds NEVER into bot code. | |

## Stage 5 — Trials & gates

| Tool | Use | Notes |
|---|---|---|
| `scripts/ra_gate.py <bot> <threshold> <streak> [max] [jsonl]` | Owner gate RA-tunnel→RA-top via the `ra_trial` verb | Runs through the proxy so the bridge keeps its channel (owner watches live). JSONL evidence per attempt. Large result events (≤4096 samples) can block the channel seconds — generous timeouts. |
| `ra_trial <bot> ra_spawn <max_secs>` (control verb) | The right instrument for item-goal measurement | Movement-based 1 s stall + fall detector (the owner's fast-fail rule), authoritative pickup, wall telemetry, full samples. |
| `core.trial(start, target, ..., pass_time_s=, streak_target=, arrive_box=)` | Puppet goto-based trial (v2 streak mode) | **Puppet ≠ production**: puppet executes native speedjumps production refuses; its stall watchdog is straight-line-XY to goal and false-stalls routes that pass under the target. Use for link-level A/B, not item-goal gates. |
| `penalties <bot>` (control verb) | Live failed-link penalty picture mid-run | First instrument when routing looks irrational. Penalty memory conditions behavior and is wiped by restart — **book gate numbers only from a freshly restarted state.** |
| `route <bot>`, `sjtrace <bot>` | Route/executor introspection | `route` shows a stale/other route object while `ra_trial` runs — validate the instrument in the current mode. |
| ra_trial result samples | Columns route_pos/link + `initial_route` in the result event | The ground truth for "what did the bot actually traverse". |

## Stage 6 — When to stop touching the mesh

If trajectory AND times are identical after a graph edit that should have
mattered (e.g. removing the very link the behavior appears to use), the
behavior is owned by executor/pursuit **code**, not the mesh. Stop mesh
surgery, document the blocker in the spec (`kodlane_blockerare` pattern in
`dm3-ra-mellanledge-missing-spec.json`), and hand off to the bot-code lane.

---

## Surfaces that are Claude-only (never load-bearing)

- `movement-lab` skill (`~/.claude/skills/movement-lab/`) — thin router to the
  runbook + this manifest. Content duplicated there must stay a pointer.
- Auto-memory / vault notes — pointers and rig state only.

If you find process knowledge that exists ONLY in a Claude skill or memory,
that is a bug: move it into this repo (runbook or this manifest) and leave a
pointer behind.
