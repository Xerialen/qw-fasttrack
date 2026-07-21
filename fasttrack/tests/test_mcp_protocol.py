from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_server  # noqa: E402


class McpProtocolTests(unittest.TestCase):
    def test_tools_list_contains_v0_eleven_plus_live_pair(self):
        response = mcp_server.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(len(names), 16)
        self.assertEqual(set(names) - {"live_start", "live_stop", "demo_replay_start",
                                       "demo_replay_stop", "missing_spec"}, {
            "server_up", "server_down", "server_status", "maps_list", "ctl",
            "patch_apply", "patch_clear", "trial", "demo_ingest", "promote", "graph_dump",
        })


if __name__ == "__main__":
    unittest.main()
