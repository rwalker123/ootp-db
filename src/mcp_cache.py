"""File-based cache for MCP tool responses.

Cache file: PROJECT_ROOT/cache/mcp_cache.json
Key:        sha256(save_name + ":" + tool_name + ":" + sorted JSON args)
Entry:      { "result": str, "import_time": str }
Hit:        entry exists AND entry["import_time"] == current last_import
"""

import hashlib
import json
import tempfile
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "cache" / "mcp_cache.json"


def _cache_key(tool_name: str, args: dict, save_name: str) -> str:
    payload = save_name + ":" + tool_name + ":" + json.dumps(args, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def cache_get(tool_name: str, args: dict, save_name: str, import_time: str) -> str | None:
    """Return cached result string if valid, else None."""
    if not import_time:
        return None
    cache = _load_cache()
    key = _cache_key(tool_name, args, save_name)
    entry = cache.get(key)
    if entry and entry.get("import_time") == import_time:
        return entry["result"]
    return None


def cache_put(tool_name: str, args: dict, save_name: str, result: str, import_time: str) -> None:
    """Write a result to the cache."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cache = _load_cache()
    key = _cache_key(tool_name, args, save_name)
    cache[key] = {"result": result, "import_time": import_time}
    fd, tmp_path = tempfile.mkstemp(dir=CACHE_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(cache, indent=2))
        os.replace(tmp_path, CACHE_FILE)
    except Exception:
        os.unlink(tmp_path)
        raise
