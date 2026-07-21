# Success Criteria

The binding criteria are the seven items under **Globala success-kriterier** in
`docs/plans/2026-07-21-v1-live-viewer.md`, as overridden by **Skiljedom varv 2
(rev 3)**. In short:

1. `fasttrack/smoke_live.py` exits 0 and prints `LIVE-SMOKE: OK`.
2. Measured p95 for status RTT + bridge tick + WebSocket send is below 200 ms.
3. Reviewer screenshots prove hot used-cell/link rendering and follow mode.
4. Reviewer comparison proves the no-`live` view is visually unchanged.
5. route-lab main-tree status exactly matches the captured T1 baseline.
6. Library code remains map-agnostic and bot/engine code remains untouched.
7. With the bridge down, all 11 v0 MCP tools remain listed and direct
   `server_status` plus one trial still work.

Rev-3 also requires the graph fingerprint/spot-check guard, terminal-event
ownership, global SID routing, nonce health check, graph-dump interlock, and
hard-kill stale-state fallback described in S1-S5.
