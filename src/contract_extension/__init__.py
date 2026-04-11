"""Contract extension advisor: report generation and skill queries.

Public names are loaded on first access so ``import contract_extension`` does not
pull in submodules until actually needed.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "generate_contract_extension_report",
    "query_contract_extension",
]

_LAZY: dict[str, tuple[str, str]] = {
    "generate_contract_extension_report": ("report",  "generate_contract_extension_report"),
    "query_contract_extension":           ("queries", "query_contract_extension"),
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
