# Findings Log

## 2026-07-23 — ÖPPEN DISKREPANS: curl-mål-cvars (döda eller krävs?)

### Experiment
Ingen — dokumentläsning inför merge-trial. Ägarbeslut: håll öppen, glöm ej.

### Result
Två dokument motsäger varandra om curl-mål-cvars för planterade länkar:
- `docs/solutions/2026-07-22-dm3-under-lifts-to-sng.md` (lager 1, pkt 3,
  skriven ~22:45): "curl-cvars MÅSTE sättas (annars styr
  default-gain-12-korrigeringen flygbågen mot osatta mål): gain 12,
  entry (−220,637), switch 160, landing (−302,535)."
- `docs/runbooks/qwd-till-gron-rutt.md` (steg 5, skriven 23:54, nyare):
  "Curl-mål-cvars behövs INTE i denna build (entry/switch/landing-cvars är
  döda; endast `rtx_jump_curl_gain` global gain finns — planterade länkar
  får gain 12 by default och luftsikte mot länkens landning)."

### Interpretation
**LÖST 2026-07-23 (merge-trial-sessionen), via kodarkeologi:** båda
utsagorna var sanna — för varsin build.
- `focus-controller` (04437e7, rutt A-certifieringen): `SpeedJumpTraversal`
  har INGA aim-fält; `plant_link_json` sätter gain-default **12**; flygningen
  är `air_correct`-pursuit mot bearing (länkens landning). = runbokens text.
- `ra-tunnel-on-main` (3222689): traversal HAR aim-fälten
  (entry/switch/landing) och `plant_link_json` defaultar gain **0**
  ("planted links fly straight", 6ef6105) — för i DEN runtimen homade
  gain>0 mot osatta aim-cvars → map origin (spawn-7-blockern).
- Lösningsdokumentets "curl-cvars MÅSTE sättas" beskrev en tidig
  focus-iteration; slut-04437e7 hade redan tagit bort aim-fälten.

### Merge-beslutet
I mergen (branch `merge-trial`): gain-default 12 ÅTERSTÄLLD (facit) ovanpå
deras traversal-struct. Säkert eftersom aim-fälten bara aktiveras via
profilerad axel (`curl_switch_dist != 0`), vilket cvar-lösa plants aldrig
får — spawn-7-mekaniken kan inte återuppstå. Empiriskt dömt av gaterna
(rutt A + RA-acceptans).

### Confidence
High (verifierad mot båda sidors källkod; empirisk dom via gaterna).

### Follow-up
Rätta lösningsdokumentets lager-1-punkt-3 ("curl-cvars MÅSTE sättas") med
en not — texten är historisk. Runbokens text står.

## YYYY-MM-DD

### Experiment
What was attempted?

### Result
What happened?

### Evidence
Actual terminal output, logs, metrics, screenshots, links, commits.

### Interpretation
What do we think this means?

### Confidence
Low / Medium / High

### Follow-up
What should be tested next?

## 2026-07-22 — grounded apex artifacts

### Experiment
Replace sample-count plateau detection with the specified time-based one-sided
window, then run both synthetic and real xersng QWD regressions. Add a z-stable
live unresolved streak and validate the final replay in Movement Lab.

### Result
The first implementation was rejected: it left quantized apex cells and
increased missing cells from 38 to 46. A QWD peak-turn veto removed those
artifacts. A 144 Hz regression then found that a final airborne sample could
borrow the stable landing plateau; requiring a flat adjacent step closed that
boundary too. The plan's allegedly real z=163.8 shelf was also proven to be an
airborne +43.8u apex and intentionally removed. Final `missing_spec` has 4
surface cells; direct replay has 9 surface cells instead of 42 mixed cells.

### Evidence

- Red-first: synthetic plateau/apex test failed twice; live helper import was
  absent.
- Focused final tests: 3 grounded-mask, 4 attribution/proxy, 1 MCP test green.
- Real demo: `cells_required=182`, `cells_missing=4`,
  `jumps_required=26`, `jumps_missing=17`, hover violations 0.
- Artifact sha256:
  `82386b4f4f48ff0bf9d907ec652c820144e140a231df96d3478beba5a4c909d8`.
- Browser evidence:
  `docs/evidence/2026-07-22-grounded-apex-surfaces.png`.
- Final headed WebGPU browser console: `live-id maps: 4621 cells, 50218 links`;
  no page error in the accepted run.

### Interpretation
Spread alone is not a sufficient stationary-ground signal when a quantized
ballistic window straddles its maximum or touches the landing plateau. A
pronounced interior maximum plus a flat adjacent step are the missing
discriminators. The previous z=163.8 “ground truth” came from the bugged
classifier itself and was circular evidence.

