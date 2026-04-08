#!/usr/bin/env python3
"""Import OOTP Baseball CSV dumps into PostgreSQL."""

import json
import os
import platform
import re
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from shared_css import db_name_from_save, get_saves_path, load_saves_registry
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SNAPSHOTS_DIR = PROJECT_ROOT / "schema_snapshots"

_OOTP_VERSION_RE = re.compile(
    r"(?:OOTP Baseball|Out of the Park Baseball)\s*(\d+)\s*$",
    re.IGNORECASE,
)


def detect_ootp_version(lg_dir: Path) -> int | None:
    """Extract OOTP major version from path (e.g. 27 from folder 'OOTP Baseball 27')."""
    try:
        resolved = lg_dir.resolve()
    except OSError:
        resolved = lg_dir
    for p in [resolved, *resolved.parents]:
        m = _OOTP_VERSION_RE.match(p.name)
        if m:
            return int(m.group(1))
    m = re.search(
        r"(?:OOTP Baseball|Out of the Park Baseball)\s*(\d+)",
        str(resolved),
        re.IGNORECASE,
    )
    return int(m.group(1)) if m else None


def schema_snapshot_path(db_name: str) -> Path:
    return SCHEMA_SNAPSHOTS_DIR / f"{db_name}.json"


def load_schema_snapshot(db_name: str) -> dict[str, list[str]]:
    path = schema_snapshot_path(db_name)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    raw = data.get("tables") or {}
    return {str(k): [str(c) for c in v] for k, v in raw.items()}


def save_schema_snapshot(db_name: str, tables: dict[str, list[str]]) -> None:
    SCHEMA_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ordered = {
        t: sorted(cols) for t, cols in sorted(tables.items(), key=lambda x: x[0])
    }
    schema_snapshot_path(db_name).write_text(
        json.dumps(dict(tables=ordered), indent=2)
    )


def diff_schemas(
    previous: dict[str, list[str]],
    current: dict[str, list[str]],
) -> dict:
    """Compare two table→columns maps. Keys are table names; values sorted column lists."""
    prev_keys = set(previous)
    cur_keys = set(current)
    new_tables = sorted(cur_keys - prev_keys)
    removed_tables = sorted(prev_keys - cur_keys)
    table_column_changes: dict[str, dict[str, list[str]]] = {}
    for t in sorted(prev_keys & cur_keys):
        pcols = set(previous[t])
        ccols = set(current[t])
        added = sorted(ccols - pcols)
        removed = sorted(pcols - ccols)
        if added or removed:
            table_column_changes[t] = {
                "new_columns": added,
                "removed_columns": removed,
            }
    return {
        "new_tables": new_tables,
        "removed_tables": removed_tables,
        "table_column_changes": table_column_changes,
    }


def print_schema_changes(diff: dict, had_previous: bool) -> None:
    if not had_previous:
        print(
            "\nSchema: first import for this database — baseline snapshot saved for next run."
        )
        return
    if (
        not diff["new_tables"]
        and not diff["removed_tables"]
        and not diff["table_column_changes"]
    ):
        print("\nSchema changes: none.")
        return
    print("\nSchema changes")
    print("-" * 40)
    for t in diff["new_tables"]:
        print(f"  New table: {t}")
    for t in diff["removed_tables"]:
        print(f"  Removed table (warning): {t}")
    for t, ch in sorted(diff["table_column_changes"].items()):
        if ch["new_columns"]:
            cols = ", ".join(ch["new_columns"])
            print(f"  {t}: new columns: {cols}")
        if ch["removed_columns"]:
            cols = ", ".join(ch["removed_columns"])
            print(f"  {t}: removed columns (warning): {cols}")


# Known OOTP install root patterns, searched in order, per platform
if platform.system() == "Windows":
    _OOTP_SEARCH = [
        (
            Path.home() / "Documents" / "Out of the Park Developments",
            "OOTP Baseball */saved_games",
        ),
        (
            Path("C:/Program Files (x86)/Steam/steamapps/common"),
            "Out of the Park Baseball */saved_games",
        ),
        (
            Path("C:/Program Files/Steam/steamapps/common"),
            "Out of the Park Baseball */saved_games",
        ),
    ]
