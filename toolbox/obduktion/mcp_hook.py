"""MCP-registrering för obducera (read-only). Importeras från mcp_server."""
from __future__ import annotations

from .dump import dumps
from .pipeline import obducera


def call(args: dict) -> str:
    doc = obducera(
        args["serie"],
        arm=args.get("arm") or "AB",
        regim=args.get("regim") or "kedjad",
        stamplar=args.get("stamplar"),
        ent=int(args["ent"]) if args.get("ent") is not None else 1,
    )
    return dumps(doc)


TOOL = {
    "desc": "Read-only autopsy: JSONL series → classified events → "
            "clustered prioritized action list. Byte-identical JSON to "
            "scripts/obducera.py. Never touches the live rig.",
    "schema": {"serie": "string", "arm": "string", "regim": "string",
               "stamplar": "string", "ent": "integer"},
    "required": ["serie"],
    "canonical": True,
    "fn": call,
}
