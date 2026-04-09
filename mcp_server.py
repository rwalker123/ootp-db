#!/usr/bin/env python3
"""Launch the OOTP MCP server (stdio). Run from the project root so `.env` resolves."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from ootp_mcp.server import main

if __name__ == "__main__":
    main()
