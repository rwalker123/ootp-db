# MCP Server Refactor Plan

## Goal

The MCP server currently uses two inconsistent approaches for its tools — some call generators, some write SQL from scratch. This refactor makes all DB query logic live in a new `src/queries.py`. All 8 generators delegate to query functions from `queries.py`, and the MCP server becomes a thin presentation layer on top of `queries.py` with a file-based cache.

## Architecture After Refactor

```
mcp_server.py  (presentation layer — formatting + cache + tool dispatch)
    ↓ calls
queries.py  (all DB query logic + data assembly)
    ↑ imported by
generators (waiver_wire.py, etc.)  — still produce HTML for Claude Code skills unchanged

mcp_cache.py  (cache layer)
    ← used by mcp_server.py tools
    ← invalidated automatically via last_import timestamp in saves.json
```

## Tool Inventory (post-refactor)

| MCP Tool | Generator | Change |
|---|---|---|
| `player_stats` | `report.py` | Replaces `player_lookup` (stopgap) |
| `player_rating` | `ratings.py` | New tool — currently missing |
| `search_free_agents` | `free_agents.py` | Replace direct SQL with generator logic |
| `search_draft_prospects` | `draft_targets.py` / `ifa_targets.py` | Replace direct SQL with generator logic |
| `waiver_claim` | `waiver_wire.py` | Revert `bypass_cache` hack |
| `contract_extension` | `contract_extension.py` | Revert `bypass_cache` hack |
| `lineup_optimizer` | `lineup_optimizer.py` | Revert `bypass_cache` hack |
| `trade_targets` | `trade_targets.py` | Delegate via `query_trade_targets()` |

`player_lookup` is removed — it was a stopgap.

---

## Implementation Order

Steps 1, 2, and 3 are **independent** and can be done in any order or in parallel.
Steps 4, 5, and 6 depend on Steps 2 and 3 being complete.
Step 7 is independent.

```
Step 1 (fix import.py)   ──┐
Step 2 (create queries.py) ├──▶ Step 4 (rewrite mcp_server.py)
Step 3 (create mcp_cache.py)─┘    Step 5 (update 4 bypass_cache generators)
                                   Step 6 (update 4 other generators)
Step 7 (gitignore)  (anytime)
```

---

## Step 1 — Fix `src/import.py`: Preserve `my_team_id` and `my_team_abbr` on Re-import

### Problem

`_update_registry()` replaces the entire save entry dict on every import, wiping manually-set
fields `my_team_id` and `my_team_abbr`.

### Fix

Load the existing entry and merge only the three keys that change on import:

```python
def _update_registry(save_name, db_name, csv_dir):
    registry = _load_registry()
    saves = registry.setdefault("saves", {})
    existing = saves.get(save_name, {})
    existing.update({
        "db_name": db_name,
        "last_import": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "csv_path": str(csv_dir),
    })
    saves[save_name] = existing
    if not registry.get("active"):
        registry["active"] = save_name
    SAVES_JSON.write_text(json.dumps(registry, indent=2))
```

### Why This Matters

The MCP cache uses `last_import` from `saves.json` to determine cache validity. The `my_team_id`
and `my_team_abbr` fields are set manually and must survive subsequent re-imports. Without this
fix, every re-import silently breaks `waiver_claim`, `contract_extension`, `lineup_optimizer`,
and `trade_targets` tools.

---

## Step 2 — Create `src/queries.py`

New file. All DB query logic moves here. Generators and the MCP server both import from this module.

### Shared helpers at top of file

- `_get_engine(save_name)` — build SQLAlchemy engine from `.env` + save name
- `POS_MAP`, `BATS_MAP`, `THROWS_MAP`, `POS_CODE` — position/handedness lookup dicts (moved from `mcp_server.py`)
- `_fmt()`, `_pct()` — formatting helpers (moved from `mcp_server.py`)

### 8 Query Functions

#### `query_standings(save_name) -> list[dict]`
Lift SQL from `mcp_server.py` `standings()`. Returns list of dicts with keys:
`division`, `sub_league_id`, `division_id`, `name`, `nickname`, `w`, `l`, `pct`, `pos`, `gb`

#### `query_player(save_name, first_name, last_name) -> dict | None`
Queries `player_ratings` + `batter_advanced_stats` / `pitcher_advanced_stats`.
Returns the MCP subset dict (see Key Data Dict Reference below), or `None` if not found.
**Does not** call `generate_player_report()` — the generator's full data bag is needed only for HTML.