### Confidence
High for the recorded QWD and 15 Hz live streak contract; medium for unusual
non-ballistic vertical movers, which remain an accepted limitation.

### Follow-up
Independent review should check the 0.5u peak-turn margin and run one demo
containing a real lift/water pause, which this bug intentionally does not fix.

## 2026-07-22 — Toolbox v2 Phase 1

### Experiment
Implement Trial v2 and replay P0.2–P0.4 without starting a game server. Add
mocked control-channel timing tests, coordinator/real-loopback-WS tests, and a
cross-`PYTHONHASHSEED` subprocess test over the complete offline artifact.

### Result
Trial success now comes from the first received `status.bots[].origin` inside
the requested box; terminal events are evidence only. Replay commands are
serialized through one coordinator, while each client gets a non-blocking
one-slot latest-frame writer queue. Offline samples and dedup products have a
total deterministic order. All 17 WSL unit tests pass.

The confirmed replay wedge was caused by `_broadcast` iterating all clients
and awaiting each `writer.drain()` inline. One slow or churned socket therefore
stalled replay's sole frame producer indefinitely. The asyncio scheduler could
still run an accept handler and write HTTP 101, but a fresh client received no
first application frame and was operationally indistinguishable from a wedged
handshake. Broadcast now only replaces each client's queued snapshot; the
client's sole writer task owns every frame/pong write and any blocked drain is
isolated to that client. The churn regression blocks one server-side `drain()`
indefinitely and proves a fresh client still completes handshake and receives
a frame within one second.

The offline nondeterminism came from ordering only samples by timestamp and
then trusting insertion order in fuzzy-attribution/dedup structures. Equal-time
records could retain parser/hash-dependent order, which changed transition
attribution and then the insertion order of used/missing links. Samples now
use a total `(t,x,y,z,speed)` order at both ingestion and timeline boundaries;
cell buckets, jump buckets, missing points, and overlay indexes are explicitly
sorted before serialization.

### Evidence

- Red-first excerpts:

  ```text
  TypeError: trial() got an unexpected keyword argument 'pass_time_s'
  ImportError: cannot import name 'PlaybackCoordinator' from 'demo_replay'
  FAILED (errors=5)
  ```

- Focused final: 12 Trial/replay/MCP tests passed in 1.808 s.
- Full-suite transcript under Ubuntu-24.04:

  ```text
  $ python3 -m unittest discover -s fasttrack/tests
  ...................
  ----------------------------------------------------------------------
  Ran 19 tests in 1.437s

  OK
  ```

- Churn regression: five connect/disconnect clients plus one non-reader; a
  fresh client completed handshake and received a frame under the 1 s bound.
- Hash-seed regression: full canonical timeline+missing-spec SHA matched for
  seeds 1 and 2.
- No game server, viewer worktree, rex tree, or route-lab main tree was changed.

### Interpretation
The timing and replay evidence paths are now bounded by received observations
and deterministic state ownership rather than terminal-event timestamps,
client backpressure, or incidental iteration order.

### Confidence
High for the unit-level measurement semantics, loopback churn behavior, and
synthetic cross-seed determinism contract. Real route acceptance remains a
later phase and was intentionally not run while the externally owned boot was
active.

### Follow-up
Run the required independent Claude review for Phase 1. Phase 2 can then add
the optional playback field and controls to the isolated viewer worktree.

## 2026-07-22 — Toolbox v2 Phase 3 / P1 bsp-probe

### Experiment
Build a persistent rex JSONL oracle around the existing `Bsp::hull1_trace`,
then replace the demo ground classifier through the specified optional seam.
Pin the exact BSP used by fasttrack's server skeleton, exercise the approved
surface/apex points in Rust and Python, and compare real xersng ingest against
the old heuristic under a 30-second gate.

### Result
Rex branch `bsp-probe` through commit
`0e94183b15561bc610df30fbf41cd42b2e6073b0` adds `bsp-probe`. It loads one
BSP per process, emits `{"v":1}` before
serving requests, traces the standing-player hull 2u down from the supplied
origin without pre-offset, and samples render-hull contents at the origin.
The three dm3 moving brush models are reconstructed from the entity lump using
stock door/plat/train travel rules. The probe samples their travel paths and
traces the actual translated submodel hulls; a hit returns `unknown`.

