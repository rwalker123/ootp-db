# Ad-hoc OOTP Database Query

Answer an ad-hoc question about the OOTP Baseball database expressed in plain English.

## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the question to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.

## Argument substitution

`$ARGUMENTS` is the full text of the user's question (e.g. "who leads the league in home runs?").
Answer the question as stated — do not rephrase, reframe, or extend it.

## Usage

```
/adhoc who leads the league in home runs?
/adhoc what is the Tigers' current record?
/adhoc which pitcher has the lowest ERA this season?
```

Answer: **"$ARGUMENTS"**

---

## Hard Rules — Read These Before Writing Any Code

### 1. Use the Python heredoc pattern — always
```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from sqlalchemy import text
from shared_css import get_engine, load_saves_registry
save = load_saves_registry()["active"]
engine = get_engine(save)
with engine.connect() as conn:
    rows = conn.execute(text("SELECT ...")).fetchall()
    for r in rows:
        print(r)
PYEOF
```

### 2. Never read `.env`
The `.env` file contains API keys. Never `cat` it, never open it, never read it.
All DB access goes through `get_engine()` and `load_saves_registry()` — they handle config internally.

### 3. No `{}` or f-strings in heredocs
The shell flags curly braces as suspicious. Use `dict(key=val)` for query parameters,
never `{"key": val}` or f-strings with `{variable}`:
```python
# CORRECT
rows = conn.execute(text("SELECT ... WHERE league_id = :lid"), dict(lid=MLB_LEAGUE_ID)).fetchall()

# WRONG — curly braces blocked in heredoc
rows = conn.execute(text("SELECT ..."), {"lid": 203}).fetchall()
```

### 4. Use `ootp_db_constants.py` for all OOTP enum values
Never hardcode magic numbers. Import constants from `src/ootp_db_constants.py`:
```python
from ootp_db_constants import MLB_LEAGUE_ID, MLB_LEVEL_ID, SPLIT_CAREER_OVERALL
```
Always filter by `league_id = MLB_LEAGUE_ID` unless the question explicitly asks about
minor leagues.

### 5. Use only documented column names
Do not explore the database schema at runtime (`PRAGMA table_info`, `information_schema`,
`\d tablename`, etc.). The schema is fully documented in `AGENTS.md`. Read that section
if unsure — do not guess column names.

### 6. `players_contract` salary columns
`players_contract` has **no** bare `salary` column. Salary columns are `salary0` through
`salary14` (one per contract year). Use `salary0` for the current year's salary.

### 7. Filter career stats correctly
In `players_career_batting_stats` and `players_career_pitching_stats`:
- `split_id = 1` → overall (all seasons — use this for career totals)
- `split_id = 2` → vs LHP/LHB splits
- `split_id = 3` → vs RHP/RHB splits
- `split_id = 0` does **not** exist

### 8. MLB-level players only (unless asked otherwise)
`player_ratings` is already pre-filtered to MLB players. For raw tables, filter:
```python
AND league_id = MLB_LEAGUE_ID
```

### 9. Use `player_ratings.rating_overall` for ranking
When listing or ranking players by quality, use `player_ratings.rating_overall`
(composite 0–100 score), not `players_value.oa` or `players_value.oa_rating`.

### 10. Do not explore the filesystem
Do not `ls`, `find`, `glob`, or otherwise explore directories to answer the question.
All relevant code entry points are in `src/`. The schema is in `AGENTS.md`.

---

## Step 1: Identify the relevant tables

From the question, determine which tables are needed. Common mappings:

| Question type | Tables |
|--------------|--------|
| Player stats (batting) | `players_career_batting_stats` joined to `players` |
| Player stats (pitching) | `players_career_pitching_stats` joined to `players` |
| Player ratings / ranking | `player_ratings` |
| Team standings / record | `team_record` joined to `teams` |
| Team batting/pitching | `team_batting_stats` / `team_pitching_stats` |
| Free agents | `player_ratings` WHERE `team_id IS NULL` or via `players_roster_status` |
| Contracts / salary | `players_contract` (use `salary0` for current salary) |
| Advanced stats | `batter_advanced_stats` / `pitcher_advanced_stats` |
| Waiver wire | `players_roster_status` |
| Division standings | `team_relations` + `team_record` + `teams` |

For current-season stats, use the main stats tables. For historical data, use `_history` tables.

## Step 2: Write and run the query

Write the query following the hard rules above. Run it via the heredoc pattern.

## Step 3: Print the answer

Present the results as a clean, readable table or summary. Include relevant context
(e.g., "as of the 2026 season", "MLB only"). Do not pad the output with disclaimers.
