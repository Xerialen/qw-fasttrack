"""Gyllene facit A — 1373-attribution (förseglat facit: WORK_LOGS/facit-verktygslada/facit-1373-attribution.md).

Acceptansen: det frusna 1373-ringsfallet ska attribueras till
SLÄPP-/LANDNINGSCELLEN 1376 [256, -608, -16] via Drop 1375->1376 — inte till
startcellen 1373 [256, -672, 328] (som enbart är kontext). Numeriskt link-id är
medvetet inte facit: länken identifieras som (kind=Drop, source=1375,
target=1376).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from live_bridge import Attribution, GraphContract, GraphMatcher  # noqa: E402


class Attribution1373Tests(unittest.TestCase):
    """ring-ned från 1373: Walk 20u norr till läpp 1375, sen Drop 344u ner i 1376."""

    def _graph(self) -> GraphContract:
        cells = [
            [256.0, -672.0, 328.0],   # 1373 start (bara Walk-ut)
            [256.0, -652.0, 328.0],   # 1375 läpp (Drop till z=-16)
            [256.0, -608.0, -16.0],   # 1376 landning
        ]
        cell_ids = [1373, 1375, 1376]
        links = [
            [0, 1, "Walk", 1.0],
            [1, 2, "Drop", 1.56],
        ]
        link_ids = [90001, 90002]
        return GraphContract(
            path=Path("fixture-1373.json"), name="fixture-1373", sha256="1373",
            cells=cells, links=links, cell_ids=cell_ids, link_ids=link_ids,
            links_by_cells={(1373, 1375): (90001,), (1375, 1376): (90002,)},
            cell_z_by_id={1373: 328.0, 1375: 328.0, 1376: -16.0},
            cell_by_id={
                1373: [256.0, -672.0, 328.0],
                1375: [256.0, -652.0, 328.0],
                1376: [256.0, -608.0, -16.0],
            },
        )

    def test_drop_attributes_landing_cell_not_start(self):
        graph = self._graph()
        matcher = GraphMatcher(graph)
        state = Attribution()
        # Fruset ring-ned-spår: 1373 -> 1375 -> [luft/fall 328->-16 = 344u] -> 1376.
        trace = [
            (0.00, [256.0, -672.0, 328.0], True),
            (0.20, [256.0, -652.0, 328.0], True),
            (0.40, [256.0, -640.0, 200.0], False),
            (1.56, [256.0, -608.0, -16.0], True),
        ]
        for now, pos, on_ground in trace:
            if not on_ground:
                continue
            cell, _ = matcher.classify(pos)
            self.assertIsNotNone(cell, pos)
            state.observe(cell, now, graph)

        # peak_drop_150-eventets attribution = landningscellen, inte startcellen.
        self.assertEqual(state.start_cell, 1373)               # kontext, ej attribution
        self.assertEqual(state.drop_landing_cell, 1376)        # SLÄPP-/LANDNINGSCELL
        self.assertEqual(graph.cell_by_id[1376], [256.0, -608.0, -16.0])
        self.assertNotEqual(state.drop_landing_cell, 1373)     # aldrig startcellen
        self.assertEqual(state.drop_from_cell, 1375)           # läppen
        # Länken resolvas till (Drop, 1375 -> 1376), ej numeriskt facit.
        self.assertIsNotNone(state.drop_link_id)
        idx = graph.link_ids.index(state.drop_link_id)
        self.assertEqual(str(graph.links[idx][2]).lower(), "drop")
        self.assertEqual(graph.cell_ids[int(graph.links[idx][0])], 1375)
        self.assertEqual(graph.cell_ids[int(graph.links[idx][1])], 1376)


if __name__ == "__main__":
    unittest.main()
