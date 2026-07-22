# Current Stage

last-verified: 2026-07-22
status: active
maturity: stage-1-prototype

## Current goal

Deliver Toolbox v2 in the approved phases. Phase 1 is Trial v2 plus the
Python side of P0 (playback coordinator, WebSocket robustness, and offline
determinism), governed by `docs/plans/2026-07-22-toolbox-v2.md` rev 3+.

## Why this matters

It makes the eventual demo-to-gap-to-patch proof chain measurable and keeps a
slow replay client or hash iteration order from corrupting that evidence.

## Next smallest useful step

Obtain the specified Claude review of the Phase 1 commit, then begin Phase 2
viewer work only after that package is accepted.

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

Phase 1 implementation is locally complete: Trial v2 measures received
positions at 15 Hz with streak evidence; replay has a single playback
coordinator and per-client latest-frame writers; offline timeline/spec output
is deterministically ordered. The WSL unittest suite is green (19 tests).

## Required docs to update

`docs/findings-log.md`, `docs/testing-and-validation.md`, and `README.md` must
carry the implementation and verification evidence before completion.
