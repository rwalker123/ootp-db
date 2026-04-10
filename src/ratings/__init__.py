"""Player rating system: batch `player_ratings` table, reports, and skill queries.

Public names are loaded on first access so ``import ratings`` does not pull in
pandas-heavy ``compute`` unless you use ``compute_*`` or ``main``.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "classify_batter_archetype",
    "compute_batter_ratings",
    "compute_pitcher_ratings",
    "fetch_career_trend_stats",
    "find_existing_rating_report",
    "generate_rating_report",
    "get_last_import_time",
    "letter_grade",
    "main",
    "query_player_rating",
]

_LAZY: dict[str, tuple[str, str]] = {
    "classify_batter_archetype": ("queries", "classify_batter_archetype"),
    "query_player_rating": ("queries", "query_player_rating"),
    "fetch_career_trend_stats": ("queries", "fetch_career_trend_stats"),
    "letter_grade": ("grades", "letter_grade"),
    "find_existing_rating_report": ("report", "find_existing_rating_report"),
    "get_last_import_time": ("report", "get_last_import_time"),
    "generate_rating_report": ("report", "generate_rating_report"),
    "compute_batter_ratings": ("compute", "compute_batter_ratings"),
    "compute_pitcher_ratings": ("compute", "compute_pitcher_ratings"),
    "main": ("compute", "main"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        submod, attr = _LAZY[name]
        module = importlib.import_module(f".{submod}", __name__)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__))