else:
    # macOS (and Linux fallback)
    _OOTP_SEARCH = [
        (
            Path.home() / "Library/Containers",
            "com.ootpdevelopments.ootp*/Data/Application Support/"
            "Out of the Park Developments/OOTP Baseball */saved_games",
        ),
        (
            Path.home() / "Library/Application Support",
            "Out of the Park Developments/OOTP Baseball */saved_games",
        ),
    ]


def singularize(name):
    """Simple singularization for OOTP table names."""
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ches") or name.endswith("ses"):
        return name[:-2]
    if name.endswith("s"):
        return name[:-1]
    return name


# Known compound primary keys for tables where the singular_id pattern doesn't apply
COMPOUND_KEYS = {
    "divisions": ("league_id", "sub_league_id", "division_id"),
    "sub_leagues": ("league_id", "sub_league_id"),
    "team_relations": ("league_id", "team_id"),
    "team_affiliations": ("team_id", "affiliated_team_id"),
    "team_roster": ("team_id", "player_id", "list_id"),
    "game_logs": ("game_id", "line"),
    "games_score": ("game_id", "team", "inning"),
    "language_data": ("parent_id", "language_id"),
    "league_history": ("league_id", "sub_league_id", "year"),
    "league_history_all_star": ("league_id", "sub_league_id", "year", "all_star_pos"),
    "league_history_fielding_stats": ("year", "league_id", "sub_league_id"),
    "team_history": ("team_id", "year"),
    "team_history_batting_stats": ("team_id", "year"),
    "team_history_fielding_stats_stats": ("team_id", "year"),
    "team_history_financials": ("team_id", "year"),
    "team_history_pitching_stats": ("team_id", "year"),
    "team_history_record": ("team_id", "year"),
    "human_manager_history": ("human_manager_id", "year"),
    "human_manager_history_batting_stats": ("human_manager_id", "year"),
    "human_manager_history_fielding_stats_stats": ("human_manager_id", "year"),
    "human_manager_history_financials": ("human_manager_id", "year"),
    "human_manager_history_pitching_stats": ("human_manager_id", "year"),
    "human_manager_history_record": ("human_manager_id", "year"),
    "players_individual_batting_stats": ("player_id", "opponent_id"),
    "players_salary_history": ("player_id", "team_id", "year"),
    "players_game_pitching_stats": ("player_id", "game_id"),
}


def _find_saves_dirs():
    """Yield all saved_games directories found in known OOTP install locations."""
    for root, pattern in _OOTP_SEARCH:
        if root.is_dir():
            yield from root.glob(pattern)


def find_lg_dir(save_name):
    """Search known OOTP locations for <save_name>.lg. Returns Path or None."""
    for saves_dir in _find_saves_dirs():
        candidate = saves_dir / f"{save_name}.lg"
        if candidate.is_dir():
            return candidate
    return None


def list_saves():
    """Print all .lg saves found on the machine, noting which are imported."""
    registry = _load_registry()
    imported = registry.get("saves", {})
    active = registry.get("active")

    discovered = {}
    for saves_dir in _find_saves_dirs():
        for lg_dir in sorted(saves_dir.glob("*.lg")):
            name = lg_dir.stem
            if not name or lg_dir.name == ".lg":
                continue
            if name not in discovered:
                discovered[name] = lg_dir

    if not discovered and not imported:
        print("No OOTP saves found.")
        return

    all_names = sorted(set(list(discovered.keys()) + list(imported.keys())))
    print(f"{'Save':<35} {'Status':<12} {'Last Import':<22} {'Path'}")
    print("-" * 100)
    for name in all_names:
        marker = " *" if name == active else "  "
        if name in imported:
            last = imported[name].get("last_import", "unknown")
            path = imported[name].get("csv_path", "")
            # Show the .lg dir path, not the csv subdir
            lg_path = str(Path(path).parent.parent) if path else ""
            status = "imported"
        else:
            last = ""
            lg_path = str(discovered[name]) if name in discovered else ""
            status = "not imported"
        print(f"{marker}{name:<33} {status:<12} {last:<22} {lg_path}")

    if active:
        print(f"\nActive save: {active}")


def _load_registry():
    return load_saves_registry()


