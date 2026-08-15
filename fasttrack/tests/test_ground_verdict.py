"""Spår A enhetssvit: GroundVerdict (cell-vid-xyz-domen).

Isolerad ur live-gap-verdicts ``test_link_attribution.py`` (pinnad 311c2df).
Dessa 9 tester bär GraphMatcher-kärnan: 32u-grid, off-grid vs missing,
residue vs steg, hylla-ovanför och pent-ledge utan fantomlänk. Körs
fristående utan graffil eller server:

    python3 -m unittest fasttrack.tests.test_ground_verdict
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from live_bridge import Attribution, GraphContract, GraphMatcher  # noqa: E402


class GroundVerdictTests(unittest.TestCase):
    """A 32u carve cannot place a cell against a wall; that is not a hole.

    Regression for the wall-hugging false positive: every step a player took
    along the pent ledge resolved to nothing and was stamped as missing ground,
    because the tolerance (24) was smaller than the distance to the last cell
    centre a 32u grid can offer (up to 32). The red layer then filled with
    ground the mesh represents perfectly well one square to the side.
    """

    def _matcher(self, cells):
        ids = list(range(10, 10 + len(cells)))
        return GraphMatcher(GraphContract(
            path=Path("fixture.json"), name="fixture", sha256="abc",
            cells=cells, links=[], cell_ids=ids, link_ids=[], links_by_cells={},
            cell_z_by_id={i: c[2] for i, c in zip(ids, cells, strict=True)},
            cell_by_id=dict(zip(ids, cells, strict=True)),
        ))

    def test_inside_a_cells_own_square_is_covered(self):
        matcher = self._matcher([[0, 0, 0], [0, 32, 0]])
        self.assertEqual(matcher.classify([4, 16, 0]), (10, GraphMatcher.COVERED))

    def test_ground_past_the_last_cell_row_is_off_grid_not_missing(self):
        # The row ends at y=0; y=32 would be inside a wall, so no rebuild can
        # cover y=27. The bot cannot stand there, but the ground is continuous.
        matcher = self._matcher([[0, 0, 0]])
        cell, verdict = matcher.classify([0, 27, 0])
        self.assertEqual(verdict, GraphMatcher.OFF_GRID)
        self.assertEqual(cell, 10)

    def test_ground_beyond_a_pitch_is_missing(self):
        matcher = self._matcher([[0, 0, 0]])
        self.assertEqual(matcher.classify([0, 40, 0]), (None, GraphMatcher.MISSING))

    def test_a_shelf_far_above_the_nearest_cell_stays_missing(self):
        # The dm3 SNG shelf: real ground 104u above the only cell beneath it.
        matcher = self._matcher([[0, 0, -16]])
        self.assertEqual(matcher.classify([0, 0, 88]), (None, GraphMatcher.MISSING))

    def test_a_shelf_just_off_to_the_side_is_missing_not_residue(self):
        # The band CELL_Z alone would swallow: a shelf a jump-height up and a
        # square across. Ground does not continue into the cell here, it steps
        # away from it, and a mesh that cannot represent it must say so.
        matcher = self._matcher([[0, 0, 0]])
        for dz in (12, 20, 32, 40):
            with self.subTest(dz=dz):
                self.assertEqual(matcher.classify([27, 0, dz]),
                                 (None, GraphMatcher.MISSING))

    def test_residue_is_only_the_same_plane_beside_a_cell(self):
        matcher = self._matcher([[0, 0, 0]])
        # A ramp's own slope across one square stays residue...
        self.assertEqual(matcher.classify([27, 0, 4])[1], GraphMatcher.OFF_GRID)
        # ...a step does not.
        self.assertEqual(matcher.classify([27, 0, 18])[1], GraphMatcher.MISSING)

    def test_a_cell_under_the_point_still_wins_over_residue_beside_it(self):
        # Standing inside a cell's own square, on a slope, must resolve to that
        # cell even though a flatter neighbour is nearer in plan.
        matcher = self._matcher([[0, 0, 0], [32, 0, 0]])
        cell, verdict = matcher.classify([2, 0, 30])
        self.assertEqual(verdict, GraphMatcher.COVERED)
        self.assertEqual(cell, 10)

    def test_walking_off_grid_beside_a_row_invents_no_missing_link(self):
        # The pent-ledge regression, end to end: the mesh row runs east at y=0,
        # the player walks the same plane at y=27 where no cell can exist. Every
        # step must attribute to the row it is beside -- not break the chain and
        # then report one long unlinked traversal across the whole ledge.
        cells = [[float(x), 0.0, 0.0] for x in (0, 32, 64, 96)]
        matcher = self._matcher(cells)
        graph = matcher.graph
        state = Attribution()
        for x in (0, 8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 96):
            cell, verdict = matcher.classify([float(x), 27.0, 0.0])
            self.assertEqual(verdict, GraphMatcher.OFF_GRID, f"x={x}")
            self.assertIsNotNone(cell, f"x={x}")
            state.observe(cell, 0.1 * x, graph)
        self.assertEqual(state.missing_links, [], "walking beside a row is not a gap")
        self.assertEqual(state.used_cells, {10, 11, 12, 13})

    def test_off_grid_ground_is_reported_apart_from_missing(self):
        state = Attribution()
        state.note_off_grid([0.0, 27.0, 0.0])
        payload = state.missing_payload()
        self.assertEqual(payload["cells"], [])
        self.assertEqual(payload["off_grid"], [[0.0, 27.0, 0.0]])


if __name__ == "__main__":
    unittest.main()
