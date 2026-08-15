"""Enhetstest: graph_stamp (nivå 1) + graph_content_hash (nivå 2)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from stamp import canonical_inventory, graph_content_hash, graph_stamp  # noqa: E402

# Gyllene nivå 1 (T1h-era dm3-status: map=dm3, cells=5978, links=48208, rj=0)
LEVEL1_DM3 = 13090435456435551592
# Gyllene nivå 2 (dm3-dump, T-form, alla traversable=True):
# INTERIM — gäller nuvarande dump (48193 adjacenslänkar). Uppdateras när dumpen
# bär traversable-flagga på alla 48208 länkar.
LEVEL2_DM3_INTERIM = "ce143dc051cd035ed8981a52918d2b50586d0d64f7ca15ef1cf41e0ade1ae300"
# Gyllene nivå 2 (syntetisk minifixtur, T-form, båda traversable)
LEVEL2_TINY = "6d8af07e9580a26c19959861e21d295b95995d903fada013c4c4e54e142beeaf"
# Gyllene nivå 2 (minifixtur med EN rensad länk traversable=False)
LEVEL2_TINY_PRUNED = "6819c5bea29a4d690db502c8ef3186154dacb254548de82aa7a5ecd883a76c02"

TINY = {
    "cells": [[0, 0, 0], [32, 0, 0]],
    "cell_ids": [10, 11],
    "links": [
        {"from": 10, "to_cell": 11, "kind": "walk"},
        {"from": 11, "to_cell": 10, "kind": "walk"},
    ],
}


class GraphStampTests(unittest.TestCase):
    def test_level1_dm3_golden(self):
        self.assertEqual(graph_stamp("dm3", 5978, 48208, 0), LEVEL1_DM3)

    def test_level2_tiny_fixture_golden(self):
        self.assertEqual(graph_content_hash(TINY), LEVEL2_TINY)

    def test_level2_tiny_inventory_byteform(self):
        self.assertEqual(
            canonical_inventory(TINY).decode("utf-8"),
            "C\t10\t0\t0\t0\nC\t11\t32\t0\t0\n"
            "L\t10\t11\twalk\t1\nL\t11\t10\twalk\t1",
        )

    def test_level2_pruned_link_changes_hash(self):
        pruned = {
            "cells": [[0, 0, 0], [32, 0, 0]],
            "cell_ids": [10, 11],
            "links": [
                {"from": 10, "to_cell": 11, "kind": "walk", "traversable": True},
                {"from": 11, "to_cell": 10, "kind": "walk", "traversable": False},
            ],
        }
        self.assertEqual(graph_content_hash(pruned), LEVEL2_TINY_PRUNED)
        self.assertNotEqual(graph_content_hash(pruned), graph_content_hash(TINY))

    def test_level2_determinism(self):
        self.assertEqual(graph_content_hash(TINY), graph_content_hash(TINY))

    @unittest.skipUnless(
        (Path.home() / "lab" / "dm3-graph-current.json").is_file(),
        "dm3-dump saknas",
    )
    def test_level2_dm3_golden_interim(self):
        p = Path.home() / "lab" / "dm3-graph-current.json"
        doc = json.loads(p.read_bytes())
        self.assertEqual(graph_content_hash(doc), LEVEL2_DM3_INTERIM)


if __name__ == "__main__":
    unittest.main()
