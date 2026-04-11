"""Rotation analysis skill: optimal 5/6-man rotation, opener pairings, depth ranking.

Public names are loaded on first access so ``import rotation_analysis`` does not
pull in query or report submodules until actually needed.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "generate_rotation_report",
    "query_rotation",
]

_LAZY: dict[str, tuple[str, str]] = {
    "generate_rotation_report": ("report",  "generate_rotation_report"),
    "query_rotation":           ("queries", "query_rotation"),
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
