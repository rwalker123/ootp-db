"""Accumulate human-readable pipeline warnings for import + analytics.

One JSON file per save (derived DB name) under <project_root>/pipeline_warnings/
for update_status.py and the UI. Writes use a temp file + os.replace; on POSIX,
an exclusive flock on a sibling .lock file avoids concurrent clobbering for the
same save and prevents torn writes from cooperating processes.
"""

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from shared_css import db_name_from_save

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WARNING_DIR = PROJECT_ROOT / "pipeline_warnings"


def warnings_json_path(save_name: str) -> Path:
    """Filesystem path for this save's accumulated warnings JSON."""
    return WARNING_DIR / f"{db_name_from_save(save_name)}.json"


def _lock_path(json_path: Path) -> Path:
    return json_path.with_name(json_path.name + ".lock")


@contextmanager
def _exclusive_file_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    f = open(lock_path, "a+", encoding="utf-8")
    try:
        if sys.platform != "win32":
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if sys.platform != "win32":
            import fcntl

            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        f.close()


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
            tmp_f.write(payload)
            tmp_f.flush()
            os.fsync(tmp_f.fileno())
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_pipeline_warnings(save_name: str) -> list[str]:
    path = warnings_json_path(save_name)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    w = raw.get("warnings") if isinstance(raw, dict) else None
    if not isinstance(w, list):
        return []
    return [str(x) for x in w if x]


def reset_pipeline_warnings(save_name: str) -> None:
    path = warnings_json_path(save_name)
    try:
        with _exclusive_file_lock(_lock_path(path)):
            _atomic_write_json(path, dict(warnings=[]))
    except OSError:
        pass


def add_pipeline_warnings(save_name: str, msgs: list[str]) -> None:
    path = warnings_json_path(save_name)
    try:
        with _exclusive_file_lock(_lock_path(path)):
            data: dict = dict(warnings=[])
            if path.is_file():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and isinstance(raw.get("warnings"), list):
                        data = raw
                except (json.JSONDecodeError, OSError):
                    pass
            w = data.setdefault("warnings", [])
            for m in msgs:
                if m and m not in w:
                    w.append(m)
            _atomic_write_json(path, data)
    except OSError:
        pass
