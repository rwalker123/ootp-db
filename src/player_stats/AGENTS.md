---
paths:
  - "src/player_stats/**"
---

## Player Stats Package Developer Context (`src/player_stats/`)

Generates the HTML player report for the `/player-stats` skill. Replaces the old
`src/report.py` monolith.

### Module layout

| Module | Purpose |
|--------|---------|
| `rates.py` | Pure rate-stat calculators: `calc_rates`, `calc_pitching_rates` — no DB, no imports except `config` |
| `fetch.py` | DB fetch functions: `fetch_common_data`, `fetch_batter_data`, `fetch_fielding_stats`, `fetch_pitcher_data` — all accept an open `conn` |
| `report.py` | HTML generators, formatting helpers, `find_existing_report`, `generate_player_report` |
| `__init__.py` | Re-exports `generate_player_report` and `find_existing_report` |

### Public API

```python
from player_stats import generate_player_report, find_existing_report

path, data = generate_player_report(save_name, first_name, last_name, raw_args="")
path = find_existing_report(save_name, first_name, last_name, raw_args="")
```

`generate_player_report` returns `(report_path, data_dict)`. On a cache hit,
`data_dict` is `None`. `server.py` uses the lazy import form inside `_run_data`.

### Tables read (not written)

`players`, `players_batting`, `players_pitching`, `players_fielding`,
`players_value`, `players_scouted_ratings`, `players_career_batting_stats`,
`players_career_pitching_stats`, `players_career_fielding_stats`,
`batter_advanced_stats`, `batter_advanced_stats_history`,
`pitcher_advanced_stats`, `pitcher_advanced_stats_history`,
`team_batting_stats`, `team_pitching_stats`, `team_history_batting_stats`,
`team_history_pitching_stats`, `teams`, `team_history`
