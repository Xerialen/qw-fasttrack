# Current Stage

last-verified: 2026-07-22 (kväll)
status: active
maturity: stage-1-prototype

## ⭐ LÄS FÖRST om du är ny här

**Målacceptansen är GRÖN och hela lösningen är dokumenterad i
[docs/solutions/2026-07-22-dm3-under-lifts-to-sng.md](solutions/2026-07-22-dm3-under-lifts-to-sng.md)**
— tolv rotorsaker i fem lager (navmesh-data, exekutorn, tillståndsläckor,
verktygsbuggar, världens hissar), exakta commits/konstanter, evidensvägar,
reproduktionskommandon, samt pekaren till systerlösningen
**RA-tunnel→RA-topp** (route-lab spår 1, draft-PR qw-ctf/rtx#6). Börja där.

**Metoden som replikerbar runbook:**
[docs/runbooks/qwd-till-gron-rutt.md](runbooks/qwd-till-gron-rutt.md)
(qwd → referens → gap → kuraterad plantering → trial → telemetri →
regression → botkod). **Tar du över som nytt säte:** läs
[docs/plans/2026-07-23-seat-handoff-branches.md](plans/2026-07-23-seat-handoff-branches.md)
(exakt branchläge, live-läge, kvarvarande arbete, ägarbeslut).

## Current goal

Deliver Toolbox v2 in the approved phases. Phase 4 / P3 is locally implemented:
the rev-3 `gap_to_proof` workflow, promote v2 gate, and canonical overlay store.
**2026-07-22 kväll: mål-acceptansen (5 raka ≤3,82 s) UPPNÅDD — se ⭐ ovan.**

## Why this matters

It turns the demo-to-gap-to-patch chain into one owned, ordered A/B proof run
with bounded phases, cleanup on every exit, and SHA-bound promotion evidence.

## Next smallest useful step

Obtain the specified independent Claude review of the Phase 4 commit. After
acceptance, run the real owner-approved route proof only when port 27530 is free.

## Active constraints

- Keep library code map-agnostic; dm3 is allowed only in smoke/fixtures/docs.
- Do not modify bot/engine code or route-lab main source/code. The canonical
  main-tree overlay data directory is the explicit Phase 4 exception.
- Preserve the protected ports listed in the v1 plan.
- Viewer source work happens only on the isolated `viewer-live-fasttrack`
  worktree; overlay data lives canonically in route-lab main because that is
  the directory served by the 18089 sidecar/trunk proxy.

## Stop conditions

Stop if the documented graph/control contracts cannot be reconciled with live
behavior, or if an exact plan requirement would require touching a protected
port, route-lab main source/code, any main-tree path other than the explicitly
approved canonical overlay directory, or bot/engine code.

## Last known state

Phase 4 implementation is locally complete. `gap_to_proof` enforces inactive
server/live units before mutation, exact clean-baseline ordering, one patch
application, Trial v2 A/B, per-phase+total timeouts, and cleanup restart under
ordinary errors or cancellation. Partial manifests survive mid-run failures.
`promote` now verifies the bundle SHAs and patched streak. The WSL unit suite is
green (33 tests); all server/control behavior in Phase 4 tests is mocked, so the
externally owned server on 27530 was not started, stopped, or contacted.

## Required docs to update

`docs/findings-log.md`, `docs/testing-and-validation.md`, and `README.md` must
carry the implementation and verification evidence before completion.
