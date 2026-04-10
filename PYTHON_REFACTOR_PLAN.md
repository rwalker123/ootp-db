# Python layout refactor plan

This document analyzes `src/` modules (post-`ratings/` package split) and proposes follow-on work. It is meant to be picked up incrementally; order and scope can change.

## Reference model

Use **`src/ratings/`** and **AGENTS.md → Domain packages and module split (ratings model)** as the template:

- `constants.py` — shared between compute and presentation where applicable  
- `compute.py` (or domain-specific name) — batch / heavy logic, `main()`, `python -m <pkg>`  
- `queries.py` — data assembly for skills, MCP, server (no HTML)  
- `report.py` — cache, HTML, `write_report_html`  
- `__init__.py` — lazy `__getattr__` if lightweight imports must not pull pandas  
- No sibling `src/foo.py` + `src/foo/`  

---

## Summary table

| File | Lines (approx) | Split priority | Notes |
|------|----------------|----------------|--------|
| `ratings/` | (done) | — | Reference implementation |
| `lineup_optimizer.py` | ~1,509 | **High** | Large optimizer + ranking + HTML in one file |
| `waiver_wire.py` | ~1,471 | **High** | Deep query + many `_build_*` HTML sections |
| `report.py` | ~1,231 | **High** | Player-stats: fetch layers + large HTML generators |
| `contract_extension.py` | ~1,059 | **High** | Very large `query_*` + many table builders + report |
| `analytics.py` | ~768 | Medium | Cohesive ETL; split optional (batter / pitcher / history) |
| `trade_targets.py` | ~638 | Medium | Trade query + table HTML + context lookup |
| `import.py` | ~556 | Low–medium | Mostly one workflow; optional extract schema/discovery |
| `free_agents.py` | ~328 | Medium–low | Same *shape* as trade_targets but smaller |
| `draft_ratings.py` | ~364 | Medium | Parallel to `ifa_ratings.py`; shared scoring helper candidate |
| `ifa_ratings.py` | ~368 | Medium | Same as draft_ratings |
| `config.py` | ~312 | No split | Keep as single tuning surface |
| `shared_css.py` | ~250 | No split | Shared infrastructure |
| `queries.py` | ~263 | Low | Thin MCP/query barrel; split only if it grows |
| `draft_targets.py` / `ifa_targets.py` | ~280 each | Low | Reasonable size for one feature |
| `ootp_mcp/` | package | Optional | Already split; revisit if server grows |

---

## File-by-file analysis

### `lineup_optimizer.py` (~1,509 lines)

**Concerns mixed today**

- DB loaders (`load_roster_batters`, fielding, stats, 30-day rolling)  
- Core algorithm (`compute_blended_woba`, `platoon_score`, `_select_positional_nine`, `build_lineup`, alternation scoring)  
- Presentation (`build_html`, many `*_td` / color helpers)  
- Public API (`query_lineup`, `generate_lineup_report`)  

**Recommendation:** Package `src/lineup_optimizer/` (name matches domain):

- `compute.py` or `engine.py` — ranking, lineup construction, WOBA blend (pure logic + DB loads could stay here or `loaders.py`)  
- `report.py` — `build_html`, formatting helpers  
- `queries.py` — `query_lineup` orchestration if kept separate from HTML  
- `__main__.py` — if a CLI is ever added; today entry may be server-only  

**Dependency note:** Heaviest file; high value for tests on optimizer without HTML.

---

### `waiver_wire.py` (~1,471 lines)

**Concerns mixed today**

- SQL helpers (`_lookup_player`, incumbents, advanced stats, fielding, 40-man)  
- Many `_build_*_section` HTML fragments (candidate, ratings, contract, stats, incumbents, fielding, personality)  
- `query_waiver_claim` vs `generate_waiver_claim_report`  

**Recommendation:** Package `src/waiver_claim/` (or `waiver_wire/` to match imports):

- `queries.py` — all `_get_*` / `_lookup_*` and `query_waiver_claim`  
- `report.py` — sections + `generate_waiver_claim_report` + cache (`find_existing_*`)  
- `formatting.py` — duplicated `letter_grade`, `injury_label`, salary helpers **or** delegate to a shared module (see cross-cutting)  

**Risk:** Many HTML sections; refactor in one PR is large—split mechanically first (move functions), then dedupe.

---

### `report.py` (~1,231 lines) — player advanced stats report

**Concerns mixed today**

- Rate calculations (`calc_rates`, `calc_pitching_rates`)  
- `fetch_common_data`, `fetch_batter_data`, `fetch_pitcher_data`, fielding  
- Large `generate_*_html` / section builders  
- `find_existing_report`, `generate_player_report`  

**Recommendation:** Package `src/player_stats/` (or `player_report/`) to avoid confusion with generic “report”:

- `fetch.py` — all `fetch_*`  
- `rates.py` — batting/pitching rate helpers  
- `report.py` — HTML + cache + `generate_player_report`  
- `__init__.py` — re-exports for `from player_stats import generate_player_report` (update `server.py` imports)  

---

### `contract_extension.py` (~1,059 lines)

**Concerns mixed today**

- Huge `query_contract_extension` (data gathering)  
- Many `build_*_table` / scalar summaries for comps and WAR  
- `generate_contract_extension_report`  

**Recommendation:** Package `src/contract_extension/`:

