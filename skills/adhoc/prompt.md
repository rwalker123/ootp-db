# Ad-hoc OOTP Database Query

Answer an ad-hoc question about the OOTP Baseball database expressed in plain English,
then write the answer as an HTML report.

## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the question to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.

**Never use `open` to launch the report.** Print the `file://` path instead and stop.

## Argument substitution

`$ARGUMENTS` contains two parts separated by `\n\nReport path:`:
- **Question** — everything before `\n\nReport path:` (e.g. "who leads the league in home runs?")
- **Report path** — the absolute file path after `Report path:` (e.g. `/Users/.../reports/adhoc/adhoc-1234567890.html`)

Use the question as the focus of your analysis. Use the report path exactly as given — do not
alter, sanitize, or derive a different path.

## Usage

```
/adhoc who leads the league in home runs?
/adhoc what is the Tigers' current record and how does it compare to last year?
/adhoc which pitchers have improved the most this season?
```

Answer: **"$ARGUMENTS"** (question portion only)

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
The shell flags curly braces as suspicious. Use `dict(key=val)` for query parameters
and string concatenation (`+`) for building HTML — never `{"key": val}`, f-strings with
`{variable}`, or `.format()` calls inside a heredoc:
```python
# CORRECT — dict() for params, + for string building
rows = conn.execute(text("SELECT ... WHERE league_id = :lid"), dict(lid=MLB_LEAGUE_ID)).fetchall()
row_html = row_html + "<tr><td>" + str(r[0]) + "</td></tr>"

# WRONG — curly braces blocked in heredoc
rows = conn.execute(text("SELECT ..."), {"lid": 203}).fetchall()
html = f"<td>{name}</td>"
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

### 11. Print `GENERATED:` as a bare line — no markdown, no prose
After writing the HTML file, print exactly this (and nothing else on that line):
```
GENERATED:/absolute/path/to/file.html
```
No markdown links, no `[text](url)`, no "The report is at ...", no surrounding text.
The line must start with `GENERATED:` — the server scans for this prefix exactly.

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

## Step 2: Query and generate the HTML report

Run one Python heredoc that queries the database, builds the HTML, and writes the file.
Load CSS from `shared_css` — do not inline your own styles.

Use the **report path from $ARGUMENTS** exactly as given for `Path(...)`.

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from sqlalchemy import text
from shared_css import get_engine, load_saves_registry, get_report_css
from ootp_db_constants import MLB_LEAGUE_ID
from pathlib import Path
from datetime import datetime
ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

save = load_saves_registry()["active"]
engine = get_engine(save)
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT <AGENT_FILLS_IN_COLUMNS> FROM <AGENT_FILLS_IN_TABLES> "
        "WHERE league_id = :lid <AGENT_FILLS_IN_MORE_WHERE> "
        "ORDER BY <AGENT_FILLS_IN_ORDER> LIMIT <AGENT_FILLS_IN_LIMIT>"
    ), dict(lid=MLB_LEAGUE_ID)).fetchall()

css = get_report_css()
title = "<AGENT_FILLS_IN_TITLE>"

# Build table rows — string concatenation only, no f-strings or {} in this heredoc
thead = "<tr>" + "".join("<th>" + h + "</th>" for h in [<AGENT_FILLS_IN_HEADER_LIST>]) + "</tr>"
tbody = ""
for r in rows:
    tbody = tbody + "<tr>" + "".join("<td>" + str(c) + "</td>" for c in r) + "</tr>"

# Build full HTML — commentary paragraph(s) written by you as the analyst
commentary = (
    "<p><AGENT_FILLS_IN_COMMENTARY_SENTENCE_1></p>"
    "<p><AGENT_FILLS_IN_COMMENTARY_SENTENCE_2_IF_NEEDED></p>"
)

html = (
    "<!DOCTYPE html><html><head>"
    "<meta charset='utf-8'>"
    "<meta name='ootp-generated' content='" + ts + "'>"
    "<title>" + title + "</title>"
    "<style>" + css + "</style>"
    "</head><body><div class='container'>"
    "<div class='page-header'>"
    "<div class='header-top'><div>"
    "<div class='player-name'>" + title + "</div>"
    "<div class='player-meta'>Ad-hoc &bull; <AGENT_FILLS_IN_SUBTITLE e.g. 'MLB &bull; 2026 Season'></div>"
    "</div></div></div>"
    "<div class='section'>"
    + commentary +
    "<table><thead>" + thead + "</thead><tbody>" + tbody + "</tbody></table>"
    "<p style='color:#888;font-size:0.85em;margin-top:1.5em'>"
    "Ad-hoc reports are not cached — generated fresh each run.</p>"
    "</div></div>"
    "</body></html>"
)

Path("<AGENT_FILLS_IN_REPORT_PATH_FROM_ARGUMENTS>").write_text(html)
print("GENERATED:<AGENT_FILLS_IN_REPORT_PATH_FROM_ARGUMENTS>")
PYEOF
```

**Multiple tables:** If the question requires multiple datasets (e.g. AL leaders + NL leaders,
or batting + pitching), run one query per dataset and concatenate multiple `<table>` blocks
in the HTML before the note paragraph. Add `<h2>` headings to separate sections.

**Commentary:** Write 2–4 sentences of analysis — lead with the key finding, add context
(team, season year, relevant comparisons). Do not pad with disclaimers.

## Step 3: Print the report path

```bash
echo "file://<AGENT_FILLS_IN_REPORT_PATH_FROM_ARGUMENTS>"
```

### Position code reference
1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF
bats: 1=R, 2=L, 3=S  |  throws: 1=R, 2=L
