"""Update import status in the saves registry.

Called by import.sh after all pipeline steps complete.

Usage:
    python src/update_status.py <save_name> ok
    python src/update_status.py <save_name> partial analytics ifa_ratings
    python src/update_status.py <save_name> failed import
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shared_css import get_saves_path, load_saves_registry  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print("Usage: update_status.py <save_name> <ok|partial|failed> [failed_step ...]")
        sys.exit(1)

    save_name = sys.argv[1]
    status = sys.argv[2]
    failed_steps = sys.argv[3:]

    registry = load_saves_registry()
    saves = registry.setdefault("saves", {})
    entry = saves.setdefault(save_name, {})

    entry["import_status"] = status
    entry["failed_steps"] = failed_steps

    if status == "ok":
        entry["last_successful_import"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    saves[save_name] = entry
    get_saves_path().write_text(json.dumps(registry, indent=2))


if __name__ == "__main__":
    main()