def _update_registry(save_name, db_name, csv_dir, ootp_version: int | None = None):
    registry = _load_registry()
    saves = registry.setdefault("saves", {})
    existing = saves.get(save_name, {})
    existing.update({
        "db_name": db_name,
        "last_import": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "csv_path": str(csv_dir),
        "ootp_version": ootp_version,
    })
    saves[save_name] = existing
    # Set active only if not already set
    if not registry.get("active"):
        registry["active"] = save_name
    get_saves_path().write_text(json.dumps(registry, indent=2))


def resolve_save(arg, ootp_root=None):
    """
    Given a save name or path, return (csv_dir, save_name, lg_dir).
    Resolution order:
      1. Existing directory path (absolute or relative)
      2. Auto-discover via glob in known OOTP locations
      3. OOTP_CSV_PATH fallback (if set)
    """
    p = Path(arg).expanduser().resolve()

    if p.is_dir():
        # User passed a path — accept .lg dir directly or its parent
        lg_dir = p if p.suffix == ".lg" else p
        if lg_dir.suffix != ".lg":
            print(f"Error: '{arg}' is a directory but doesn't look like a .lg save folder.")
            sys.exit(1)
    else:
        # Try auto-discovery first
        lg_dir = find_lg_dir(arg)

        # Fall back to OOTP_CSV_PATH if set
        if lg_dir is None and ootp_root:
            candidate = Path(ootp_root) / "saved_games" / f"{arg}.lg"
            if candidate.is_dir():
                lg_dir = candidate

        if lg_dir is None:
            searched = [str(root / pattern.split("*")[0]) for root, pattern in _OOTP_SEARCH]
            print(f"Error: Could not find save '{arg}'.")
            print("Searched in:")
            for s in searched:
                print(f"  {s}...")
            if ootp_root:
                print(f"  {ootp_root}/saved_games/")
            print("\nOptions:")
            print(f"  Pass the full path: python src/import.py /path/to/{arg}.lg")
            print(f"  Run 'python src/import.py list' to see discovered saves")
            sys.exit(1)

    save_name = lg_dir.stem
    csv_dir = lg_dir / "import_export" / "csv"
    if not csv_dir.is_dir():
        print(f"Error: CSV directory not found: {csv_dir}")
        print("Export CSVs in OOTP: Game → Game Settings → Database tab → Export CSV Files")
        sys.exit(1)

    csv_files = list(csv_dir.glob("*.csv"))
    if not csv_files:
        print(f"Error: No .csv files found in {csv_dir}")
        sys.exit(1)

    return csv_dir, save_name, lg_dir


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <save_name_or_path>")
        print(f"       python {sys.argv[0]} list")
        print("Examples:")
        print("  python src/import.py My-Save-2026")
        print("  python src/import.py /path/to/My-Save-2026.lg")
        print("  python src/import.py list")
        sys.exit(1)

    # Load .env (optional — defaults to SQLite if not present)
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    if sys.argv[1] == "list":
        list_saves()
        return

    # Join all remaining args to support save names with spaces
    # e.g. ./import.sh Bless You Boys  →  "Bless You Boys"
    arg = " ".join(sys.argv[1:])

    ootp_root = os.getenv("OOTP_CSV_PATH")  # optional, for backward compat
    csv_dir, save_name, lg_dir = resolve_save(arg, ootp_root=ootp_root)
    ootp_version = detect_ootp_version(lg_dir)

    database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "sqlite"
    if not os.getenv("DATABASE_URL") and os.getenv("POSTGRES_URL"):
        print("Warning: POSTGRES_URL is deprecated, rename to DATABASE_URL in .env")

    db_name = db_name_from_save(save_name)
    is_sqlite = database_url.lower().startswith("sqlite")

    if is_sqlite:
        db_dir = PROJECT_ROOT / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{db_dir / db_name}.db")
        print(f"Using SQLite database: {db_dir / db_name}.db")
    else:
        # Create PostgreSQL database if it doesn't exist
        try:
            admin_engine = create_engine(
                f"{database_url.rstrip('/')}/postgres",
                isolation_level="AUTOCOMMIT",
            )
            with admin_engine.connect() as conn:
                exists = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :db"),
                    {"db": db_name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                    print(f"Created database: {db_name}")
            admin_engine.dispose()
        except Exception as e:
            print(f"Error: Could not connect to PostgreSQL: {e}")
            sys.exit(1)
        engine = create_engine(f"{database_url.rstrip('/')}/{db_name}")

    csv_files = sorted(csv_dir.glob("*.csv"))
    previous_schema = load_schema_snapshot(db_name)
    had_previous_schema = bool(previous_schema)
    current_schema: dict[str, list[str]] = {}

    # Import CSVs
    start = time.time()
    total_tables = 0
    total_rows = 0

    for csv_file in csv_files:
        table_name = csv_file.stem.lower()
        try:
            df = pd.read_csv(csv_file, low_memory=False, escapechar="\\")

            # Coerce ID columns to nullable integer
            for col in df.columns:
                if col == "id" or col.endswith("_id"):
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

            df.to_sql(table_name, engine, if_exists="replace", index=False)
            current_schema[table_name] = sorted(str(c) for c in df.columns)
            row_count = len(df)
            total_rows += row_count
            total_tables += 1
            print(f"✓ {table_name} ({row_count} rows)")
        except Exception as e:
            print(f"⚠ {table_name}: skipped ({e})")

    # Add primary keys and indexes
    print()
    with engine.connect() as conn:
        for csv_file in csv_files:
            table_name = csv_file.stem.lower()
            try:
                if engine.dialect.name == "sqlite":
                    cols = [
                        row[1]
                        for row in conn.execute(
                            text(f"PRAGMA table_info('{table_name}')")
                        )
                    ]
                else:
                    cols = [
                        row[0]
                        for row in conn.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name = :t ORDER BY ordinal_position"
                            ),
                            {"t": table_name},
                        )
                    ]
            except Exception:
                conn.rollback()
                continue

            # Determine primary key columns
            pk_cols = None
            if table_name in COMPOUND_KEYS:
                pk_cols = COMPOUND_KEYS[table_name]
            else:
                pk_col = singularize(table_name) + "_id"
                if pk_col in cols:
                    pk_cols = (pk_col,)

            if pk_cols:
                pk_col_list = ", ".join(f'"{c}"' for c in pk_cols)
                if engine.dialect.name == "sqlite":
                    idx_name = f"idx_{table_name}_pk"
                    try:
                        conn.execute(
                            text(
                                f'CREATE UNIQUE INDEX IF NOT EXISTS "{idx_name}" '
                                f'ON "{table_name}" ({pk_col_list})'
                            )
                        )
                        print(f"  PK {table_name} ({', '.join(pk_cols)})")
                    except Exception:
                        pass
                else:
                    conn.execute(text("SAVEPOINT pk_attempt"))
                    try:
                        conn.execute(
                            text(
                                f'ALTER TABLE "{table_name}" '
                                f"ADD PRIMARY KEY ({pk_col_list})"
                            )
                        )
                        conn.execute(text("RELEASE SAVEPOINT pk_attempt"))
                        print(f"  PK {table_name} ({', '.join(pk_cols)})")
                    except Exception:
                        conn.execute(text("ROLLBACK TO SAVEPOINT pk_attempt"))

            # Indexes on all other _id columns not part of the primary key
            pk_set = set(pk_cols) if pk_cols else set()
            for col in cols:
                if col.endswith("_id") and col not in pk_set:
                    idx_name = f"idx_{table_name}_{col}"
                    conn.execute(text("SAVEPOINT idx_attempt"))
                    try:
                        conn.execute(
                            text(
                                f'CREATE INDEX "{idx_name}" '
                                f'ON "{table_name}" ("{col}")'
                            )
                        )
                        conn.execute(text("RELEASE SAVEPOINT idx_attempt"))
                        print(f"  IX {table_name}.{col}")
                    except Exception:
                        conn.execute(text("ROLLBACK TO SAVEPOINT idx_attempt"))
        conn.commit()

    schema_diff = diff_schemas(previous_schema, current_schema)
    print_schema_changes(schema_diff, had_previous_schema)
    save_schema_snapshot(db_name, current_schema)

    # Update saves registry
    _update_registry(save_name, db_name, csv_dir, ootp_version=ootp_version)

    elapsed = time.time() - start
    print(f"\nDone: {total_tables} tables, {total_rows:,} rows in {elapsed:.1f}s")
    print(f"Save '{save_name}' → database '{db_name}'")
    if ootp_version is not None:
        print(f"OOTP version (from path): {ootp_version}")


if __name__ == "__main__":
    main()
