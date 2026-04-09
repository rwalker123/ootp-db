# OOTP Database — Copilot Instructions

## Project Overview

A Python CLI that imports OOTP Baseball CSV dumps into PostgreSQL. Post-import analytics
(`src/analytics.py`, `src/ratings.py`) compute advanced stats and composite player ratings.
Claude Code skills (`.claude/skills/`) are the primary UX layer on top of the DB.

---

## Environment & DB Connection

- Always use `.venv/bin/python3` — never `python3` or `source .venv/bin/activate`
- Read the active save from `saves.json`:
  ```python
  import json
  save_name = json.loads(open("saves.json").read())["active"]
  db_name = save_name.lower().replace("-", "_").replace(" ", "_")
  ```
- Build SQLAlchemy engine:
  ```python
  from dotenv import load_dotenv; load_dotenv(".env")
  engine = create_engine(os.getenv("POSTGRES_URL").rstrip("/") + "/" + db_name)
  ```
- SQL heredoc pattern (never use `-c` with inline strings):
  ```bash
  .venv/bin/python3 << 'PYEOF'
  from sqlalchemy import create_engine, text
  # ... queries here ...
  PYEOF
  ```
- Never use `{"key": val}` dicts in heredocs — Claude Code's tool sandbox flags bare `{...}` as
  suspicious even in quoted heredocs (`<< 'PYEOF'`). Use `dict(key=val)` instead.

---

## Critical Schema Rules

**Always filter `league_id = 203` for MLB** unless the user explicitly asks about minors.

**`split_id` in player career tables** — rules **differ by table** (see `AGENTS.md`):
- **`players_career_batting_stats` / `players_career_pitching_stats`:** `split_id = 1` = overall regular season (real + sim). **`split_id = 0` does not appear** in typical exports — use **`split_id = 1`** for career totals. `2` / `3` = vs L/R splits.
- **`players_career_fielding_stats`:** OOTP uses **both** `0` and `1` as disjoint era buckets. For all-time fielding totals spanning both, use **`split_id IN (0, 1)`**; `1` alone can omit sim-era rows. Constants: `SPLIT_CAREER_FIELDING_SIM_ERA`, `SPLIT_CAREER_FIELDING_HISTORICAL` in `ootp_db_constants.py`.

**Player quality vs trade value**:
- Rank/compare by `player_ratings.rating_overall` (0–100 composite) — never `players_value.oa`
- `players_value.oa` (20–80 scale) is the trade valuation currency

**Current vs historical**: Current season in main tables (`team_record`, `team_batting_stats`);
prior seasons in `_history` tables (`team_history_record`, etc.).

---

## Key Tables

| Table | Purpose |
|-------|---------|
| `players` | Bio, demographics, injury status, personality |
| `players_batting` / `players_pitching` / `players_fielding` | Ratings (20-80 scale) |
| `players_value` | OOTP OA/POT ratings + computed values; OA used for trade bands |
| `players_contract` / `players_roster_status` | Contract details, service time, arb status |
| `player_ratings` | Computed 0-100 composite scores — **use for ranking players** |
| `batter_advanced_stats` | xwoba, barrel%, hard hit%, wRC+, OPS+, FIP per player |
| `pitcher_advanced_stats` | FIP, xFIP, K-BB%, xwOBA allowed per pitcher |
| `players_career_batting_stats` / `players_career_pitching_stats` | Career splits: overall = `split_id = 1` (no `0` in export) |
| `players_career_fielding_stats` | All-time fielding: often `split_id IN (0, 1)` — see `AGENTS.md` |
| `team_record` / `team_batting_stats` / `team_pitching_stats` | Current season team stats |

`player_ratings` columns: `rating_overall`, `rating_offense`, `rating_defense`,
`rating_contact_quality`, `rating_discipline`, `rating_potential`, `rating_durability`,
`rating_development`, `rating_clubhouse`, `rating_baserunning`

---

## Enum Quick Reference

- `position`: 1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF
- `bats` / `throws`: 1=R, 2=L, 3=S (switch)
- `level_id`: 1=MLB, 2=AAA, 3=AA, 4=A, 6=Rookie
- `role`: 11=SP, 12=RP, 13=Closer
- `split_id` (team stats): 0=overall, 2=vs LHP, 3=vs RHP

---

## Skill Architecture

Skills in `.claude/skills/<name>/SKILL.md` each delegate to a fresh `general-purpose` agent
(model: `sonnet`) — never inline the task in the outer conversation.

Python entry points (`src/<type>.py`) follow this return contract:
- Cache hit → `return (str(path), None)`
- New report → `return (str(path), data_dict)`

The agent fills HTML placeholder comments (e.g. `<!-- BATTING_SUMMARY -->`) and never
rewrites surrounding HTML. Shared CSS lives in `src/shared_css.py`. Reports go to `reports/<type>/`.

Every skill must print `CACHED:<path>` or `GENERATED:<path>` and call `open <absolute_path>`
for both exit branches.
