"""python -m ootp_mcp — requires PYTHONPATH=src or run mcp_server.py from repo root."""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ootp_mcp.server import main

if __name__ == "__main__":
    main()
