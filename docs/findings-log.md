# Findings Log

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
