# Testing and Validation

The v1 contract is `docs/plans/2026-07-21-v1-live-viewer.md`.

## Automated checks

- Viewer: contained WSL `cargo test --workspace -- --test-threads=8`, including
  parser fixtures for valid IDs, mismatch, duplicates, and kind normalization.
- Bridge: WSL unit tests for recorded SNG link attribution and two-client proxy
  SID/event/disconnect behavior.
- MCP: stdio protocol test proving 13 tools after v1, then 11 v0 tools when
  evaluating the compatibility subset.
- End to end: contained WSL `fasttrack/smoke_live.py`; it boots dm3, plants the
  proven SNG fixture, runs three proxied trials while reading WebSocket frames,
  checks graph-dump blocking, reports p50/p95 latency, tests hard-kill fallback,
  and always tears down through `finally`.
- Static guards: no forbidden ports; no `dm3` literals in changed library code;
  no overlay dumps in the viewer commit; route-lab main status equals baseline.

## Fixture provenance

The attribution fixture is a recorded status/cell sequence from the real dm3
SNG jump used by `fasttrack/smoke.py`. Coordinates and dm3 naming are permitted
in fixtures and smoke tests, never in library code.

## Visual reviewer checklist

Visual verification is assigned to the independent reviewer, not the
implementer. With server, bridge, and viewer left running, the reviewer records:

1. 8088 versus 8090 static `?graph=fasttrack` baseline comparison.
2. Live bot mid-jump with active/used cell and hot used link visible.
3. Follow mode toggled with the documented free key.
4. Static 8090 view without `?live`, compared against the baseline.

The final implementation report supplies exact URLs and commands for this pass.

## Grounded-apex regression (2026-07-22)

Focused unit coverage lives in `fasttrack/tests/test_demo_mesh_grounded.py` and
`test_link_attribution.py`:

- 72/77/144 Hz QW parabolas preserve both plateau boundary samples while
  rejecting every airborne sample;
- the recorded eighth-unit QWD apex cap rejects the false stable side whose
  endpoints return to z=99.0;
- a final airborne sample cannot borrow the stable landing plateau when its
  adjacent vertical step is still at least 0.25u;
- an isolated sample is not ground;
- three constant-z unresolved ticks stamp missing ground, while the measured
  ballistic delta sequence cannot reach the threshold.

Real-data validation uses `/mnt/c/nQuake/qw/matchinfo/demos/xersng.qwd` and the
fasttrack graph. `missing_spec` now emits 4 missing cells (down from 38), at
z=40/56/120 only (`cells_required=182`). Every output point has a graph cell on exactly the same z
within 64u XY; the >40u hover-violation count is zero. The replay's direct
sample-level dedup reports 9 cells (down from 42), likewise all on surfaces.

Visual evidence is
`docs/evidence/2026-07-22-grounded-apex-surfaces.png`, captured in a real
headed WebGPU browser from
`http://127.0.0.1:8090/?graph=fasttrack&live=8096`. The replay service remains
active as `fasttrack-replay-final` at speed 8, no loop.
