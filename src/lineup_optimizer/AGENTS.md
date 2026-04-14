---
paths:
  - "src/lineup_optimizer/**"
---

## Lineup Optimizer Package Developer Context (`src/lineup_optimizer/`)

This file is for developers modifying the package. Skill execution context (modes,
philosophy labels, placeholder, argument parsing) lives in `skills/lineup-optimizer/prompt.md`.

### Module layout

| Module | Role |
|--------|------|
| `constants.py` | Package-level constants: PHILOSOPHIES, PHIL_LABELS, WOBA_HP alias |
| `engine.py` | Compute/algorithm functions: lineup logic, positional assignment, scoring |
| `formatting.py` | Display helpers: grade colors, wOBA/wRC color bands, HTML cell renderers |
| `loaders.py` | DB loaders: resolve_team, roster batters, fielding ratings, advanced stats |
| `queries.py` | `query_lineup()` orchestrator — data assembly without HTML |
| `report.py` | `build_html()` + `generate_lineup_report()` entry point |
| `__init__.py` | Lazy `__getattr__` — exposes `generate_lineup_report`, `query_lineup`, `POS_STR_MAP` |
| `__main__.py` | CLI: `python -m lineup_optimizer <save> [philosophy] [L\|R] [team]` |

### Key engine constants (`engine.py`)

| Constant | Value | Meaning |
|----------|-------|---------|
| `MODERN_SLOT_MAP` | `{1:1, 2:0, ...}` | Best hitter at #2 (Tango-optimal) |
| `TRADITIONAL_SLOT_MAP` | `{1:2, 2:3, 3:0, ...}` | Best hitter at #3, cleanup at #4 |
| `WOBA_REG_PA` | 300 | PA credibility threshold for regression blend |
| `MIN_FIELDING_RATING` | 40 | Minimum rating for corner positions |
| `MIN_FIELDING_RATING_PREMIUM` | 50 | Minimum rating for C/2B/SS/CF |
| `MIN_POS_GAMES` | 5 | Minimum career games to qualify at a position |
| `PREMIUM_DEFENSE_POSITIONS` | {2, 4, 6, 8} | C, 2B, SS, CF |
| `BATTER_POSITIONS` | {3, 5, 7, 9} | 1B, 3B, LF, RF — bat-first spots |

### `query_lineup()` return dict

Private keys (`_*`) are consumed by `generate_lineup_report()` and stripped before returning `data_dict` to the agent.

| Key | Type | Description |
|-----|------|-------------|
| `slug` | str | Cache key fragment: `{abbr}_{philosophy}_{hand}_{pos_key}` |
| `lineup_json` | str | JSON array of 9 lineup slots with name/pos/bats/woba/wrc_plus |
| `alternation_score` | int | L/R/S alternation quality 0–10 |
| `avg_lineup_wrc_plus` | float\|None | Mean wRC+ of starting nine |
| `hot_players` / `cold_stars` | str | Comma-separated names for agent summary |
| `_lineup` | dict[int, dict] | slot → player dict with `assigned_pos` |
| `_batters` | list[dict] | Full roster (including bench) for HTML full-roster table |

### `POS_STR_MAP` re-export

`server.py` imports `POS_STR_MAP` from `lineup_optimizer`. The package re-exports it from
`ootp_db_constants` via `__init__.__getattr__` to preserve this import path without duplication.