Python uses one long-lived subprocess with a five-second response bound.
`unknown` points are individually marked and use the heuristic; a crash,
timeout, invalid protocol row or `error` response discards every partial
oracle result and restarts classification wholly in heuristic mode. Artifacts
carry `method`, BSP SHA, probe commit, structured fallback reason and the list
of per-point unknown fallbacks.

The server skeleton BSP is
`/home/xerial/.local/share/route-lab/nav-ab/qw/maps/dm3.bsp`. It is
byteidentical to `/mnt/c/nQuake/qw/maps/dm3.bsp`; both hash to
`aec9edbb727c0a206edc2c0688775ce8242c0d51e1ee7583c7126c76f7c3b2f1`.

### Evidence

- Rust: 67 library tests plus three binary tests passed (the mandatory
  acceptance points, a translated intermediate mover position and scalar-yaw
  secret-door orientation); final release build completed in 22.85 s.
- Python: 24/24 WSL unittests passed in 8.826 s. The subprocess tests also ran
  under `-W error::ResourceWarning` after closing the initial stdout-handle
  leak found during the first focused run.
- xersng oracle ingest: 1.16 s, 189 required cells, 4 missing cells, 33
  required jumps and 14 missing jumps. Grounding provenance names BSP SHA
  `aec9ed…b2f1`, probe commit `0e94183b…73b0`, method `oracle`, no mover
  fallbacks in this recording.
- Heuristic control: 182 required cells, 4 missing cells, 26 required jumps and
  17 missing jumps. Thus the requested missing-cell count comparison is 4 vs
  4; the oracle changes which samples/jumps are accepted, not this graph's
  final number of missing cell buckets.
- Oracle missing points are `(-292.6,548.2,120)`, approximately
  `(79.5,670.5,40)`, `(310.1,670.4,56)`, `(336.2,666.1,56)`. The fourth
  bucket centroid shifts from the heuristic's `(83.3,670.0,40)` because the
  oracle admits additional genuine floor samples. All missing z values are
  40/56/120; no ~99.8 apex class remains.

### Interpretation
The spec's hull correction is decisive: player origins are already the input
coordinate system for hull 1. Applying another −24u would ask about a player
box buried in the floor. Static BSP geometry can make stable-window heuristics
miss genuine short contacts; conversely the trace removes the quantized apex
without trajectory inference.

### Deviations and corrections

- The spec's example `/mnt/c/nQuake/qw/id1/maps/dm3.bsp` does not exist on
  this machine. The live skeleton and nQuake copy above were found from
  `fasttrack/core.py::SKELETON` and pinned instead, as explicitly permitted.
- Repo-wide `cargo fmt --all -- --check` is already red on many unrelated
  rex files. The new `bsp-probe.rs` passes a targeted rustfmt check; no
  unrelated formatting was changed.
- The golden missing-cell count is equal (oracle 4, heuristic 4), not lower.
  The measured semantic delta is 189 vs 182 required cells and 14 vs 17
  missing jumps; this result is recorded rather than forced to differ.
- The first internal review found that Python initially attributed the current
  rex HEAD rather than the built executable, and that mover detection used a
  static submodel AABB. Both were rejected before handoff: the release binary
  now embeds/returns its build commit (verified equal to final rex HEAD), and
  mover-space uses translated submodel hull traces over reconstructed stock
  travel paths, including secret-door two-stage travel and closed train loops.
  The golden was also strengthened to assert the nearest real
  xersng samples for all four approved surface points through the ingest seam.

### Confidence
High for static-world floor/apex semantics, build provenance and
crash/fallback behavior on pinned dm3. Medium around moving brushes: stock
door/plat/train paths are reconstructed and actual hulls are traced, but the
oracle intentionally cannot observe a mover's instantaneous live position.

### Follow-up
Run the required independent Claude Phase 3 review. If accepted, proceed to P3
and use the new grounding provenance in its proof bundle.

## 2026-07-22 — Toolbox v2 Phase 4 / P3 gap_to_proof

### Experiment
Implement the approved rev-3 ordering as one MCP/core operation, prove the
ownership and cleanup behavior entirely through mocked seams while another
task owns port 27530, unify overlay I/O, and replace promotion's legacy `ok>0`
gate with the complete A/B/streak evidence contract.

### Result
`gap_to_proof(demo, map, seed, route, name?)` checks `fasttrack-server` and
`fasttrack-live-bridge` unit status before its first mutation. Once ownership
is clear it removes only stale bridge state, clears the active patch, clean
boots, dumps G0, ingests exactly against G0, runs Trial v2 baseline, calls
`patch_apply` exactly once, runs Trial v2 patched, then always clears and
restarts the map. SIGALRM-backed WSL bounds are 1800 s baseline boot, 180 s
graph dump, 300 s ingest, 600 s per trial, and 60 s apply. The 5430 s overall
deadline is measured from the original workflow start and reserves 1800 s for
cleanup plus 30 s for evidence writing after the 3600 s work deadline, so no
phase resets the total clock and restoration time cannot be consumed by work.