#### `query_player_rating(save_name, first_name, last_name, focus_modifiers=None) -> dict | None`
Extracts DB query block + weight/score computation from `ratings.py` (lines 98–293).
Returns the same data dict currently built at line 541 of `ratings.py`, plus all fields
needed for HTML generation (scores dict, weights, component labels, raw personality values).
Returns `None` if not found (currently `sys.exit(1)` — change to `return None`).

#### `query_free_agents(save_name, criteria_label, where_clause, join_clause="", order_by="pr.rating_overall DESC", limit=25, highlight=None) -> list[dict]`
Lifts the SQL block from `free_agents.py` (lines 150–184).
Returns same list of dicts currently built in `free_agents.py`.
**Preserve `where_clause` as a raw SQL string** — Claude generates it, do not restructure.

#### `query_draft_prospects(save_name, criteria_label, where_clause, order_by="dr.rating_overall DESC", limit=25, pool="draft") -> list[dict]`
Unifies `draft_targets.py` and `ifa_targets.py` — `pool="draft"` uses `draft_ratings`,
`pool="ifa"` uses `ifa_ratings`. Note: correct column names are `rating_overall`, `rating_ceiling`,
etc. (not `score_*` — the current MCP server has a bug here; fix it in this function).

#### `query_waiver_claim(save_name, first_name, last_name) -> dict | None`
Defined in `waiver_wire.py` (not `queries.py`) to avoid circular imports — the DB block calls
internal waiver helpers (`_lookup_player`, `_get_incumbents`, etc.) that live in `waiver_wire.py`.
`queries.py` re-exports it: `from waiver_wire import query_waiver_claim`.
Returns the data dict from lines 1325–1392 of `waiver_wire.py`, or `None` if not found.

#### `query_contract_extension(save_name, first_name, last_name) -> dict | None`
Defined in `contract_extension.py` — calls `_compute_*` helper variants (see Step 5).
Returns the full data dict (lines 892–929) plus private `_war_rows`, `_adv_rows`, `_comp_rows`
keys so the generator does not need to re-query the DB.
Returns `None` if player not found.

#### `query_lineup(save_name, team_query=None, philosophy="modern", opponent_hand=None, excluded_names=None, primary_only=False, forced_starts=None, forced_bench=None, fatigue_threshold=None, favor_offense=False) -> dict | None`
Defined in `lineup_optimizer.py` — extracts the DB block + post-DB Python computation
(lines 1221–1396) from `generate_lineup_report()`. Does not call `build_html()`.
Returns `data_dict` (lines 1373–1396) including `lineup_json` and `slug`, or `None` if team not found.

#### `query_trade_targets(save_name, offer_label, offered_where, target_where, my_team_id, mode="offering", target_join="", order_by="pr.rating_overall DESC", limit=25, highlight=None) -> dict`
Extracts DB block from `trade_targets.py` (lines 286–324).
Returns `dict(offered=list, targets=list)`.

---

## Step 3 — Create `src/mcp_cache.py`

Cache file: `PROJECT_ROOT / "cache" / "mcp_cache.json"`

### Cache Key

```python
def _cache_key(tool_name: str, args: dict, save_name: str) -> str:
    payload = save_name + ":" + tool_name + ":" + json.dumps(args, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
```

`save_name` must be in the key — if the active save changes, the cache must miss.

### Cache Entry Format

```json
{
  "<sha256_key>": {
    "result": "<formatted string>",
    "import_time": "2026-04-05T03:05:03"
  }
}
```

### Hit Condition

Entry exists AND `entry["import_time"] == current last_import from saves.json`.

### Functions

```python
def cache_get(tool_name: str, args: dict, save_name: str, import_time: str) -> str | None: ...
def cache_put(tool_name: str, args: dict, save_name: str, result: str, import_time: str) -> None: ...
```

Load cache file fresh on every read (no in-memory state). Write by loading, updating single key, writing back. Create `cache/` directory with `mkdir(parents=True, exist_ok=True)` on first write.

---

## Step 4 — Rewrite `src/mcp_server.py`

### Remove
- All SQL
- Direct generator imports (`waiver_wire`, `contract_extension`, `lineup_optimizer`, `trade_targets`)
- `bypass_cache=True` calls
- `player_lookup` tool (replaced by `player_stats`)
- `_get_engine`, `POS_MAP`, `BATS_MAP`, `THROWS_MAP`, `POS_CODE`, `_fmt`, `_pct` (moved to `queries.py`)

