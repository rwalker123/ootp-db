---
paths:
  - "src/rotation_analysis/**"
---

## Rotation Analysis Package Developer Context (`src/rotation_analysis/`)

This file is for developers modifying the package. Skill execution context (modes,
placeholder, decision bands) lives in `skills/rotation-analysis/prompt.md`.

### Module layout

| Module | Role |
|--------|------|
| `constants.py` | Scoring weight tables, FIP/stamina thresholds, mode definitions |
| `queries.py` | All DB loads, scoring logic, `query_rotation()` orchestrator |
| `report.py` | Cache check, HTML generation, `generate_rotation_report()` |
| `__init__.py` | Lazy `__getattr__` — `import rotation_analysis` does not pull submodules until needed |
| `__main__.py` | CLI: `python -m rotation_analysis <save> [mode] [openers=N] [team]` |

### `query_rotation()` return dict

Internal API used by `report.py`. Each key is prefixed with `_` to distinguish from
pitcher-level keys in the same data flow.

| Key | Type | Description |
|-----|------|-------------|
| `_team_id/name/abbr` | int/str/str | Resolved team |
| `_mode` | str | Active mode |
| `_n_starters` | int | 5 or 6 |
| `_rotation` | list[dict] | Top N starters by score; each has `_stats`, `_ratings`, `_career`, `score`, `throws_label`, `_flags` |
| `_depth` | list[dict] | Remaining candidates with ≥ `DEPTH_MIN_GS` career GS |
| `_opener_pairings` | list[dict] | `{slot, bulk, opener, reason, opener_score}` |
| `_ootp_diff` | list[dict] | `{slot, model_name, ootp_name, move_str, same}` |
| `_ootp_projected_ids` | list[int] | player_ids from `projected_starting_pitchers` |
| `_six_man` | bool | Whether the run is using a 6-man rotation mode |
| `_n_openers` | int | Number of opener slots requested for the run |
| `_all_names` | dict[int,str] | player_id → full name |

### Tables read

- `players`, `team_roster`, `players_roster_status`, `players_pitching` — pool assembly
- `pitcher_advanced_stats` — FIP, xFIP, K%, WHIP, splits (from `analytics.py`)
- `player_ratings` — `rating_now`, `rating_durability`, `rating_potential`, `flag_injury_risk`, `confidence`
- `players_career_pitching_stats` — recent GS/IP, career GS total
- `projected_starting_pitchers` — OOTP diff
- `players_injury_history` — IL stint counts
- `human_managers` — fallback team when no team arg given

### Key constants (`constants.py`)

| Constant | Value | Meaning |
|----------|-------|---------|
| `FIP_ELITE` / `FIP_POOR` | 2.50 / 5.50 | FIP → 0–100 normalization bounds |
| `STAMINA_FULL` / `STAMINA_POOR` | 70 / 35 | Stamina → innings-durability normalization |
| `MIN_SWING_MAN_STAMINA` | 50 | Min stamina for a reliever to enter the starter pool |
| `FIP_XFIP_LUCK_THRESHOLD` | 0.50 | Gap triggering regression-risk flag |
| `LOW_CAREER_GS_NON_ACE` | 15 | Career GS below this flags inexperience at #3–5 slots |
| `CAREER_GS_TARGET` | 80 | Career GS → full workload score (innings mode) |
| `OPENER_OPPOSITE_HAND_BONUS` | 10.0 | Score bonus when opener hand ≠ bulk pitcher hand |

Adding a new mode: add weight dict + entry in `MODES`, `MODE_LABELS`, and `MODE_WEIGHTS` in `constants.py`.
