# Current Stage

last-verified: 2026-07-22
status: active
maturity: stage-1-prototype

## Current goal

Eliminate false airborne missing-ground glyphs from both offline QWD replay
and the live bridge without losing real surface contacts. The implementation
contract and measured correction are in
`docs/plans/2026-07-22-grounded-apex-artifacts.md`.

## Why this matters

It closes the movement-lab feedback loop: an owner can run a trial and inspect
the bot, active cell, and attributed links in one live browser view.

## Next smallest useful step

Obtain independent review of the grounded-apex fix and its regenerated
`dm3-xersng-full-missing-spec.json` evidence.

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

Fasttrack v1 is implemented at `b4df138`: live bridge, viewer layer, demo
replay, missing layer, and spec export exist. The grounded-apex candidate
removes every measured xersng airborne cell glyph; the final replay has nine
surface-level missing cells rather than 42 floating/ground-mixed cells.

## Required docs to update

`docs/findings-log.md`, `docs/testing-and-validation.md`, and `README.md` must
carry the implementation and verification evidence before completion.
