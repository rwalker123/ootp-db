"""Update import status in the saves registry.

Called by import.sh after all pipeline steps complete.

Usage:
    python src/update_status.py <save_name> ok
    python src/update_status.py <save_name> partial analytics ifa_ratings
    python src/update_status.py <save_name> failed import

If <project_root>/pipeline_warnings.json exists and contains a non-empty "warnings" list,
import_status becomes "warning" instead of "ok" (still sets last_successful_import).
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shared_css import get_saves_path, load_saves_registry  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WARNING_PATH = PROJECT_ROOT / "pipeline_warnings.json"


def _load_pipeline_warnings() -> list[str]:
    if not WARNING_PATH.is_file():
        return []
    try:
        raw = json.loads(WARNING_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    w = raw.get("warnings") if isinstance(raw, dict) else None
    if not isinstance(w, list):
        return []
    return [str(x) for x in w if x]


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: update_status.py <save_name> <ok|partial|failed> [failed_step ...]"
        )
        sys.exit(1)

    save_name = sys.argv[1]
    status = sys.argv[2]
    failed_steps = sys.argv[3:]

    registry = load_saves_registry()
    saves = registry.setdefault("saves", {})
    entry = saves.setdefault(save_name, {})

    warnings = _load_pipeline_warnings()
    entry["import_warnings"] = warnings

    if status == "ok":
        entry["last_successful_import"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if warnings:
            status = "warning"
        entry["failed_steps"] = []
    elif status == "partial":
        entry["failed_steps"] = failed_steps
    else:
        entry["failed_steps"] = failed_steps

    entry["import_status"] = status

    saves[save_name] = entry
    get_saves_path().write_text(json.dumps(registry, indent=2))


if __name__ == "__main__":
    main()
