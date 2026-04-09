"""Validate read-only SQL for MCP ootp_run_sql (defense in depth; DB is already read-only)."""

from __future__ import annotations

import re

# Default max rows returned to the model (tool result size / context control).
DEFAULT_MAX_ROWS = 500

_FORBIDDEN_START = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|VACUUM|ATTACH|DETACH|PRAGMA|COPY|GRANT|REVOKE|CALL)\b",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN_ANYWHERE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|VACUUM|ATTACH|DETACH|PRAGMA|COPY|GRANT|REVOKE|CALL)\b",
    re.IGNORECASE | re.DOTALL,
)


def _split_single_statement(sql: str) -> str:
    """Return single statement body while ignoring ; inside strings/comments."""
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    statement_breaks = 0
    first_break_idx = -1

    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            if ch == "'" and nxt == "'":
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == ";":
            statement_breaks += 1
            if first_break_idx == -1:
                first_break_idx = i
        i += 1

    if statement_breaks == 0:
        return sql.strip()

    head = sql[:first_break_idx].strip()
    tail = sql[first_break_idx + 1 :].strip()
    if tail:
        raise ValueError("Only a single SQL statement is allowed (no multiple statements).")
    return head


def _mask_sql_strings_and_comments(sql: str) -> str:
    """Replace comment and string literal bodies with spaces; same length as sql for index-safe search."""
    out: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            out.append("\n" if ch == "\n" else " ")
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            out.append(" ")
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            out.append(" ")
            if ch == "'" and nxt == "'":
                out.append(" ")
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            out.append(" ")
            if ch == '"' and nxt == '"':
                out.append(" ")
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            out.append(" ")
            out.append(" ")
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            out.append(" ")
            out.append(" ")
            i += 2
            continue
        if ch == "'":
            in_single = True
            out.append("'")
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append('"')
            i += 1
            continue
        out.append(ch)
        i += 1

    return "".join(out)


def validate_readonly_sql(sql: str) -> str:
    """Return normalized single-statement SQL or raise ValueError."""
    if not sql or not sql.strip():
        raise ValueError("SQL is empty")

    stmt = _split_single_statement(sql)

    if _FORBIDDEN_START.search(stmt):
        raise ValueError("Only SELECT (or WITH ... SELECT) is allowed.")

    head = stmt.lstrip()
    upper = head[:32].upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise ValueError("Statement must begin with SELECT or WITH.")

    # Defense in depth: block writable CTEs like
    # WITH x AS (DELETE ... RETURNING ...) SELECT ...
    if _FORBIDDEN_ANYWHERE.search(_mask_sql_strings_and_comments(stmt)):
        raise ValueError("Read-only query required: writable/DDL keywords are not allowed.")

    return stmt


def clamp_limit_in_sql(sql: str, max_rows: int) -> str:
    """If there is no LIMIT clause, append LIMIT max_rows.

    - Inserts LIMIT before a trailing OFFSET clause when needed: SQLite requires LIMIT
      before OFFSET; appending LIMIT after OFFSET is a syntax error there.
    - Appends LIMIT on its own line so a trailing SQL line comment cannot swallow it.
    """
    if max_rows < 1:
        return sql
    if re.search(r"\blimit\s+\d", sql, re.IGNORECASE):
        return sql
    cap = int(max_rows)
    s = sql.rstrip()
    masked = _mask_sql_strings_and_comments(s)
    m = re.search(r"(?is)\boffset\s+.+$", masked)
    if m:
        prefix = s[: m.start()].rstrip()
        suffix = s[m.start() :].lstrip()
        return f"{prefix}\nLIMIT {cap} {suffix}"
    return f"{s}\nLIMIT {cap}"
