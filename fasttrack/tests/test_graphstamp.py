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
# Gyllene nivå 2 (dm3-dump: 5978 celler + 48193 länkar i arrayen)
LEVEL2_DM3 = "680b540a642e90cdd9eac76debd35af687ff918e7b1b5f6583e5cf34f4759ec0"
# Gyllene nivå 2 (syntetisk minifixtur, självständig utan dump)
LEVEL2_TINY = "1dbb72548adce39a7f54a0b2e91261c9275fdc13f40037148e8c9c04f2816f9b"

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
            "L\t10\t11\twalk\nL\t11\t10\twalk",
        )

    def test_level2_determinism(self):
        self.assertEqual(graph_content_hash(TINY), graph_content_hash(TINY))

    @unittest.skipUnless(
        (Path.home() / "lab" / "dm3-graph-current.json").is_file(),
        "dm3-dump saknas",
    )
    def test_level2_dm3_golden(self):
        p = Path.home() / "lab" / "dm3-graph-current.json"
        doc = json.loads(p.read_bytes())
        self.assertEqual(graph_content_hash(doc), LEVEL2_DM3)


if __name__ == "__main__":
    unittest.main()
