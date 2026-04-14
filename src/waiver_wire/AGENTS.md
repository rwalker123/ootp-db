---
paths:
  - "src/waiver_wire/**"
---

## Waiver Wire Package Developer Context (`src/waiver_wire/`)

This file is for developers modifying the package. Skill execution context (placeholder,
recommendation format, output fields) lives in `skills/waiver-claim/prompt.md`.

### Module layout

| Module | Role |
|--------|------|
| `formatting.py` | Pure helpers: `fmt_salary`, `get_current_salary`, `get_years_remaining`, `letter_grade`, `grade_badge`, `score_color`, `injury_label`, `injury_color`, `trait_label`, `arb_status_label`, `_score_td`, `_war_td`, `_fmt_pct` |
| `queries.py` | All DB query functions (`_lookup_player`, `_get_incumbents`, `_get_advanced_stats_batter/pitcher`, `_get_fielding_positions/details`, `_get_40man_count`, `_get_team_name`) and public `query_waiver_claim` |
| `report.py` | Cache check (`find_existing_waiver_report`), all `_build_*` HTML section builders, and public `generate_waiver_claim_report` |
| `__init__.py` | Lazy `__getattr__` — `import waiver_wire` does not pull submodules until needed |

### Public API

```python
from waiver_wire import generate_waiver_claim_report, query_waiver_claim
```

- `generate_waiver_claim_report(save_name, first_name, last_name, raw_args="")` —
  returns `(path_str, data_dict)` on generation, `(path_str, None)` on cache hit,
  `(None, None)` if player not found.
- `query_waiver_claim(save_name, first_name, last_name)` —
  returns full data dict (with `_candidate`, `_adv`, `_incumbents`, `_field_positions`,
  `_fielding_details`, `_roster_count`, `_player_id`, `_player_type`, `_position`,
  `_player_role`, `_comparison_positions`, `_my_team_name` private keys), or `None` if
  player not found.

### HTML placeholder

```
<!-- WAIVER_RECOMMENDATION -->
```

Agent replaces this after `GENERATED:`. On `CACHED:` — open and print one-liner, stop.

### Tables read

- `players` — bio, bats/throws, team, injury status, personality
- `player_ratings` — composite ratings, flags, personality traits, team_abbr
- `players_roster_status` — waiver/DFA status, service time, options
- `players_contract` — salary schedule (`salary0`–`salary9`), years, current_year, no_trade
- `players_fielding` — position ratings and fielding component ratings
- `team_roster` — roster membership (list_id=1 = 40-man)
- `batter_advanced_stats` — hitting stats, contact quality, platoon splits
- `pitcher_advanced_stats` — pitching stats, contact allowed, platoon splits
- `teams` — team name/nickname

### Position grouping for incumbent comparison

| Group | Positions |
|-------|-----------|
| `PITCHER_POS` | {1} |
| `OF_POS` | {7, 8, 9} |
| `CORNER_IF_POS` | {3, 5} |
| `MIDDLE_IF_POS` | {4, 6} |

Pitchers are further split by role: SP (role=11) vs RP/CL (role=12/13).
