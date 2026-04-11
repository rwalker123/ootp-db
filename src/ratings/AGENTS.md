---
paths:
  - "src/ratings/**"
---

## Ratings Package Developer Context (`src/ratings/`)

The `player_ratings` table schema (columns, confidence, flags) lives in root `AGENTS.md`
under **Player Ratings Table** — that's the query-time reference. This file covers
package internals for developers modifying the ratings engine.

### Module layout

| Module | Role |
|--------|------|
| `constants.py` | Weight dicts, development trait multipliers, age bounds — all tunable values |
| `grades.py` | `letter_grade()` and badge helpers shared across compute and report |
| `defense_blend.py` | Position-specific fielding rating blends |
| `compute.py` | Loads `batter_advanced_stats` / `pitcher_advanced_stats`, scores players, writes `player_ratings` via `to_sql` |
| `queries.py` | Read-only assembly for skills and MCP (`query_player_rating`, focus modifiers) |
| `report.py` | Cache check, HTML generation, `generate_player_rating_report` |
| `__init__.py` | Lazy `__getattr__` — `import ratings` does not pull pandas until `compute` is accessed |
| `__main__.py` | `python -m ratings <save_name>` — delegates to `compute.main()` |

### Invocation

```bash
( cd src && ../.venv/bin/python3 -m ratings My-Save-2026 )
```

Run after `analytics.py`. Reads `batter_advanced_stats` and `pitcher_advanced_stats`;
writes (replaces) `player_ratings`.

### Tuning weights

All scoring weights and thresholds are in `constants.py`. Key groups:
- `BATTER_WEIGHTS` / `PITCHER_WEIGHTS` — dimension weights for `rating_overall`
- `DEVELOPMENT_REALIZATION_MULT_*` — multipliers by development trait tier
- `DEVELOPMENT_TRAIT_WEIGHT_*` — blend weights for `rating_development`
- `DEVELOPMENT_MIN_AGE` / `DEVELOPMENT_MAX_AGE` / `DEVELOPMENT_EXPONENT` — age runway curve for `rating_potential`

Do not put thresholds in `compute.py` — keep them in `constants.py` so they're tunable
without reading compute logic.

### HTML placeholder

```
<!-- RATING_SUMMARY -->
```

Agent replaces this after `GENERATED:`. On `CACHED:` — open and print one-liner, stop.