- `queries.py` — `query_contract_extension` and DB-only helpers  
- `report.py` — HTML + `generate_contract_extension_report`  
- `tables.py` — WAR / advanced / comps table builders (optional third module to keep `report.py` smaller)  

---

### `analytics.py` (~768 lines)

**Mostly one pipeline:** career stats → contact quality → finalize → optional history archive.

**Recommendation:** **Optional** split into `analytics/batter.py`, `analytics/pitcher.py`, `analytics/history.py`, `analytics/__main__.py` if you want faster navigation or separate tests. **Lower priority** than report-heavy skills because there is little HTML and a single `main()`.

---

### `trade_targets.py` (~638 lines)

**Pattern:** `lookup_trade_context`, `query_trade_targets`, HTML table builders, small formatting helpers.

**Recommendation:** Package `src/trade_targets/` with `queries.py` + `report.py` + `constants.py` (position adjustments). Good second exercise after one of the larger splits.

---

### `free_agents.py` (~328 lines)

**Pattern:** Similar to trade targets (query + table + badges).

**Recommendation:** Package `src/free_agents/` when touching it next, or batch with `trade_targets` if introducing **shared table styling** for list reports.

---

### `import.py` (~556 lines)

**Cohesive:** version detect, schema snapshot diff, save discovery, registry, CSV load loop.

**Recommendation:** **Low priority.** Optional `importlib` package with `schema.py`, `discovery.py`, `main.py` only if `import.py` grows further.

---

### `draft_ratings.py` & `ifa_ratings.py` (~364 / ~368 lines)

**Near-duplicate structure:** `clamp`, `norm`, `load_*`, tool scores, `compute_*`, `main`.

**Recommendation:**

1. Extract **`src/prospect_ratings_common.py`** (or `prospect_scoring/`) with shared `clamp`, `norm`, defense/tools scoring patterns.  
2. Keep two thin CLIs or two small packages `draft_ratings/`, `ifa_ratings/` with only `load_*` + `compute_*` + `main` if divergence grows.  

**Priority:** Medium — DRY before growing either file further.

---

### `queries.py` (~263 lines)

Standings / player / draft prospect helpers for MCP.

**Recommendation:** Leave as-is until it exceeds ~400 lines or domains blur; then split to `mcp_queries/` or fold into respective domain packages (`draft_targets` queries next to draft code).

---

## Cross-cutting: duplicated report helpers

Several files reimplement or copy:

- `get_last_import_time` (`.last_import` path)  
- `letter_grade` / `grade_badge`  
- `injury_label` / `injury_color`  
- `trait_label` / `trait_color`  
- `fmt_salary`, `get_current_salary`, `get_years_remaining`  
- `arb_status_label`  

**Recommendation (separate small initiative):**

1. Add **`src/report_formatting.py`** (or extend `report_write.py` carefully) with config-driven injury/trait helpers matching `config.py` thresholds.  
2. Replace duplicates incrementally as each large file is split.  
3. Optionally centralize “last import” in `shared_css.py` if you want one canonical path helper.  

This reduces the risk of another “hardcoded vs config” drift like the old `ratings.py` issue.

---

## Suggested phases

### Phase 0 — Done

- [x] `src/ratings/` package + lazy `__init__.py`  
- [x] `import.sh` / `import.bat` + AGENTS.md alignment  

### Phase 1 — Shared formatting (optional but high leverage)

- [ ] Introduce `report_formatting.py` (or agreed name) with shared helpers + tests  
- [ ] Migrate **one** consumer (e.g. `free_agents.py` or `trade_targets.py`) to prove the pattern  

### Phase 2 — Largest report modules (highest user-facing complexity)

Pick order by what you touch most:

- [ ] `waiver_wire.py` → `waiver_claim/` (or `waiver_wire/`)  
- [ ] `lineup_optimizer.py` → `lineup_optimizer/`  
- [ ] `report.py` → `player_stats/` (import path rename plan for `server.py`)  
- [ ] `contract_extension.py` → `contract_extension/`  

Each step: move code with **no behavior change**, run import pipeline / server smoke path, then dedupe formatting.

### Phase 3 — Medium list reports

- [ ] `trade_targets.py` → package  
- [ ] `free_agents.py` → package  

### Phase 4 — ETL and prospect scripts

- [ ] Shared prospect scoring module for `draft_ratings.py` + `ifa_ratings.py`  
- [ ] (Optional) `analytics.py` → `analytics/` package  
- [ ] (Optional) `import.py` internal modules  

---

## Per-package checklist (repeat for each)

1. Create `src/<domain>/` with `__init__.py` (lazy if pandas/heavy).  
2. Move `main` to `__main__.py` if applicable; update `import.sh` / docs.  
3. Grep for `from <old_module>` / `import <old_module>` in repo (`server.py`, MCP, skills prompts).  
4. Run `python -m unittest discover -s tests` (and any manual report generation you rely on).  
5. Update **AGENTS.md** / **SKILLS_ROADMAP.md** only if user-facing commands change.  

---

## Out of scope for this plan

- Frontend / npm projects  
- Rewriting SQL or rating formulas (structure only)  
- Moving `server.py` into a package (could be a later mega-task)  

---

*Last updated from a line-count and symbol survey of `src/*.py`. Adjust line numbers as the codebase grows.*
