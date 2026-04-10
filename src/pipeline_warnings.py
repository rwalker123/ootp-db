"""Accumulate human-readable pipeline warnings for import + analytics.

Written to <project_root>/pipeline_warnings.json for update_status.py and the UI.
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WARNING_PATH = PROJECT_ROOT / "pipeline_warnings.json"


def reset_pipeline_warnings() -> None:
    WARNING_PATH.write_text(json.dumps(dict(warnings=[]), indent=2))


def add_pipeline_warnings(msgs: list[str]) -> None:
    data = dict(warnings=[])
    if WARNING_PATH.exists():
        try:
            raw = json.loads(WARNING_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("warnings"), list):
                data = raw
        except (json.JSONDecodeError, OSError):
            pass
    w = data.setdefault("warnings", [])
    for m in msgs:
        if m and m not in w:
            w.append(m)
    try:
        WARNING_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
