"""FastMCP server: read-only OOTP DB tools + schema resources."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from sqlalchemy import inspect, text

_SRC = Path(__file__).resolve().parent.parent
_ROOT = _SRC.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mcp.server.fastmcp import FastMCP

from ootp_db_constants import MLB_LEAGUE_ID
from ootp_mcp.sql_validate import DEFAULT_MAX_ROWS, clamp_limit_in_sql, validate_readonly_sql
from shared_css import db_name_from_save, get_engine, load_saves_registry


_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$", re.IGNORECASE)

mcp = FastMCP(
    "ootp-db",
    instructions=(
        "OOTP Baseball database (read-only). Use ootp_list_saves first if unsure of the save name. "
        "Read ootp://query-conventions for MLB filters and table conventions. "
        "Use ootp_list_tables / ootp_describe_table before guessing column names."
    ),
)


def _resolve_save_name(save_name: str | None) -> str:
    reg = load_saves_registry()
    if save_name and str(save_name).strip():
        s = str(save_name).strip()
        if s not in reg.get("saves", {}):
            raise ValueError(f"Unknown save_name: {s!r} (not in saves registry)")
        return s
    active = reg.get("active")
    if not active:
        raise ValueError(
            "No save_name given and no active save in registry — import a save or set active."
        )
    return active


def _validate_table_name(table: str) -> str:
    t = table.strip()
    if not _TABLE_NAME_RE.match(t):
        raise ValueError(
            "Invalid table name: use letters, digits, underscore only (typical OOTP table names)."
        )
    return t


@mcp.resource("ootp://query-conventions", mime_type="text/markdown")
def resource_query_conventions() -> str:
    """High-level query rules so the model does not invent columns or wrong leagues."""
    return f"""# OOTP DB query conventions (read-only)

- **MLB-only unless asked otherwise:** filter with `league_id = {MLB_LEAGUE_ID}` on league-scoped tables (see `ootp_db_constants.MLB_LEAGUE_ID`).
- **Ratings:** prefer composite **`player_ratings`** (`rating_overall`, etc.) for rankings — not raw `players_value.oa_rating` alone.
- **Contracts:** salary columns are **`salary0`..`salary14`** — there is no bare `salary` column. Length is **`years`**; **`current_year`** indexes the active salary column.
- **Career `split_id` (table-specific — do not mix conventions):**
  - **`players_career_batting_stats` / `players_career_pitching_stats`:** `split_id = 1` = overall regular season (real + sim). **`split_id = 0` does not appear.** Use `1` for career totals; `2`/`3` = vs L/R; `21` = postseason when present.
  - **`players_career_fielding_stats`:** OOTP uses **both** `split_id = 0` and `1` as disjoint era buckets (historical vs sim-era rows; year bands vary by save). For **all-time** fielding games/totals spanning both, use **`split_id IN (0, 1)`** — `1` alone can omit sim seasons. See `ootp_db_constants` (`SPLIT_CAREER_FIELDING_*`) and **`AGENTS.md`**.
  - Team **current-season** stats: non-`_history` tables (their own `split_id` meanings — see constants).
- **Never invent column names.** If unsure, call **`ootp_describe_table`**.
- Full human schema: project **`AGENTS.md`** (Database Schema Overview).
"""


@mcp.resource("ootp://saves-hint", mime_type="text/markdown")
def resource_saves_hint() -> str:
    return """# Saves registry

- Config: **`DATABASE_URL`** in `.env` (SQLite files under `db/<save>.db` or PostgreSQL).
- Active save and import metadata: **`saves.sqlite.json`** or **`saves.postgresql.json`** at the project root (matches engine).
- Field **`active`** is the default save when `save_name` is omitted on tools.
"""


@mcp.resource("ootp://schema-snapshot", mime_type="application/json")
def resource_schema_snapshot() -> str:
    """Post-import column snapshot if present (schema_snapshots/<db_name>.json)."""
    try:
        save = _resolve_save_name(None)
    except ValueError as e:
        return json.dumps(dict(ok=False, error=str(e)))
    db_name = db_name_from_save(save)
    path = _ROOT / "schema_snapshots" / f"{db_name}.json"
    if not path.is_file():
        return json.dumps(
            dict(
                ok=False,
                message="No schema snapshot for this save — run import to refresh schema_snapshots.",
                db_name=db_name,
            ),
            indent=2,
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return json.dumps(dict(ok=False, error=f"Invalid JSON: {e}"))
    return json.dumps(data, indent=2)


@mcp.tool()
def ootp_list_saves() -> str:
    """List registered saves and which one is active (default for other tools)."""
    reg = load_saves_registry()
    saves = reg.get("saves") or {}
    out = dict(
        active=reg.get("active"),
        saves=[
            dict(
                name=name,
                db_name=info.get("db_name"),
                last_import=info.get("last_import"),
            )
            for name, info in sorted(saves.items(), key=lambda x: x[0].lower())
        ],
    )
    return json.dumps(out, indent=2)


@mcp.tool()
def ootp_list_tables(save_name: str | None = None) -> str:
    """List all table names in the save database (SQLite or PostgreSQL)."""
    save = _resolve_save_name(save_name)
    engine = get_engine(save)
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            rows = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ).fetchall()
        else:
            rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name"
                )
            ).fetchall()
    names = [r[0] for r in rows]
    return json.dumps(dict(save=save, tables=names, count=len(names)), indent=2)


@mcp.tool()
def ootp_describe_table(table: str, save_name: str | None = None) -> str:
    """Return columns (name, type, nullable) for one table."""
    t = _validate_table_name(table)
    save = _resolve_save_name(save_name)
    engine = get_engine(save)
    insp = inspect(engine)
    cols: list[dict] = []
    for col in insp.get_columns(t):
        out = dict(
            name=col.get("name"),
            type=str(col.get("type")),
            nullable=bool(col.get("nullable", True)),
        )
        if "primary_key" in col:
            out["primary_key"] = bool(col.get("primary_key"))
        cols.append(out)
    return json.dumps(dict(save=save, table=t, columns=cols), indent=2)


@mcp.tool()
def ootp_run_sql(
    sql: str,
    save_name: str | None = None,
    max_rows: int | None = None,
) -> str:
    """Run a single read-only SELECT (or WITH ... SELECT). Row cap if no LIMIT."""
    save = _resolve_save_name(save_name)
    cap = int(max_rows) if max_rows is not None else DEFAULT_MAX_ROWS
    if cap < 1 or cap > 10_000:
        raise ValueError("max_rows must be between 1 and 10000")

    stmt = validate_readonly_sql(sql)
    final_sql = clamp_limit_in_sql(stmt, cap)

    engine = get_engine(save)
    with engine.connect() as conn:
        result = conn.execute(text(final_sql))
        keys = list(result.keys()) if result.keys() else []
        rows = result.fetchmany(cap + 1)
    truncated = len(rows) > cap
    out_rows = [dict(zip(keys, row)) for row in rows[:cap]]

    payload = dict(
        save=save,
        sql_executed=final_sql,
        columns=keys,
        row_count=len(out_rows),
        truncated=truncated,
        rows=out_rows,
    )
    if truncated:
        payload["notice"] = f"Result truncated to {cap} rows; tighten WHERE or lower max_rows."
    return json.dumps(payload, indent=2, default=str)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