### Add
- `from queries import (query_standings, query_player, query_player_rating, query_free_agents, query_draft_prospects, query_waiver_claim, query_contract_extension, query_lineup, query_trade_targets, POS_MAP, BATS_MAP, THROWS_MAP, POS_CODE, _fmt, _pct)`
- `from mcp_cache import cache_get, cache_put`
- `player_stats` tool (replaces `player_lookup`)
- `player_rating` tool (new)

### Helper: `_get_import_time(save_name)`
```python
def _get_import_time(save_name: str) -> str:
    saves = _load_saves()
    return saves.get("saves", {}).get(save_name, {}).get("last_import", "")
```

### Consistent tool pattern (all 9 tools)
```python
@mcp.tool()
def tool_name(param: str) -> str:
    save = _active_save()
    import_time = _get_import_time(save)
    args = dict(param=param)
    hit = cache_get("tool_name", args, save, import_time)
    if hit:
        return hit
    data = query_tool_name(save, param)
    if data is None:
        return "Not found: ..."
    result = _format_tool_name(data)
    cache_put("tool_name", args, save, result, import_time)
    return result
```

### Formatting functions stay in `mcp_server.py`
- `_format_standings(rows)`, `_format_player_stats(data)`, `_format_player_rating(data)`
- `_format_free_agents(results)`, `_format_draft_prospects(results, pool)`
- `_format_waiver_claim(data)`, `_format_contract_extension(data)`
- `_format_lineup(data)`, `_format_trade_targets(result)`

---

## Step 5 — Update the 4 Generators With `bypass_cache`

### `src/waiver_wire.py`
1. Define `query_waiver_claim(save_name, first_name, last_name)` as a standalone function
   that calls the existing internal helpers (`_lookup_player`, `_get_incumbents`, etc.)
2. Update `generate_waiver_claim_report()` to call `query_waiver_claim()` for data
3. Revert `bypass_cache=False` parameter — restore original cache check

### `src/contract_extension.py` — Helper Split (most complex)

Each helper that mixes HTML generation with scalar computation gets split:

| Current helper | Compute variant | HTML variant |
|---|---|---|
| `build_war_table_batter(rows)` → `(html, war_vals)` | `_compute_war_vals_batter(rows)` | keep existing (can call compute internally) |
| `build_war_table_pitcher(rows)` → `(html, war_vals)` | `_compute_war_vals_pitcher(rows)` | keep existing |
| `build_comps_table(rows)` → `(html, median_sal)` | `_compute_comps_data(rows)` → `{median_sal, comp_names}` | keep existing |
| `build_adv_stats_batter_table(rows)` → `(html, most_recent)` | `_compute_adv_most_recent_batter(rows)` | keep existing |
| `build_adv_stats_pitcher_table(rows)` → `(html, most_recent)` | `_compute_adv_most_recent_pitcher(rows)` | keep existing |

Then:
1. Define `query_contract_extension()` — calls `_compute_*` functions, returns full data dict
   plus `_war_rows`, `_adv_rows`, `_comp_rows` private keys
2. Update `generate_contract_extension_report()` — calls `query_contract_extension()`, then
   uses `_*_rows` for HTML generation (no second DB trip)
3. Revert `bypass_cache=False` — restore original cache check at line 545

### `src/lineup_optimizer.py`
1. Define `query_lineup()` — extracts lines 1221–1396 (DB block + data_dict construction)
2. Update `generate_lineup_report()` — call `query_lineup()`, then call `build_html(data_dict)`
3. Revert `bypass_cache=False` — restore original cache check

---

## Step 6 — Update the 4 Generators Without `bypass_cache`

### `src/trade_targets.py`
Replace DB block (lines 286–324) with `result = query_trade_targets(...)`.
Use `result["offered"]` and `result["targets"]` for HTML generation.

### `src/free_agents.py`
Replace DB block (lines 146–184) with `results = query_free_agents(...)`.
HTML generation uses `results` list as before.

### `src/ratings.py`
Replace DB query + weight computation block with `data = query_player_rating(...)`.
HTML generation reads all needed values from `data` dict.
Ensure `query_player_rating()` return dict includes all fields needed for HTML (not just the
summary fields currently returned at line 541).

