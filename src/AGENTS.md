---
paths:
  - "src/**"
---

## Environment
- Python 3.11+
- Virtual environment at `.venv` (create with `python3 -m venv .venv`)
- PostgreSQL assumed to be running locally
- The target database is created automatically by the import script if it doesn't exist

## Dependencies
All dependencies go in `requirements.txt`:
- pandas
- sqlalchemy
- psycopg2-binary
- python-dotenv

## Configuration
All configuration is via a `.env` file in the project root. A `.env.example` should be 
created as a template. Never commit `.env`.
```
# Use 'sqlite' for local SQLite files (db/<db_name>.db; same naming as PostgreSQL db_name), or a full PostgreSQL URL
DATABASE_URL=sqlite
# DATABASE_URL=postgresql://localhost

# Optional: only needed if auto-discovery fails (see import.py Behavior below)
# OOTP_CSV_PATH=/Users/<username>/Library/Containers/com.ootpdevelopments.ootp27macqlm/Data/Application Support/Out of the Park Developments/OOTP Baseball 27
```

## Project Structure
```
ootp-db/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .env                  # not committed
├── .env.example
├── .gitignore
└── src/
    ├── import.py
    ├── analytics.py
    ├── shared_css.py
    ├── config.py
    ├── ootp_db_constants.py
    └── ratings/          # example domain package (see skills/AGENTS.md → Domain packages)
        ├── __init__.py
        ├── __main__.py
        ├── compute.py
        ├── constants.py
        ├── grades.py
        ├── queries.py
        └── report.py
```

Larger features that outgrow a single `src/<script>.py` file should follow the
**ratings-style domain package** described in `skills/AGENTS.md → Domain packages and
module split (ratings model)`.

## import.py Behavior
- Accept a save name or path as a CLI argument (e.g. `My-Save-2026` or `/path/to/My-Save-2026.lg`)
- Resolve the `.lg` directory via: (1) direct path arg, (2) auto-discovery in known OOTP macOS
  locations (`~/Library/Containers/com.ootpdevelopments.ootp*` and
  `~/Library/Application Support/Out of the Park Developments/OOTP Baseball *`),
  (3) `OOTP_CSV_PATH` env var fallback
- Build the CSV path: `<save>.lg/import_export/csv`
- Load config from `.env`
- Validate that the CSV path exists and contains `.csv` files, exit with clear error if not
- After a successful import, update the engine-specific saves registry (`saves.sqlite.json` or
  `saves.postgresql.json`) with the save's db name, last import time, csv path, and
  `ootp_version` (major version inferred from the `.lg` path, or null if unknown). Sets `active`
  to this save if no active save is set yet.
- Compare loaded CSV columns to `schema_snapshots/<db_name>.json` from the prior import; print a
  **Schema changes** summary (new/removed tables and columns), then refresh the snapshot.
- Derive database name from save name (lowercase, hyphens/spaces → underscores)
- Create the database if it doesn't already exist (SQLite: creates file; PostgreSQL: connects to `postgres` db with AUTOCOMMIT)
- Connect via DATABASE_URL/<db_name> (or POSTGRES_URL for backward compat)
- For each `.csv` file in the dump directory:
  - Derive table name from filename (strip `.csv` extension, lowercase)
  - Read into a pandas DataFrame
  - Coerce any column ending in `_id` or named `id` to Int64 (nullable integer) to prevent 
    float inference from nulls
  - Load into Postgres using `if_exists='replace'` and `index=False`
  - Print: `✓ <table_name> (<row_count> rows)`
- Print a final summary: total tables loaded, total rows, elapsed time
- Exit with code 1 on any failure, with a descriptive error message

## Error Handling
- Missing `.env` file: print instructions to copy `.env.example`
- CSV directory not found: print the expected path and suggest checking OOTP export location
- Postgres connection failure: print the error and check that PostgreSQL is running
- Individual CSV parse errors: log a warning and continue, do not abort the full import

## Running
```bash
# First time setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — only POSTGRES_URL is required

# List available saves (auto-discovered)
./import.sh list

# Import by save name (auto-discovered)
./import.sh My-Save-2026

# Or import by full path to the .lg directory
./import.sh /path/to/My-Save-2026.lg
```

## Notes
- The OOTP CSV dump is triggered from inside OOTP: Game → Game Settings → Database tab → 
  Database Tools → Export CSV Files
- The dump directory is typically inside the `.lg` saved game folder under `import_export/csv`
- Do not use the MySQL export — it generates MySQL-specific SQL that is not compatible 
  with PostgreSQL
- The script auto-creates the database if needed; no manual `createdb` step required
- Database name is derived from the save name (lowercase, hyphens/spaces → underscores): `My-Save-2026` → `my_save_2026`, `Restore the Roar` → `restore_the_roar`
