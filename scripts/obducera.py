#!/usr/bin/env python3
"""obducera --serie <dir>  — spår I, samma JSON som MCP-verktyget obducera."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from toolbox.obduktion.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
