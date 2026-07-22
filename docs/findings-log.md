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
