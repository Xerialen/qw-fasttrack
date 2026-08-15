"""Gyllene facit A — 1373-attribution (facit förseglat av terra).

Acceptansen: det frusna 1373-ringsfallet ska attribueras till
SLÄPP-/LANDNINGSCELLEN 1376 [256, -608, -16] via Drop 1375->1376 — inte till
startcellen 1373 [256, -672, 328] (enbart kontext). Länken identifieras som
(kind=Drop, source=1375, target=1376), aldrig numeriskt link-id.

Fables ytbeslut: attributionsytan är landningscellen oavsett länk-kind, satt
via landnings-xyz-resolution — även vid kind!=Drop eller classify=MISSING.
last_cell-semantiken är orörd (GroundVerdict får inte riskeras).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from live_bridge import Attribution, GraphContract, GraphMatcher  # noqa: E402


class Attribution1373Tests(unittest.TestCase):
    """ring-ned 1373: Walk 20u norr till läpp 1375, sen fall 344u ner i 1376."""

    def _graph(self, *, drop: bool = True) -> GraphContract:
        cells = [
            [256.0, -672.0, 328.0],   # 1373 start (bara Walk-ut)
            [256.0, -652.0, 328.0],   # 1375 läpp
            [256.0, -608.0, -16.0],   # 1376 landning
        ]
        cell_ids = [1373, 1375, 1376]
        if drop:
            links = [[0, 1, "Walk", 1.0], [1, 2, "Drop", 1.56]]
            link_ids = [90001, 90002]
            by_cells = {(1373, 1375): (90001,), (1375, 1376): (90002,)}
        else:
            # kind != Drop: en Jump-länk 1375->1376 (fuzzy_links kräver ej att
            # den är en Drop — landningscellen ska ändå attribueras via xyz).
            links = [[0, 1, "Walk", 1.0], [1, 2, "Jump", 1.56]]
            link_ids = [90001, 90003]
            by_cells = {(1373, 1375): (90001,), (1375, 1376): (90003,)}
        return GraphContract(
            path=Path("fixture-1373.json"), name="fixture-1373", sha256="1373",
            cells=cells, links=links, cell_ids=cell_ids, link_ids=link_ids,
            links_by_cells=by_cells,
            cell_z_by_id={1373: 328.0, 1375: 328.0, 1376: -16.0},
            cell_by_id={
                1373: [256.0, -672.0, 328.0],
                1375: [256.0, -652.0, 328.0],
                1376: [256.0, -608.0, -16.0],
            },
        )

    def _ground(self, state, matcher, graph, pos, now):
        cell, _ = matcher.classify(pos)
        if cell is None:
            state.note_missing_landing(pos)
        else:
            state.observe(cell, now, graph)

    def test_air_landing_attributes_landing_cell_not_start(self):
        graph = self._graph(drop=True)
        matcher = GraphMatcher(graph)
        state = Attribution()
        self._ground(state, matcher, graph, [256.0, -672.0, 328.0], 0.00)  # 1373
        self._ground(state, matcher, graph, [256.0, -652.0, 328.0], 0.20)  # 1375
        state.note_airborne()
        # Predikterat fel (GAMLA ytan): under luften rapporterar last_cell
        # läppen 1375, inte landningscellen 1376. Det var hela attributionsytan
        # före denna fix.
        self.assertEqual(state.last_cell, 1375)
        self._ground(state, matcher, graph, [256.0, -608.0, -16.0], 1.56)  # 1376

        self.assertEqual(state.start_cell, 1373)               # kontext
        self.assertEqual(state.drop_landing_cell, 1376)        # NY yta: landningscell
        self.assertEqual(graph.cell_by_id[1376], [256.0, -608.0, -16.0])
        self.assertNotEqual(state.drop_landing_cell, 1373)     # aldrig startcellen
        self.assertEqual(state.drop_from_cell, 1375)           # läppen
        self.assertIsNotNone(state.drop_link_id)
        idx = graph.link_ids.index(state.drop_link_id)
        self.assertEqual(graph.link_kind(state.drop_link_id).lower(), "drop")
        self.assertEqual(graph.cell_ids[int(graph.links[idx][0])], 1375)
        self.assertEqual(graph.cell_ids[int(graph.links[idx][1])], 1376)

    def test_landing_attributed_even_when_kind_is_not_drop(self):
        graph = self._graph(drop=False)
        matcher = GraphMatcher(graph)
        state = Attribution()
        self._ground(state, matcher, graph, [256.0, -672.0, 328.0], 0.00)
        self._ground(state, matcher, graph, [256.0, -652.0, 328.0], 0.20)
        state.note_airborne()
        self._ground(state, matcher, graph, [256.0, -608.0, -16.0], 1.56)
        # Landningscellen attribueras oavsett att länken är Jump, inte Drop.
        self.assertEqual(state.drop_landing_cell, 1376)
        self.assertEqual(state.drop_from_cell, 1375)
        self.assertIsNotNone(state.drop_link_id)
        self.assertEqual(graph.link_kind(state.drop_link_id).lower(), "jump")

    def test_missing_landing_records_xyz_and_unknown_cell(self):
        graph = self._graph(drop=True)
        matcher = GraphMatcher(graph)
        state = Attribution()
        self._ground(state, matcher, graph, [256.0, -672.0, 328.0], 0.00)
        self._ground(state, matcher, graph, [256.0, -652.0, 328.0], 0.20)
        state.note_airborne()
        # Landning mot vägg ~z=128: classify = MISSING (grok2:s västläge).
        self._ground(state, matcher, graph, [256.0, -608.0, 128.0], 1.56)
        # Ingen cell att attribuera, men läppen och landnings-xyz är sparade.
        self.assertIsNone(state.drop_landing_cell)
        self.assertEqual(state.drop_from_cell, 1375)
        payload = state.missing_payload()
        self.assertIn([256.0, -608.0, 128.0], payload["cells"])


if __name__ == "__main__":
    unittest.main()
