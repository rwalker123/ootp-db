"""Lineup optimizer domain package.

Public API (lazy-loaded to avoid heavy imports on package import):
  - generate_lineup_report
  - query_lineup
  - POS_STR_MAP  (re-exported from ootp_db_constants for server.py compatibility)
"""

_public = {
    "generate_lineup_report": ("report", "generate_lineup_report"),
    "query_lineup": ("queries", "query_lineup"),
}


def __getattr__(name):
    if name in _public:
        mod_name, attr = _public[name]
        import importlib
        mod = importlib.import_module(f".{mod_name}", package=__name__)
        return getattr(mod, attr)
    if name == "POS_STR_MAP":
        from ootp_db_constants import POS_STR_MAP
        return POS_STR_MAP
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["generate_lineup_report", "query_lineup", "POS_STR_MAP"]