The bundle contains `gaps.json`, `patch.json`, `ab.json`, and
`provenance.json`, each bound by filename+SHA-256 in `manifest.json`.
Per-attempt A/B rows include elapsed, outcome, streak and patched-minus-baseline
delta (negative is faster). Provenance carries graph, active patch, BSP and
probe SHAs/commits plus baseline/patched cvar readback. Interrupted and failed
runs write whatever evidence exists with `partial:true`. `promote` verifies all
four SHAs, requires baseline streak evidence and `patched.passed` with
`streak_max >= streak_target`, checks that the stored patch equals the proof
patch, and copies the whole bundle.

### Evidence
The exact requested WSL command passed 33 tests in 5.271 s. New tests use
mocked units, server boot, graph dump, ingest, patch application and Trial v2;
they cover server ownership abort, live-bridge ownership abort, ambiguous unit
status fail-closed, exact ordering, middle-phase failure, partial marking,
cancellation cleanup, promotion reject (including a SHA-valid empty A/B table),
promotion accept, and MCP count 17. No real server/control call was made.

Actual final terminal output:

```text
$ python3 -m unittest discover -s fasttrack/tests
.................................
----------------------------------------------------------------------
Ran 33 tests in 5.271s

OK
```

The route-lab T1 baseline is
`docs/plans/2026-07-21-v1-baseline.txt` (71 lines including its start-SHA and
header). The current route-lab status has 22 entries and does not equal that
historical snapshot because concurrent work has legitimately changed or
cleaned many pre-existing paths. The exact comparison reported these two
current-only entries relative to T1:

```text
?? artifacts/nav-patches/
?? qw-nav-viewer/overlays/xersng-oracle-graph.json
BASELINE_COUNT=71 CURRENT_COUNT=22
```

Phase 4 never executed `graph_dump`, `demo_ingest`, or promotion against
route-lab: all mutating seams were mocked, and the suite only read the existing
canonical `fasttrack-graph.json`. Thus this task produced no route-lab
working-tree delta; exact equality to the old T1 snapshot is explicitly not
claimed under the concurrently evolving main worktree.

### Deviation and correction
The P3 spec text says overlay output should go to the isolated worktree. Phase
2 review established that this is not the directory consumed by the canonical
18089 sidecar and trunk proxy. The implementation therefore intentionally uses
`route-lab/qw-nav-viewer/overlays` as the single canonical data directory for
`graph_dump`, `demo_ingest`, `live_start`, `demo_replay_start`, and
`missing_spec`; `VIEWER_WORKTREE` remains only the isolated source/build tree.
This changes overlay data under route-lab main but does not change its source.

The first full suite run then failed because the recorded SNG fixture still
expected worktree link ID 50259. Inspection showed the same canonical graph
traversal (cell 942→684) is represented by IDs 38040 and 38041. The fixture was
updated to assert that canonical pair, after which all 33 tests passed. A
syntax typo in the newly edited MCP-count test was also surfaced by the first
focused invocation and corrected before the successful runs.

The post-commit two-axis review found three contract gaps and two documentation
gaps. They were corrected before handoff: ownership now accepts only exact
`inactive` unit status (so `activating`, bus errors, and unknown states abort);
promotion requires non-empty per-attempt elapsed/streak/delta rows plus valid
graph/patch/BSP SHA-256 and both cvar readbacks; cleanup and evidence use the
original total clock with reserved time. The actual test output and route-lab
T1/current comparison were added here, and `current-stage` now names the
canonical overlay exception instead of contradicting it. The unbounded
non-SIGALRM fallback was removed: unsupported runtimes fail closed before a
phase starts. The re-review then found that promotion overvalidated paired A/B
rows even though baseline and patched streak trials normally have different
attempt counts. Validation now accepts a missing side with `delta_s:null` while
still requiring elapsed/streak on every side that exists; the successful
promotion fixture includes this unpaired-row case.

### Confidence and next step
High for orchestration order, fail-closed ownership (including ambiguous unit
states), bundle/promotion checks,
and cleanup semantics at mocked seams. Real route performance is intentionally
unmeasured because the server was externally owned. Next: independent Claude
review of the Phase 4 commit, then a real proof run only after 27530 is free.
