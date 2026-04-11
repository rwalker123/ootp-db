---
paths:
  - "skills/**"
---

## Skill Architecture

Each skill has two parts:

- **`skills/<skill-name>/prompt.md`** — the LLM-neutral prompt that any model can follow.
  This is the source of truth for what the skill does.
- **An LLM adapter** — a thin per-tool config that exposes the skill for invocation and
  passes arguments to the prompt. When adding support for a new LLM, create a parallel
  adapter that loads the same prompt.md.

All eight OOTP skills follow this architecture. Follow these rules exactly when creating or
modifying any skill.

### The Division of Responsibility

**Python does** (deterministic, no LLM needed):
- Cache check — return existing report if it's newer than the last import
- All DB queries
- All HTML generation (structure, tables, CSS, color coding)
- File write

**Agent does** (requires LLM judgment):
- Parse `$ARGUMENTS` into parameters (player name, focus modifiers, NL criteria)
- For `/free-agents` only: translate NL → SQL WHERE/JOIN/highlight
- Write LLM analysis text into HTML placeholder comments
- Run `open <path>` to open the browser
- Print the 2–3 line terminal summary

The agent **never** queries the database directly and **never** generates HTML structure.

### CACHED:/GENERATED: Protocol

Every Python entry point prints exactly one of:
```
CACHED:/absolute/path/to/report.html
GENERATED:/absolute/path/to/report.html
```

On `CACHED:` — agent runs `open <path>`, prints one-liner, **STOP**.
On `GENERATED:` — agent writes analysis into the placeholder, then opens, then prints summary.

### HTML Placeholders

Each report type has one placeholder the agent fills in:
- `/player-stats` → `<!-- BATTING_SUMMARY -->` and/or `<!-- PITCHING_SUMMARY -->`
- `/player-rating` → `<!-- RATING_SUMMARY -->`
- `/free-agents` → `<!-- FA_CALLOUT_SUMMARY -->`

The agent reads the file, replaces the placeholder comment with the analysis HTML, writes
it back. It never rewrites any other part of the file.

### `open` Command Rules

- **Always use the full absolute path** — never a relative path or `<placeholder>`
- The orchestrator (the LLM in the outer conversation) knows the player's ID and filename
  from prior runs and hardcodes it in the agent prompt
- For a new player the orchestrator doesn't know yet, instruct the agent to use the path
  printed after `GENERATED:` — make this explicit: *"open the path printed after GENERATED:"*
- A bash `open` block must appear in the prompt.md for **every** exit branch (CACHED and GENERATED)

### Context Isolation

Every skill's prompt.md must include a **Context isolation** section near the top:

```
## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the arguments to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.
```

This prevents context bleedover when running multiple skills in the same session. If a
sub-agent mechanism is available (e.g. a tool that supports spawning isolated sub-agents),
the LLM will use it for hard isolation. If not, the prompt instruction provides a best-effort reset.

### Python Entry Point Conventions

Entry points live in `src/` and follow this pattern:

```python
def generate_<type>_report(save_name, ...):
    existing = find_existing_<type>_report(...)
    if existing:
        return existing, None          # None = cache hit signal

    # ... queries, HTML generation ...

    report_path.write_text(html)
    return str(report_path), data_dict  # data_dict for agent terminal summary
```

- Return `(path, None)` on cache hit
- Return `(path, data_dict)` on generation
- `data_dict` contains the key stats the agent needs for its terminal summary
- CSS: use the shared `get_report_css()` from `src/shared_css.py` for visual consistency
- Reports go under `PROJECT_ROOT / "reports" / "<type>/"`

### Domain packages and module split (ratings model)

When new Python work combines **batch / ETL** (derived tables, pandas, heavy merges), **per-request queries** (skills, MCP, server), and **HTML reports** (cache, templates), **do not** keep everything in one huge `src/<thing>.py`. Follow the layout used by **`src/ratings/`**:

| Piece | Role | Typical module |
|-------|------|----------------|
| **Shared constants** | Maps, weight dicts, column names used by both batch and report/query paths | `constants.py` |
| **Tiny shared helpers** | Letter grades, one-liners with no heavy imports | e.g. `grades.py` |
| **Batch / compute** | Load frames, scoring, `to_sql`, CLI `main()` | `compute.py` |
| **Query / skill API** | Read-only assembly for agents (names, focus modifiers, MCP helpers) | `queries.py` |
| **Report** | Cache check, HTML generation, `write_report_html` | `report.py` |
| **CLI** | `python -m <package>` from `src/` | `__main__.py` delegates to `compute.main()` (or equivalent) |

**Conventions:**

- **Package location:** `src/<domain>/` as a proper package (`__init__.py`). Do **not** place `src/<domain>.py` next to `src/<domain>/` — Python import ambiguity.
- **Invocation:** Run batch jobs as `( cd src && python -m <domain> <save_name> )`. Wire `import.sh` / `import.bat` the same way as `ratings`.
- **Public API:** Re-export stable names from `__init__.py` (`from domain import generate_*_report`, `query_*`, …) so `server.py`, MCP, and skills keep simple imports.
- **Lazy imports:** If the package pulls in **pandas / numpy** only for batch compute, use **`__getattr__`** in `__init__.py` (see `src/ratings/__init__.py`) so `import <domain>` or `from <domain> import query_*` does **not** load the heavy submodule until something like `main` or `compute_*` is accessed.
- **Cross-cutting config** stays in **`config.py`**, **`ootp_db_constants.py`**, and **`shared_css.py`**; do not introduce repo-wide folders like `src/compute/` or `src/reports/` that scatter one feature across layers.

Legacy single-file scripts (`analytics.py`, `free_agents.py`, …) are fine until a change touches enough surface area to justify a package; **new large features** should start as or migrate to this model.

### `/free-agents` Highlight Columns

The `generate_free_agents_report` function accepts a `highlight` parameter — a list of
`(col_key, display_label)` tuples that add extra stat columns to the table:

```python
highlight = [("rating_defense", "Defense")]
path, rows = generate_free_agents_report(..., highlight=highlight)
```

The agent picks highlight columns based on the query focus (see prompt.md mapping table).
Maximum 2 highlight columns per search. Column keys come from `player_ratings`.

### Visual Style (all reports)

- CSS via `shared_css.py` — consistent font, table styles, color classes
- Table headers: `background: #2c3e50; color: white`
- Striped rows: `tr:nth-child(even) td { background: #f0f4f8 }`
- Hover: `tr:hover td { background: #e0e8f0 }`
- Score colors: green ≥70, yellow 40–69, red <40
- Classes: `.good` (green bold), `.poor` (red bold), `.summary` (left-bordered callout)
