"""Bygg HTML som hostar map-template.html med PROPOSAL_DATA."""
from __future__ import annotations

from pathlib import Path

from .convert import json_literal

WRAPPER = """<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8">
<title>obducera heatmap — stallkarta</title>
<style>
  html,body{margin:0;height:100%;background:#0c0b0a}
  iframe{border:0;width:100%;height:100%;display:block}
</style>
</head>
<body>
<script>
window.PROPOSAL_DATA = {
  graph: /*__GRAPH__*/,
  entities: /*__ENTS__*/,
  snapshots: /*__SNAPSHOTS__*/,
  linkgeo: /*__LINKGEO__*/
};
</script>
<iframe id="mv" title="stallkarta"></iframe>
<script>
document.getElementById("mv").srcdoc = /*__MAP_VIEW__*/;
</script>
</body>
</html>
"""


def render_html(proposal: dict, map_template: str) -> str:
    repl = {
        "/*__GRAPH__*/": json_literal(proposal["graph"]),
        "/*__ENTS__*/": json_literal(proposal["entities"]),
        "/*__SNAPSHOTS__*/": json_literal(proposal["snapshots"]),
        "/*__LINKGEO__*/": json_literal(proposal["linkgeo"]),
        "/*__MAP_VIEW__*/": json_literal(map_template),
    }
    html = WRAPPER
    for marker, val in repl.items():
        html = html.replace(marker, val)
    leftover = [m for m in repl if m in html]
    if leftover:
        raise RuntimeError("unreplaced markers: " + ", ".join(leftover))
    return html


def default_map_template() -> Path:
    return Path.home() / "rtx-cost-exp/testsuite/dashboard/map-template.html"


def default_map_dir() -> Path:
    return Path.home() / "rtx-cost-exp/testsuite/dashboard/assets/maps/dm3"
