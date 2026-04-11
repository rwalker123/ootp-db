# OOTP Database Importer

## Project Overview
A Python CLI tool that imports OOTP Baseball CSV data dumps into a local PostgreSQL database. 
Designed to be re-run after each OOTP sim to keep the database current.

## Querying the Database
When answering questions about OOTP data, always use `.venv/bin/python3` with sqlalchemy 
and a heredoc to avoid shell quoting issues:
```bash
.venv/bin/python3 << 'PYEOF'
from sqlalchemy import text
from shared_css import get_engine, load_saves_registry
import sys
sys.path.insert(0, "src")
save = load_saves_registry()["active"]
engine = get_engine(save)
with engine.connect() as conn:
    result = conn.execute(text("SELECT ...")).fetchall()
    for row in result:
        print(row)
PYEOF
```
- **Never** hardcode a database URL — use `get_engine(save_name)` from `src/shared_css.py`,
  which reads `DATABASE_URL` from `.env` and routes to SQLite or PostgreSQL automatically.
  **`get_engine` is read-only** (SQLite `mode=ro`; Postgres `default_transaction_read_only=on`).
  Import and derived-table jobs (`import.py`, `analytics.py`, `ratings` package / `python -m ratings`, etc.) use **`get_write_engine(save_name)`** instead.
- The active DB engine is configured via `DATABASE_URL` in `.env`:
  - `DATABASE_URL=sqlite` → SQLite files under `db/<db_name>.db`, where `db_name` is derived from the save name (lowercase; hyphens and spaces → underscores), same as `db_name_from_save()` in `src/shared_css.py`
  - `DATABASE_URL=postgresql://...` → PostgreSQL
- **Never** use `psql`, `source .venv/bin/activate`, or other approaches
- **Always** use `.venv/bin/python3` directly (not `python3` or `source ... && python3`)
- **Always** use heredoc (`<< 'PYEOF'`) syntax, never `-c` with inline strings
- **Never** use Python dicts (`{"key": val}`) or f-strings with braces in heredocs — 
  the shell flags curly braces as suspicious. Use `dict(key=val)` instead of `{"key": val}`.
- **Never use `ILIKE` in SQL** — `ILIKE` is PostgreSQL-only and will fail on SQLite.
  Use `LIKE` instead; SQLite's `LIKE` is already case-insensitive for ASCII characters.
  This applies everywhere, including team name lookups in skill query modules.
- **Never read `.env` directly** — it contains API keys. All DB config is accessed via
  `get_engine(save_name)` and `load_saves_registry()`. Never `cat .env`, never open it.
- **`players_contract` salary columns** are named `salary0` through `salary14` (one per contract
  year). There is **no** bare `salary` column and **no** `length` column. Use `salary0` for the
  current year's salary. Contract length is stored as `years`; current year position is `current_year`.
- The active save and database name are tracked in `saves.postgresql.json` or `saves.sqlite.json`
  at the project root (engine-specific). Read the correct file based on `DATABASE_URL` in `.env`,
  or use `load_saves_registry()` from `src/shared_css.py`.
  Active save name: `registry["active"]`; DB name: `save_name.lower().replace("-", "_").replace(" ", "_")` (see `db_name_from_save` in `src/shared_css.py`).
- **MCP (Cursor / Claude Desktop):** run `mcp_server.py` from the project root, or `./mcp-server.sh` / `mcp-server.bat` (venv + deps + same update check as web UI); tools `ootp_*` use the same read-only `get_engine` path. See README **Under the Hood → Model Context Protocol (MCP)**.
- **Never use magic numbers for OOTP enum values.** All fixed OOTP game schema constants
  (league IDs, level IDs, position codes, split IDs, role codes, result codes, etc.) are
  defined in `src/ootp_db_constants.py`. Import from there:
  ```python
  from ootp_db_constants import MLB_LEAGUE_ID, MLB_LEVEL_ID, SPLIT_CAREER_OVERALL
  ```
  Always filter by `league_id = MLB_LEAGUE_ID` unless the user specifically asks about
  minor leagues. Other league_ids are minor league levels.
  Application-level thresholds (grade cutoffs, rating weights, injury tiers) live in
  `src/config.py` — see the Analytics Engine section.
- Current-season data is in the main tables (e.g. `team_record`, `team_batting_stats`).
  Prior seasons are in `_history` tables.
- Refer to the Database Schema Overview below for table structures, primary keys, 
  column conventions, and stat abbreviations. Do NOT explore the schema at query time — 
  it is fully documented here.
- **Only use column names documented in the schema below.** Do not guess or invent 
  column names. If unsure, check the schema section first.
