# Current Stage

last-verified: 2026-07-21
status: active
maturity: stage-1-prototype

## Current goal

Build fasttrack v1 live-viewer: show the bot moving on the map and navmesh in
real time, with the navmesh elements used by the current attempt clearly
highlighted. The implementation contract is
`docs/plans/2026-07-21-v1-live-viewer.md`, including its final rev-3 rulings.

## Why this matters

It closes the movement-lab feedback loop: an owner can run a trial and inspect
the bot, active cell, and attributed links in one live browser view.

## Next smallest useful step

Complete T0-T6 in the v1 plan and preserve terminal and reviewer evidence.

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

The v0 server/control/MCP prototype exists. The live bridge, live viewer layer,
and lifecycle tools are not yet implemented.

## Required docs to update

`docs/findings-log.md`, `docs/testing-and-validation.md`, and `README.md` must
carry the implementation and verification evidence before completion.
