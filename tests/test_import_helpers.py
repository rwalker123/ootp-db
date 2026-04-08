"""Tests for OOTP version detection and schema diff helpers in src/import.py."""

import importlib.util
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_IMP_PATH = _SRC / "import.py"


def _load_importer():
    sys.path.insert(0, str(_SRC))
    spec = importlib.util.spec_from_file_location("ootp_importer", _IMP_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_imp = _load_importer()


class TestDetectOotpVersion(unittest.TestCase):
    def test_mac_style_folder_name(self):
        p = Path("/Users/x/Library/Containers/com.ootpdevelopments.ootp27macqlm/Data/Application Support/Out of the Park Developments/OOTP Baseball 27/saved_games/MySave.lg")
        self.assertEqual(_imp.detect_ootp_version(p), 27)

    def test_steam_style_folder_name(self):
        p = Path("C:/Program Files (x86)/Steam/steamapps/common/Out of the Park Baseball 27/saved_games/Foo.lg")
        self.assertEqual(_imp.detect_ootp_version(p), 27)

    def test_no_version_in_path(self):
        p = Path("/tmp/manual_copy/MySave.lg")
        self.assertIsNone(_imp.detect_ootp_version(p))


class TestDiffSchemas(unittest.TestCase):
    def test_new_and_removed_tables(self):
        prev = dict(players=["a", "b"])
        cur = dict(players=["a", "b"], teams=["x"])
        d = _imp.diff_schemas(prev, cur)
        self.assertEqual(d["new_tables"], ["teams"])
        self.assertEqual(d["removed_tables"], [])

    def test_column_add_remove(self):
        prev = dict(players=["id", "old_col"])
        cur = dict(players=["id", "new_col"])
        d = _imp.diff_schemas(prev, cur)
        self.assertEqual(d["table_column_changes"]["players"]["new_columns"], ["new_col"])
        self.assertEqual(
            d["table_column_changes"]["players"]["removed_columns"], ["old_col"]
        )

    def test_no_changes(self):
        prev = dict(t=["x", "y"])
        cur = dict(t=["x", "y"])
        d = _imp.diff_schemas(prev, cur)
        self.assertEqual(d["new_tables"], [])
        self.assertEqual(d["removed_tables"], [])
        self.assertEqual(d["table_column_changes"], {})


if __name__ == "__main__":
    unittest.main()