- **When ranking or listing players by quality, always use `player_ratings.rating_overall`**
  (the composite 0–100 score computed by `src/ratings/` — run via `python -m ratings` from `src/`) rather than `players_value.oa_rating`
  or `players_value.oa` (OOTP's raw 20–80 scale). The `player_ratings` table also has
  per-dimension scores (`rating_offense`, `rating_defense`, etc.) and is pre-filtered to
  MLB-level players. See the Analytics Engine section for its full schema.

### Common Query Patterns
World Series winner for a given year (won_playoffs = 1 means won the championship):
```sql
SELECT t.name, t.nickname, thr.w, thr.l
FROM team_history th
JOIN teams t ON t.team_id = th.team_id
JOIN team_history_record thr ON thr.team_id = th.team_id AND thr.year = th.year
WHERE th.year = 2027 AND th.won_playoffs = 1 AND th.league_id = 203  -- MLB_LEAGUE_ID
```
Playoff teams for a given year:
```sql
SELECT t.name, t.nickname, thr.w, thr.l, thr.pos, d.name as division
FROM team_history th
JOIN teams t ON t.team_id = th.team_id
JOIN team_history_record thr ON thr.team_id = th.team_id AND thr.year = th.year
JOIN divisions d ON d.league_id = th.league_id AND d.sub_league_id = th.sub_league_id AND d.division_id = th.division_id
WHERE th.year = 2027 AND th.made_playoffs = 1 AND th.league_id = 203  -- MLB_LEAGUE_ID
ORDER BY thr.w DESC
```
Current season division standings (use `dict()` not `{}` for params in heredocs):
```sql
-- Python: conn.execute(text("..."), dict(lid=MLB_LEAGUE_ID, slid=0, did=1))
SELECT t.name, t.nickname, tr.w, tr.l, tr.pct, tr.pos, tr.gb
FROM team_relations rel
JOIN teams t ON t.team_id = rel.team_id
JOIN team_record tr ON tr.team_id = rel.team_id
WHERE rel.league_id = :lid AND rel.sub_league_id = :slid AND rel.division_id = :did
ORDER BY tr.pos
```
Player lookup by name:
```sql
SELECT player_id, first_name, last_name, team_id, position, age
FROM players WHERE last_name = 'Jobe' AND first_name = 'Jackson'
```

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
    └── ratings/          # example domain package (see “Domain packages” under Skill Architecture)
        ├── __init__.py
        ├── __main__.py
        ├── compute.py
        ├── constants.py
        ├── grades.py
        ├── queries.py
        └── report.py
```

Larger features that outgrow a single `src/<script>.py` file should follow the **ratings-style domain package** described in **Skill Architecture → Domain packages and module split (ratings model)** below.

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

## Re-running After a Sim
Just run `./import.sh My-Save-2026` again. All tables are dropped and recreated, so the 
database always reflects the current state of the OOTP save.

## Saves registry (`saves.sqlite.json` / `saves.postgresql.json`)
After each import, the registry for the configured engine is written/updated in the project root
(legacy `saves.json` is migrated once to the engine-specific file). It tracks all imported saves
and which one is currently active. Per-save entries include `db_name`, `last_import`, `csv_path`,
and `ootp_version` when the install path includes a folder like `OOTP Baseball 27`. The active save
determines which DB the skills query. The `active` pointer is set to the first save imported;
subsequent imports don't change it (it will be switchable from the web UI in the future).

Schema snapshots for drift detection live under `schema_snapshots/` (gitignored), one JSON file per
database name.

## Notes
- The OOTP CSV dump is triggered from inside OOTP: Game → Game Settings → Database tab → 
  Database Tools → Export CSV Files
- The dump directory is typically inside the `.lg` saved game folder under `import_export/csv`
- Do not use the MySQL export — it generates MySQL-specific SQL that is not compatible 
  with PostgreSQL
- The script auto-creates the database if needed; no manual `createdb` step required
- Database name is derived from the save name (lowercase, hyphens/spaces → underscores): `My-Save-2026` → `my_save_2026`, `Restore the Roar` → `restore_the_roar`

## Database Schema Overview

The OOTP CSV export produces 71 tables. Below is the structure organized by domain.

### Primary Key Conventions
- Entity tables use `<singular_table_name>_id` as PK (e.g. `teams` → `team_id`)
- History/stats tables use compound keys (e.g. `team_id + year`)
- The import script auto-creates PKs and indexes on `_id` columns after loading

### Reference / Lookup Tables

| Table | PK | Key Columns | Description |
|-------|-----|-------------|-------------|
| `leagues` (15) | `league_id` | nation_id, language_id, parent_league_id | League config, rules, ratings averages |
| `sub_leagues` (16) | `league_id, sub_league_id` | | AL/NL style sub-leagues within a league |
| `divisions` (39) | `league_id, sub_league_id, division_id` | | Divisions within sub-leagues |
| `team_relations` (231) | `league_id, team_id` | sub_league_id, division_id | Maps teams to their league/division |
| `nations` (244) | `nation_id` | continent_id, capital_id | Countries |
| `states` (3375) | `state_id` | nation_id | States/provinces |
| `cities` (122K) | `city_id` | nation_id, state_id | Cities with lat/long/population |
| `continents` (6) | `continent_id` | | Continents |
| `languages` (40) | `language_id` | | Language names |
| `language_data` (373) | `parent_id, language_id` | | Language percentages for nations |
| `parks` (212) | `park_id` | nation_id | Ballparks with dimensions, weather, park factors |

### Teams

| Table | PK | Key Columns | Description |
|-------|-----|-------------|-------------|
| `teams` (273) | `team_id` | city_id, park_id, league_id, sub_league_id, division_id, parent_team_id | Team info; `parent_team_id` links minors to MLB org |
| `team_affiliations` (229) | `team_id, affiliated_team_id` | | Minor league affiliations |
| `team_roster` (19K) | `team_id, player_id, list_id` | | Roster assignments |
| `team_roster_staff` (273) | `team_id` | | Staff IDs (manager, coaches, GM, owner, etc.) — values are coach_id references |
| `team_record` (273) | `team_id` | | Current season W/L/pct/GB |
| `team_financials` (273) | `team_id` | | Current season finances (revenue, expenses, budget, attendance) |
| `team_last_financials` (273) | `team_id` | | Previous season finances |
| `team_batting_stats` (273) | `team_id` | league_id, level_id, split_id | Current season team batting |
| `team_pitching_stats` (273) | `team_id` | league_id, level_id, split_id | Current season team pitching |
| `team_bullpen_pitching_stats` (273) | `team_id` | league_id, level_id, split_id | Current season bullpen splits |
| `team_starting_pitching_stats` (273) | `team_id` | league_id, level_id, split_id | Current season starter splits |
| `team_fielding_stats_stats` (273) | `team_id` | league_id, level_id, split_id | Current season team fielding |
| `projected_starting_pitchers` (273) | `team_id` | | Projected rotation (starter_0 through starter_7 are player_ids) |

### Team History (keyed by team_id + year)

| Table | Description |
|-------|-------------|
| `team_history` (4K) | Year-by-year team name, league, division, awards, playoffs |
| `team_history_record` (4K) | Year-by-year W/L/pct |
| `team_history_batting_stats` (4K) | Year-by-year team batting |
| `team_history_pitching_stats` (4K) | Year-by-year team pitching |
| `team_history_fielding_stats_stats` (4K) | Year-by-year team fielding |
| `team_history_financials` (4K) | Year-by-year team finances |

### Players

| Table | PK | Key Columns | Description |
|-------|-----|-------------|-------------|
| `players` (136K) | `player_id` | team_id, league_id, nation_id, city_of_birth_id | Player bio, demographics, personality, injury status, draft info, morale |
| `players_batting` (136K) | `player_id` | team_id, league_id | Batting ratings (overall/vsR/vsL/talent), running ratings |
| `players_pitching` (136K) | `player_id` | team_id, league_id | Pitching ratings (stuff/movement/control), pitch repertoire ratings |
| `players_fielding` (136K) | `player_id` | team_id, league_id | Fielding ratings by position, experience by position |
| `players_scouted_ratings` (45K) | `player_id, scouting_team_id` | scouting_coach_id, scouting_accuracy | Per-scout view of all ratings across all four tiers (overall/vsR/vsL/talent) for batting, pitching, and fielding. `scouting_team_id=0` with `scouting_coach_id=-1` = ground-truth true ratings; `scouting_team_id=N` = team N's scout view. Only present when "Additional complete scouted ratings" is enabled in OOTP export settings. |
| `players_value` (14K) | `player_id` | team_id, league_id | Computed player values (offensive, pitching, overall, by position) |
| `players_contract` (14K) | `player_id` | team_id, league_id | Current contract details and salary by year |
| `players_contract_extension` (14K) | `player_id` | team_id, league_id | Extension offer details |
| `players_roster_status` (14K) | `player_id` | team_id, league_id, claimed_team_id | Service time, active/DL/waivers/DFA status. Key waiver/DFA columns: `is_on_waivers`, `designated_for_assignment` (not `is_dfa`), `days_on_waivers`, `days_on_waivers_left` (not `days_waivers_left`), `days_on_dfa_left`, `irrevocable_waivers`, `claimed_team_id` |
| `players_salary_history` (144K) | `player_id, team_id, year` | | Historical salary by year |
| `players_injury_history` (42K) | — | player_id | Injury log with dates, lengths, body parts |
| `players_awards` (14K) | — | player_id, league_id, team_id, award_id, year | Award history |
| `players_streak` (214K) | — | player_id, league_id, streak_id | Active and ended streaks |
| `players_individual_batting_stats` (180K) | `player_id, opponent_id` | | Batter vs pitcher matchup stats (ab, h, hr) |
| `players_league_leader` (189K) | — | player_id, league_id, sub_league_id, year, category | League leader placements |

### Player Ratings — What the CSV Exports

The CSV exports **true underlying ratings**, not scout-adjusted values. In-game, your 
team scout and the OSA scout each show estimates that may differ from the true value 
depending on scout accuracy. The CSV values will generally be close to your team scout's 
view but may differ by 5 points on individual ratings.

**`players_batting`** — Batting & running ratings:
- `batting_ratings_overall_*` — Current ability (overall). **Exported as zeros by default.**
  Two OOTP settings must both be active for real values to appear: (1) "Additional complete
  scouted ratings" in the CSV export config, AND (2) **Current Ratings Scale** must not be
  set to "None" in Game Settings → Global Settings → Player Rating Scales. If either is off, these columns
  export as zeros. Prefer `players_scouted_ratings` (scouting_team_id=0) as the authoritative
  source. In reports, zero values render as N/A.
- `batting_ratings_vsr_*` / `batting_ratings_vsl_*` — Current vs RHP/LHP. Same as above.
- `batting_ratings_talent_*` — Potential/talent ceiling. Requires **Potential Ratings Scale**
  not set to "None" in Game Settings → Global Settings → Player Rating Scales; zeros otherwise. In reports,
  zero values render as N/A.
- Rating categories: `contact`, `gap`, `eye`, `strikeouts` (avoid K), `hp` (HBP tendency), 
  `power`, `babip`
- `batting_ratings_misc_*` — `bunt`, `bunt_for_hit`, `gb_hitter_type`, `fb_hitter_type`
- `running_ratings_*` — `speed`, `stealing_rate` (aggressiveness), `stealing`, `baserunning`
- All ratings are on the 20-80 scouting scale

**`players_pitching`** — Pitching ratings (stuff/movement/control) and pitch repertoire.
  Same four tiers (overall/vsR/vsL/talent); overall/vsR/vsL are zeros by default. Same two
  conditions apply as batting: "Additional complete scouted ratings" enabled AND Current/Potential
  Ratings Scale not set to "None". Prefer `players_scouted_ratings` (scouting_team_id=0) as
  the authoritative source for current ratings. Zero values render as N/A in reports.

**`players_fielding`** — Fielding ratings:
- General (note the `fielding_ratings_` prefix on all general columns):
  `fielding_ratings_infield_range`, `fielding_ratings_infield_arm`, `fielding_ratings_turn_doubleplay`,
  `fielding_ratings_infield_error`, `fielding_ratings_outfield_range`, `fielding_ratings_outfield_arm`,
  `fielding_ratings_outfield_error`, `fielding_ratings_catcher_arm`, `fielding_ratings_catcher_ability`,
  `fielding_ratings_catcher_framing`
- Per-position current: `fielding_rating_pos1` through `pos9` (1=P through 9=RF)
- Per-position potential: `fielding_rating_pos1_pot` through `pos9_pot`
- Fielding ratings ARE exported with real values (not zeroed like batting)

**`players_value`** — Overall/potential ratings and computed values:
- `oa` / `pot` — precise internal overall ability / potential (may not land on 5s)
- `oa_rating` / `pot_rating` — display values rounded to 20-80 scale (nearest 5)
- `offensive_value`, `pitching_value`, `overall_value`, `talent_value`, `career_value` — 
  internal composite scores (larger scale, not 20-80)
- Per-position overall ratings: `overall_sp`, `overall_rp`, `overall_c`, `overall_1b` 
  through `overall_rf`

### Player Stats — Career (keyed by player_id + year + team_id + league_id + level_id + split_id)

| Table | Rows | Description |
|-------|------|-------------|
| `players_career_batting_stats` | 729K | Career batting by year/team/league/level/split |
| `players_career_pitching_stats` | 416K | Career pitching by year/team/league/level/split |
| `players_career_fielding_stats` | 210K | Career fielding by year/team/league/level/split/position |

**`players_career_fielding_stats` columns:** `player_id`, `year`, `team_id`, `league_id`, `level_id`,
`split_id`, `position`, `g`, `gs`, `ip` (innings played — NOT `inn`), `tc`, `po`, `a`, `e`, `er`,
`dp`, `tp`, `pb`, `sba`, `rto`, `ipf`, `plays`, `plays_base`, `roe`, `framing`, `arm`, `zr`
— Note: there is **no** `fpct` column; compute it as `(po + a - e) / (po + a)` if needed.

### Player Stats — Current Season Game-Level

| Table | PK | Rows | Description |
|-------|-----|------|-------------|
| `players_game_batting` | — | 288K | Per-game batting lines for current season |
| `players_game_pitching_stats` | `player_id, game_id` | 108K | Per-game pitching lines for current season |
| `players_at_bat_batting_stats` | — | 219K | Individual at-bat results with exit velo, launch angle |

### Games

| Table | PK | Key Columns | Description |
|-------|-----|-------------|-------------|
| `games` (13K) | `game_id` | league_id, home_team, away_team, winning_pitcher, losing_pitcher, save_pitcher, starter0, starter1 | Game results; `home_team`/`away_team` reference team_id; pitcher columns reference player_id |
| `games_score` (247K) | `game_id, team, inning` | | Inning-by-inning linescore |
| `game_logs` (227K) | `game_id, line` | | Play-by-play text (HTML with player links) |

### League History

| Table | PK | Description |
|-------|-----|-------------|
| `league_history` (372) | `league_id, sub_league_id, year` | Award winners per year |
| `league_history_all_star` (7K) | `league_id, sub_league_id, year, all_star_pos` | All-star selections |
| `league_history_batting_stats` (372) | — | League-wide batting by year |
| `league_history_pitching_stats` (372) | — | League-wide pitching by year |
| `league_history_fielding_stats` (372) | `year, league_id, sub_league_id` | League-wide fielding by year |
| `league_playoffs` (15) | `league_id` | Playoff format config |
| `league_playoff_fixtures` (15) | — | Current playoff matchups and results |
| `league_events` (3K) | — | Scheduled league events (draft, trade deadline, etc.) |

### Coaches & Staff

| Table | PK | Description |
|-------|-----|-------------|
| `coaches` (5K) | `coach_id` | Coach bio, ratings (teaching, scouting, managing, medical), strategy tendencies |

### Human Manager

| Table | PK | Description |
|-------|-----|-------------|
| `human_managers` (1) | `human_manager_id` | Your manager profile |
| `human_manager_history` | `human_manager_id, year` | Season-by-season summary |
| `human_manager_history_record` | `human_manager_id, year` | Season W/L record |
| `human_manager_history_batting_stats` | `human_manager_id, year` | Team batting under your management |
| `human_manager_history_pitching_stats` | `human_manager_id, year` | Team pitching under your management |
| `human_manager_history_fielding_stats_stats` | `human_manager_id, year` | Team fielding under your management |
| `human_manager_history_financials` | `human_manager_id, year` | Team finances under your management |

### Messages & Trades

| Table | Key Columns | Description |
|-------|-------------|-------------|
| `messages` (6K) | `message_id`, player_ids, team_ids | In-game messages/notifications |
| `trade_history` (158) | date, team_id_0, team_id_1 | Trade log with up to 10 players and 5 draft picks per side |

### Notable Column Conventions

#### Enum Values
- `split_id` **in player career tables** — **behavior differs by table** (OOTP export quirk; do not assume one rule for all three):
  - **`players_career_batting_stats` and `players_career_pitching_stats`:**
    - **`split_id = 1`** = overall regular season for **all** years (real history and simulated seasons **in one bucket**). In typical exports **`split_id = 0` does not appear** — use **`split_id = 1`** for full career batting/pitching totals.
    - **`split_id = 2`** = vs LHP (batting) / vs LHB (pitching); **`3`** = vs RHP / vs RHB; **`21`** = postseason (when present).
    ```sql
    AND split_id = 1         -- overall career batting/pitching (real + sim)
    AND split_id = 2         -- vs LHP/LHB splits only
    AND split_id = 3         -- vs RHP/RHB splits only
    ```
  - **`players_career_fielding_stats`** (different from batting/pitching):
    - OOTP writes **two disjoint era buckets**, commonly **`split_id = 1`** (historical / pre-sim rows) and **`split_id = 0`** (sim-era rows). Year ranges depend on the save; the buckets do not overlap the same `(player_id, year, …)` row.
    - For **all-time** fielding games or totals that must include **both** real history and sim, use **`split_id IN (0, 1)`**. Filtering only **`split_id = 1`** can **drop** all sim-era fielding lines. Import **`SPLIT_CAREER_FIELDING_SIM_ERA`** and **`SPLIT_CAREER_FIELDING_HISTORICAL`** from `ootp_db_constants` when you need named constants.
    ```sql
    AND split_id IN (0, 1)   -- all-time career fielding (both era buckets)
    ```
- `split_id` **in team stats tables** (`team_batting_stats`, `team_pitching_stats`, etc.):
  - 0 = overall/current season
  - 2 = vs LHP, 3 = vs RHP
- `level_id` / `league_level`: 1 = MLB, 2 = AAA, 3 = AA, 4 = High-A/A, 6 = Rookie
- `position`: 1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF
- `role`: 11=Starting Pitcher, 12=Relief Pitcher, 13=Closer
- `bats`/`throws`: 1=Right, 2=Left, 3=Switch (batting only)
- `game_type`: 0=regular season, 2=spring training, 3=playoffs, 4=all-star, 8=futures game
- `scouting_team_id` (in `players_scouted_ratings`): 0 = ground-truth true ratings (coach_id=-1), N = team N's scout view

#### Foreign Key Conventions
- `games.home_team` / `games.away_team`: These are team_ids (not named with `_id` suffix)
- `games.winning_pitcher`, `losing_pitcher`, `save_pitcher`, `starter0`, `starter1`: These are player_ids
- `team_roster_staff` columns (`manager`, `head_scout`, etc.): These are coach_ids
- `projected_starting_pitchers` columns (`starter_0` through `starter_7`): These are player_ids

#### Stat Abbreviations
- Batting: pa=plate appearances, ab=at bats, h=hits, d=doubles, t=triples, hr=home runs, 
  bb=walks, k=strikeouts, rbi=runs batted in, sb=stolen bases, cs=caught stealing, 
  hp=hit by pitch, sf=sacrifice fly, sh=sacrifice hit, gdp=grounded into double play, 
  ibb=intentional walks, ci=catcher interference, wpa=win probability added, 
  war=wins above replacement, ubr=ultimate base running
- Pitching: ip=innings pitched, ha=hits allowed, k=strikeouts, bb=walks, er=earned runs, 
  hra=home runs allowed, bf=batters faced, gs=games started, qs=quality starts, s=saves, 
  hld=holds, bs=blown saves, cg=complete games, sho=shutouts, era=earned run average, 
  whip=walks+hits per IP, fip=fielding independent pitching, babip=batting average on balls in play

### Data Availability & Limitations

#### What the CSV Export Includes vs What's Computed In-Game
The OOTP CSV export only contains **raw counting stats** at the player level. Advanced 
rate stats visible in-game (OPS+, wRC+, etc.) are computed by the game engine and NOT 
exported. However, they can be approximated from the raw data.

**Player career stats** (`players_career_batting_stats`, `players_career_pitching_stats`):
- Counting stats only: AB, H, 2B, 3B, HR, BB, K, RBI, SB, CS, etc.
- Plus: WAR, WPA, UBR
- NO rate stats: no AVG, OBP, SLG, OPS, BABIP, wOBA, OPS+, wRC+

**Team-level stats** (`team_batting_stats`, `team_history_batting_stats`):
- All counting stats PLUS rate stats: avg, obp, slg, ops, woba, iso, rc, rc27

**League-level stats** (`league_history_batting_stats`):
- All of the above PLUS: babip, kp (K%), bbp (BB%)

**Per-at-bat Statcast data** (`players_at_bat_batting_stats`):
- exit_velo, launch_angle, sprint_speed per at-bat
- **Current season only** — overwritten each CSV export

#### Calculating Advanced Stats from Raw Data
To compute rate stats for individual players, calculate from counting stats:
- `AVG = h / ab`
- `OBP = (h + bb + hp) / (ab + bb + hp + sf)`
- `SLG = (s + 2*d + 3*t + 4*hr) / ab` (where s = h - d - t - hr)
- `ISO = SLG - AVG`
- `BABIP = (h - hr) / (ab - k - hr + sf)`
- `OPS+ = 100 * (OBP/lgOBP + SLG/lgSLG - 1)` — use league averages from 
  `league_history_batting_stats` or computed from `team_batting_stats`
  Note: OOTP's in-game OPS+ also applies park factors; exact methodology is undocumented, 
  so computed values may differ by a few points from in-game values.

#### Park Factors
The `parks` table contains park factors as multipliers centered on 1.0:
- `avg`, `avg_l`, `avg_r`: batting average factors (overall/vs LHP/vs RHP)
- `d`, `t`, `hr`, `hr_l`, `hr_r`: extra-base hit factors
- These are the static park configuration values; OOTP's in-game park factor for OPS+ 
  calculations may differ (possibly computed from actual game results).

#### Current-Season-Only Tables
These tables are overwritten on each CSV export and only contain the current season:
- `league_playoff_fixtures` — current season playoff bracket only (no historical brackets)
- `games`, `games_score`, `game_logs` — current season games only
- `players_game_batting`, `players_game_pitching_stats` — current season game logs
- `players_at_bat_batting_stats` — current season at-bat data with Statcast metrics
- `team_record`, `team_batting_stats`, `team_pitching_stats`, etc. — current season

#### Historical Tables (preserved across seasons)
- `players_career_batting_stats` / `pitching` / `fielding` — full year-by-year career stats
- `team_history*` — year-by-year team records, stats, finances
- `league_history*` — year-by-year league stats, award winners, all-stars
- `team_history` — tracks `made_playoffs` and `won_playoffs` per year, but NOT 
  which teams played each other in each round

## Skill Architecture

Each skill has two parts:

- **`skills/<skill-name>/prompt.md`** — the LLM-neutral prompt that any model can follow.
  This is the source of truth for what the skill does.
- **An LLM adapter** — a thin per-tool config that exposes the skill for invocation and
  passes arguments to the prompt. When adding support for a new LLM, create a parallel
  adapter that loads the same prompt.md.

All eight OOTP skills follow this architecture. Follow these rules exactly when creating or
modifying any skill.

### The Division of Responsibility

**Python does** (deterministic, no LLM needed):
- Cache check — return existing report if it's newer than the last import
- All DB queries
- All HTML generation (structure, tables, CSS, color coding)
- File write

**Agent does** (requires LLM judgment):
- Parse `$ARGUMENTS` into parameters (player name, focus modifiers, NL criteria)
- For `/free-agents` only: translate NL → SQL WHERE/JOIN/highlight
- Write LLM analysis text into HTML placeholder comments
- Run `open <path>` to open the browser
- Print the 2–3 line terminal summary

The agent **never** queries the database directly and **never** generates HTML structure.

### CACHED:/GENERATED: Protocol

Every Python entry point prints exactly one of:
```
CACHED:/absolute/path/to/report.html
GENERATED:/absolute/path/to/report.html
```

On `CACHED:` — agent runs `open <path>`, prints one-liner, **STOP**.
On `GENERATED:` — agent writes analysis into the placeholder, then opens, then prints summary.

### HTML Placeholders

Each report type has one placeholder the agent fills in:
- `/player-stats` → `<!-- BATTING_SUMMARY -->` and/or `<!-- PITCHING_SUMMARY -->`
- `/player-rating` → `<!-- RATING_SUMMARY -->`
- `/free-agents` → `<!-- FA_CALLOUT_SUMMARY -->`

The agent reads the file, replaces the placeholder comment with the analysis HTML, writes
it back. It never rewrites any other part of the file.

### `open` Command Rules

- **Always use the full absolute path** — never a relative path or `<placeholder>`
- The orchestrator (the LLM in the outer conversation) knows the player's ID and filename
  from prior runs and hardcodes it in the agent prompt
- For a new player the orchestrator doesn't know yet, instruct the agent to use the path
  printed after `GENERATED:` — make this explicit: *"open the path printed after GENERATED:"*
- A bash `open` block must appear in the prompt.md for **every** exit branch (CACHED and GENERATED)

### Context Isolation

Every skill's prompt.md must include a **Context isolation** section near the top:

```
## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the arguments to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.
```

This prevents context bleedover when running multiple skills in the same session. If a
sub-agent mechanism is available (e.g. a tool that supports spawning isolated sub-agents),
the LLM will use it for hard isolation. If not, the prompt instruction provides a best-effort reset.

### Python Entry Point Conventions

Entry points live in `src/` and follow this pattern:

```python
def generate_<type>_report(save_name, ...):
    existing = find_existing_<type>_report(...)
    if existing:
        return existing, None          # None = cache hit signal

    # ... queries, HTML generation ...

    report_path.write_text(html)
    return str(report_path), data_dict  # data_dict for agent terminal summary
```

- Return `(path, None)` on cache hit
- Return `(path, data_dict)` on generation
- `data_dict` contains the key stats the agent needs for its terminal summary
- CSS: use the shared `get_report_css()` from `src/shared_css.py` for visual consistency
- Reports go under `PROJECT_ROOT / "reports" / "<type>/"`

### Domain packages and module split (ratings model)

When new Python work combines **batch / ETL** (derived tables, pandas, heavy merges), **per-request queries** (skills, MCP, server), and **HTML reports** (cache, templates), **do not** keep everything in one huge `src/<thing>.py`. Follow the layout used by **`src/ratings/`**:

| Piece | Role | Typical module |
|-------|------|----------------|
| **Shared constants** | Maps, weight dicts, column names used by both batch and report/query paths | `constants.py` |
| **Tiny shared helpers** | Letter grades, one-liners with no heavy imports | e.g. `grades.py` |
| **Batch / compute** | Load frames, scoring, `to_sql`, CLI `main()` | `compute.py` |
| **Query / skill API** | Read-only assembly for agents (names, focus modifiers, MCP helpers) | `queries.py` |
| **Report** | Cache check, HTML generation, `write_report_html` | `report.py` |
| **CLI** | `python -m <package>` from `src/` | `__main__.py` delegates to `compute.main()` (or equivalent) |

**Conventions:**

- **Package location:** `src/<domain>/` as a proper package (`__init__.py`). Do **not** place `src/<domain>.py` next to `src/<domain>/` — Python import ambiguity.
- **Invocation:** Run batch jobs as `( cd src && python -m <domain> <save_name> )`. Wire `import.sh` / `import.bat` the same way as `ratings`.
- **Public API:** Re-export stable names from `__init__.py` (`from domain import generate_*_report`, `query_*`, …) so `server.py`, MCP, and skills keep simple imports.
- **Lazy imports:** If the package pulls in **pandas / numpy** only for batch compute, use **`__getattr__`** in `__init__.py` (see `src/ratings/__init__.py`) so `import <domain>` or `from <domain> import query_*` does **not** load the heavy submodule until something like `main` or `compute_*` is accessed.
- **Cross-cutting config** stays in **`config.py`**, **`ootp_db_constants.py`**, and **`shared_css.py`**; do not introduce repo-wide folders like `src/compute/` or `src/reports/` that scatter one feature across layers.

Legacy single-file scripts (`analytics.py`, `free_agents.py`, …) are fine until a change touches enough surface area to justify a package; **new large features** should start as or migrate to this model.

### `/free-agents` Highlight Columns

The `generate_free_agents_report` function accepts a `highlight` parameter — a list of
`(col_key, display_label)` tuples that add extra stat columns to the table:

```python
highlight = [("rating_defense", "Defense")]
path, rows = generate_free_agents_report(..., highlight=highlight)
```

The agent picks highlight columns based on the query focus (see prompt.md mapping table).
Maximum 2 highlight columns per search. Column keys come from `player_ratings`.

### Visual Style (all reports)

- CSS via `shared_css.py` — consistent font, table styles, color classes
- Table headers: `background: #2c3e50; color: white`
- Striped rows: `tr:nth-child(even) td { background: #f0f4f8 }`
- Hover: `tr:hover td { background: #e0e8f0 }`
- Score colors: green ≥70, yellow 40–69, red <40
- Classes: `.good` (green bold), `.poor` (red bold), `.summary` (left-bordered callout)

---

## Player Ratings Table (`player_ratings`)

Computed by `src/ratings/` — run after `analytics.py`. Contains one row per MLB-level
player with composite 0–100 ratings. **Use this table, not `players_value`, when ranking
or comparing players.**

```bash
( cd src && ../.venv/bin/python3 -m ratings My-Save-2026 )
```

**Identity:** `player_id`, `first_name`, `last_name`, `team_abbr`, `position`, `age`,
`oa` (OOTP overall), `pot` (OOTP potential), `player_type` ("batter" or "pitcher")

**Composite ratings (0–100 scale):**
- `rating_overall` — primary composite score; blends current production + trade upside (potential) + clubhouse; use this to rank players by asset value
- `rating_now` — **Performance** rating: on-field dimensions + durability + baserunning (batters) or role value (pitchers); excludes potential, clubhouse, and development traits (weights renormalized)
- `rating_ceiling` — raw ceiling gap score (0–100), age-independent; `(pot - oa) * 5`; use this to find upside; compute `rating_ceiling - rating_now` for the biggest gap players
- `rating_offense` — hitting value
- `rating_contact_quality` — contact + exit velocity
- `rating_discipline` — walk/strikeout approach
- `rating_defense` — fielding at primary position
- `rating_potential` — **Trade** upside: `rating_ceiling` × development-trait realization multiplier × age runway (`DEVELOPMENT_REALIZATION_MULT_*`, `DEVELOPMENT_TRAIT_WEIGHT_*`, `DEVELOPMENT_MIN_AGE` / `DEVELOPMENT_MAX_AGE` / `DEVELOPMENT_EXPONENT` in `config.py`)
- `rating_durability` — injury resistance
- `rating_development` — 0–100 trait blend (work ethic, intelligence / baseball IQ, adaptability); drives the multiplier inside `rating_potential` and is **not** a separate additive weight in `rating_overall`
- `rating_clubhouse` — personality/leadership (Trade/Contract only — not in `rating_now`)
- `rating_baserunning` — speed and baserunning

**Confidence:** `confidence` (float, 0.0–1.0) — how much statistical backing the rating has.
- `1.0` when CUR scouted ratings were available (Player Rating Scales → Current Ratings Scale not None). Score is anchored to current ability.
- `< 1.0` when CUR was unavailable: uses the PA/IP regression ramp (`(career_pa / 500) ** 0.88` for batters, `(career_ip / 100) ** 0.88` for pitchers). Score is stats-only; low-sample players will be noisy.
- Filter or rank: `WHERE confidence >= 0.7`, or `ORDER BY rating_overall * confidence DESC`.

**Flags:** `flag_injury_risk` (bool), `flag_leader` (bool), `flag_high_ceiling` (bool)

**Carried-over stats:** `wrc_plus`, `war`, `prone_overall`

---

## Draft Ratings Tables (`draft_ratings`, `draft_ratings_1/2/3`)

Computed by `src/draft_ratings.py` — run after import. Contains one row per draft-eligible
prospect, rated on a 0–100 composite scale. Covers all four upcoming draft classes.

```bash
.venv/bin/python3 src/draft_ratings.py <save_name>
```

### Table naming — relative offset, not calendar year

Tables are named by **offset from the current sim year**, not by calendar year, so the
names remain stable across sim advances:

| Table | Offset | HSC pool constants |
|-------|--------|-------------------|
| `draft_ratings` | +0 (current draft) | `HSC_CURRENT_POOL` = (4, 5, 6, 9, 10) |
| `draft_ratings_1` | +1 year out | `HSC_FUTURE_1` = (3, 8) |
| `draft_ratings_2` | +2 years out | `HSC_FUTURE_2` = (2, 7) |
| `draft_ratings_3` | +3 years out | `HSC_FUTURE_3` = (1,) |

All four constants are defined in `src/ootp_db_constants.py`.

**Mapping a calendar year to an offset:** `team_history` stores the last *completed* season,
so the current draft year = `MAX(year) + 1`. Offset = requested_year − current_draft_year.
Query: `SELECT MAX(year) FROM team_history WHERE league_id = 203`
Example: MAX(year)=2025 → current draft year=2026. User asks for 2029 → offset=3 → `draft_ratings_3`.

### Schema (all four tables share the same columns)

**Identity:** `player_id`, `first_name`, `last_name`, `position`, `age`, `player_type`
("batter" or "pitcher"), `bats`, `throws`, `college` (1=COL, 0=HS), `domestic`
(1=USA, 0=international), `oa`, `pot`, `talent_value`

**Composite ratings (0–100):** `rating_overall`, `rating_ceiling`, `rating_tools`,
`rating_development`, `rating_defense`, `rating_proximity`

**Flags:** `flag_elite_ceiling` (pot≥65), `flag_high_ceiling` (pot≥55),
`flag_elite_we`, `flag_elite_iq`, `flag_demanding`, `flag_international`, `flag_hs`

**Personality:** `work_ethic`, `intelligence`, `greed`

---

## Analytics Engine (`src/analytics.py`)

Run after import to compute advanced stats:
```bash
.venv/bin/python3 src/analytics.py My-Save-2026
```

Produces two tables with overall + vs LHP/RHP splits:

### `batter_advanced_stats` (one row per MLB batter)
- **Identity:** player_id, first_name, last_name, team_abbr, position
- **Career (from counting stats):** g, pa, ab, h, r, rbi, hr, sb, bb, k, 
  ba, obp, slg, ops, iso, k_pct, bb_pct, babip, woba, wrc_plus, ops_plus, war, wpa
- **Contact quality (current season at-bat data):** batted_balls, avg_ev, max_ev, 
  hard_hit_pct, barrel_pct, sweet_spot_pct, gb_pct, ld_pct, fb_pct, 
  xba, xslg, xwoba, xbacon
- **L/R splits:** pa, ab, ba, obp, slg, iso, k_pct, bb_pct, woba, wrc_plus with `_vs_lhp` / `_vs_rhp`
  suffixes; contact quality columns (batted_balls, avg_ev, max_ev, avg_la, hard_hit_pct, barrel_pct,
  sweet_spot_pct, gb_pct, ld_pct, fb_pct, xbacon, xwoba, xba, xslg) also with `_vs_lhp` / `_vs_rhp`
  — Note: the batting average split column is `ba_vs_lhp` / `ba_vs_rhp`, NOT `avg_vs_lhp`

### `pitcher_advanced_stats` (one row per MLB pitcher)
- **Identity:** player_id, first_name, last_name, team_abbr, position
- **Career:** g, gs, w, l, s, hld, ip, bf, era, fip, xfip, k_pct, bb_pct, 
  k_bb_pct, whip, k_9, bb_9, hr_9, babip, gb_pct, war, wpa
- **Contact allowed (current season):** bb_against, avg_ev_against, 
  hard_hit_pct_against, barrel_pct_against, xba_against, xwoba_against
- **L/R splits:** career stats with `_vs_lhb` / `_vs_rhb` suffixes

### Advanced Stats Ready Reckoner

| Hitting Stat | Good | Average | Poor |
|-------------|------|---------|------|
| wRC+ | 115+ | 100 | <85 |
| wOBA | .360+ | .320 | <.300 |
| xwOBA | .360+ | .320 | <.300 |
| OPS+ | 115+ | 100 | <85 |
| K% | <18% | ~22% | >28% |
| BB% | 10%+ | ~8% | <6% |
| ISO | .200+ | .170 | <.120 |
| Avg EV | 92+ | 88-90 | <86 |
| Hard Hit% | 45%+ | ~39% | <32% |
| Barrel% | 10%+ | ~6-7% | <4% |
| xBA | .280+ | ~.250 | <.220 |
| xSLG | .480+ | ~.400 | <.350 |
| BABIP | context | ~.300 | context |

| Pitching Stat | Good | Average | Poor |
|--------------|------|---------|------|
| FIP | <3.50 | ~4.00 | >4.50 |
| xFIP | <3.60 | ~4.00 | >4.50 |
| K-BB% | 18%+ | ~14% | <8% |
| K% | 27%+ | ~22% | <18% |
| BB% | <6% | ~8% | >10% |
| WHIP | <1.15 | ~1.30 | >1.40 |
| HR/9 | <0.9 | ~1.1 | >1.4 |
| GB% | 47%+ | ~43% | <38% |
| Barrel% allowed | <6% | ~7-8% | >10% |
| Hard Hit% allowed | <34% | ~39% | >42% |
| xwOBA allowed | <.290 | ~.320 | >.340 |

### Stats NOT computable from OOTP export
- O-Swing%, Z-Contact%, SwStr%, Whiff%, Contact% — no per-pitch zone data
- Pitch value by type (Fastball/Breaking/Offspeed RV) — no pitch type in at-bat data
- Stuff+ — OOTP internal model only
- OAA, DRS, FRV, UZR — no play-level fielding data
- Catcher framing/blocking runs — no pitch-level catcher data
- For these, use OOTP's internal player ratings as proxies