### `src/report.py`
**No change.** `generate_player_report()` continues to use `fetch_common_data()` /
`fetch_batter_data()` / `fetch_pitcher_data()` directly — these return a large data bag
tailored for HTML output that is incompatible with the MCP subset. `query_player()` is
used only by `mcp_server.py`.

---

## Step 7 — Update `.gitignore`

Add `cache/` alongside the existing `reports/` entry.

---

## Risks and Gotchas

### 1. `contract_extension.py` helper split is the most invasive
Read `build_comps_table()` carefully — `median_comp_salary` and `comp_names` come from the
same loop. `_compute_comps_data()` must compute both in one pass.

### 2. `report.py` does not change
`generate_player_report()` needs the full HTML data bag. `query_player()` returns only the
MCP subset from `player_ratings` + advanced stats views. These two paths are intentionally
separate — do not try to unify them.

### 3. `draft_ratings` column names are `rating_*` not `score_*`
The current MCP server has a bug here — `score_overall`, `score_ceiling`, etc. are wrong.
Fix to `rating_overall`, `rating_ceiling`, `rating_tools`, `rating_development`, `rating_defense`
when writing `query_draft_prospects()`.

### 4. `query_waiver_claim` is defined in `waiver_wire.py`, not `queries.py`
To avoid circular imports (the waiver helpers it calls live in `waiver_wire.py`), define
`query_waiver_claim()` in `waiver_wire.py` and re-export from `queries.py`:
`from waiver_wire import query_waiver_claim`

### 5. `bypass_cache` removal
After the refactor, generators revert to consulting their HTML file cache normally. The MCP
server no longer calls generators at all — it calls `query_*()` functions. The generators'
HTML cache behavior is irrelevant to MCP.

### 6. `ratings.py` computation duplication risk
After the split, `generate_rating_report()` must call `query_player_rating()` for the data
dict and read values from it for HTML — not re-compute weights independently.

---

## Key Data Dict Reference

### `query_player()` return dict
```python
{
    "player_id": int,
    "first_name": str, "last_name": str,
    "position": int,            # numeric code
    "team_abbr": str,
    "age": int, "oa": int, "pot": int,
    "player_type": str,         # "batter" or "pitcher"
    "rating_overall": float,
    "rating_offense": float, "rating_defense": float,
    "rating_potential": float, "rating_durability": float,
    "rating_clubhouse": float, "rating_development": float,
    "rating_baserunning": float,
    "rating_contact_quality": float, "rating_discipline": float,
    "wrc_plus": float | None,
    "war": float | None,
    "prone_overall": int | None,
    "flag_injury_risk": bool, "flag_leader": bool, "flag_high_ceiling": bool,
    "bats": int, "throws": int,
    "free_agent": bool,
    "adv": dict | None,         # from batter_advanced_stats or pitcher_advanced_stats
}
```

### `query_contract_extension()` return dict
Public fields: all fields from `data_dict` at lines 892–929 of `contract_extension.py`.
Private fields (for HTML generation, ignored by MCP):
```python
"_war_rows": list,
"_adv_rows": list,
"_comp_rows": list,
"_player_id": int,
"_player_row_d": dict,
```

---

## Files Summary

| File | Action | Key Change |
|---|---|---|
| `src/queries.py` | **CREATE** | All 8 query functions + shared helpers |
| `src/mcp_cache.py` | **CREATE** | `cache_get` / `cache_put` with import_time invalidation |
| `src/mcp_server.py` | **REWRITE** | Remove SQL/generators; add `player_stats`, `player_rating`; cache pattern |
| `src/import.py` | **FIX** | `_update_registry()` merges instead of replaces |
| `src/waiver_wire.py` | **UPDATE** | Add `query_waiver_claim()`, revert `bypass_cache` |
| `src/contract_extension.py` | **UPDATE** | Split helpers, add `query_contract_extension()`, revert `bypass_cache` |
| `src/lineup_optimizer.py` | **UPDATE** | Delegate to `query_lineup()`, revert `bypass_cache` |
| `src/trade_targets.py` | **UPDATE** | Delegate to `query_trade_targets()` |
| `src/free_agents.py` | **UPDATE** | Delegate to `query_free_agents()` |
| `src/ratings.py` | **UPDATE** | Delegate to `query_player_rating()` |
| `src/report.py` | **NO CHANGE** | Generator keeps its own DB access; `query_player()` is MCP-only |
| `.gitignore` | **UPDATE** | Add `cache/` |
