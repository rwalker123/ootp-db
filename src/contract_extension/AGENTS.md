---
paths:
  - "src/contract_extension/**"
---

## Contract Extension Package Developer Context (`src/contract_extension/`)

This file is for developers modifying the package. Skill execution context (placeholder,
recommendation format, output fields) lives in `skills/contract-extension/prompt.md`.

### Module layout

| Module | Role |
|--------|------|
| `formatting.py` | Pure helpers: `letter_grade`, `grade_badge`, `fmt_salary`, injury/trait/pop labels and colors, `safe_div`, salary accessors, `_fmt_score_cell`, `_f1/_f2/_f3`, `_pct`, `_ev_color`, `_pct_color`, `_xwoba_color` |
| `tables.py` | HTML table row builders (`build_war_table_batter/pitcher`, `build_adv_stats_*_table`, `build_comps_table`) and scalar extractors (`_compute_war_vals_*`, `_compute_adv_most_recent_*`, `_compute_comp_scalars`, `_adv_data_dict`) |
| `queries.py` | `_lookup_player_id`, `query_contract_extension` — all DB access |
| `report.py` | Cache check, HTML assembly, `generate_contract_extension_report` |
| `__init__.py` | Lazy `__getattr__` — `import contract_extension` does not pull submodules until needed |

### Public API

```python
from contract_extension import generate_contract_extension_report, query_contract_extension
```

- `generate_contract_extension_report(save_name, first_name, last_name, raw_args="")` —
  returns `(path_str, data_dict)` on generation, `(path_str, None)` on cache hit,
  `(None, None)` if player not found.
- `query_contract_extension(save_name, first_name, last_name)` —
  returns full data dict (with `_war_rows`, `_adv_rows`, `_comp_rows`, `_player_row_d`,
  `_player_id` private keys), or `None` if player not found.

### HTML placeholder

```
<!-- CONTRACT_EXTENSION_SUMMARY -->
```

Agent replaces this after `GENERATED:`. On `CACHED:` — open and print one-liner, stop.

### Tables read

- `player_ratings` — composite ratings, flags, personality traits
- `players` — bio, bats/throws, team, popularity, personality
- `teams` — team name/nickname/abbr
- `players_contract` — salary schedule (`salary0`–`salary9`), years, current_year, no_trade
- `players_roster_status` — `mlb_service_years`
- `players_career_batting_stats` — WAR trend (last 5 MLB seasons, `split_id=SPLIT_CAREER_OVERALL`)
- `players_career_pitching_stats` — WAR trend (pitchers, same filter)
- `batter_advanced_stats_history` — contact quality year-over-year (last 3 years)
- `pitcher_advanced_stats_history` — contact quality allowed year-over-year (last 3 years)
