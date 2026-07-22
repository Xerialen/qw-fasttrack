# Current Stage

last-verified: 2026-07-22
status: active
maturity: stage-1-prototype

## Current goal

Deliver Toolbox v2 in the approved phases. Phase 3 / P1 now implements the
rev-3 hull-1 `bsp-probe` physics oracle in rex plus fail-closed Python glue in
qw-fasttrack.

## Why this matters

It makes the eventual demo-to-gap-to-patch proof chain measurable and keeps a
slow replay client or hash iteration order from corrupting that evidence.

## Next smallest useful step

Obtain the specified independent Claude review of the Phase 3 commits, then
begin Phase 4 / P3 only after this package is accepted.

## Active constraints

- Keep library code map-agnostic; dm3 is allowed only in smoke/fixtures/docs.
- Do not modify bot/engine code or route-lab's main worktree.
- Preserve the protected ports listed in the v1 plan.
- Viewer work happens only on the isolated `viewer-live-fasttrack` worktree.

## Stop conditions

Stop if the documented graph/control contracts cannot be reconciled with live
behavior, or if an exact plan requirement would require touching a protected
port, the route-lab main tree, or bot/engine code.

## Last known state

Phase 3 implementation is locally complete. Rex branch `bsp-probe` provides a
persistent JSONL hull-1 oracle pinned against the server's dm3 BSP. Python
ingest/missing/replay use it with structured whole-run fallback and flagged
mover-point fallback. The WSL unittest suite is green (24 tests); xersng oracle
ingest is 1.16 s and has 4 missing cells, all on z=40/56/120 surfaces.

## Required docs to update

`docs/findings-log.md`, `docs/testing-and-validation.md`, and `README.md` must
carry the implementation and verification evidence before completion.
