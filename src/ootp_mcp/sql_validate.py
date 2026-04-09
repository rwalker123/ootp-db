"""Validate read-only SQL for MCP ootp_run_sql (defense in depth; DB is already read-only)."""

from __future__ import annotations

import re

# Default max rows returned to the model (tool result size / context control).
DEFAULT_MAX_ROWS = 500

_FORBIDDEN_START = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|VACUUM|ATTACH|DETACH|PRAGMA|COPY|GRANT|REVOKE|CALL)\b",
    re.IGNORECASE | re.DOTALL,
)


def validate_readonly_sql(sql: str) -> str:
    """Return normalized single-statement SQL or raise ValueError."""
    if not sql or not sql.strip():
        raise ValueError("SQL is empty")

    parts = [p.strip() for p in sql.split(";") if p.strip()]
    if len(parts) != 1:
        raise ValueError("Only a single SQL statement is allowed (no multiple statements).")

    stmt = parts[0].strip()

    if _FORBIDDEN_START.search(stmt):
        raise ValueError("Only SELECT (or WITH ... SELECT) is allowed.")

    head = stmt.lstrip()
    upper = head[:32].upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise ValueError("Statement must begin with SELECT or WITH.")

    return stmt


def clamp_limit_in_sql(sql: str, max_rows: int) -> str:
    """If there is no LIMIT clause, append LIMIT max_rows."""
    if max_rows < 1:
        return sql
    if re.search(r"\blimit\s+\d", sql, re.IGNORECASE):
        return sql
    return f"{sql.rstrip()} LIMIT {int(max_rows)}"
