"""Waiver wire claim evaluator: report generation and skill queries.

Public names are loaded on first access so ``import waiver_wire`` does not pull in
sqlalchemy-heavy submodules unless you use ``generate_waiver_claim_report`` or
``query_waiver_claim``.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "generate_waiver_claim_report",
    "query_waiver_claim",
]

_LAZY: dict[str, tuple[str, str]] = {
    "generate_waiver_claim_report": ("report", "generate_waiver_claim_report"),
    "query_waiver_claim": ("queries", "query_waiver_claim"),
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
