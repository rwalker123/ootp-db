# AGENTS.md Refactor Plan

Root `AGENTS.md` is ~43.7K, above the Claude Code 40K warning threshold. This plan
reduces it by distributing domain-specific content into per-package `AGENTS.md` files,
backed by path-scoped `.claude/rules/` symlinks for Claude Code.

**This plan is intentionally aligned with `PYTHON_REFACTOR_PLAN.md`.** Each time a new
domain package is created, the matching docs move out of root at the same time. No
separate documentation pass needed.

---

## Two contexts — different sources of truth

Content must be placed based on *when* it is needed, not just *what* it is about:

| Context | When it loads | Source |
|---------|--------------|--------|
| **Skill execution** | Always — every `/skill` invocation | Root `AGENTS.md` + `skills/<name>/prompt.md` |
| **Developer / code** | Only when editing matching source files | `.claude/rules/<domain>.md` (path-scoped) |

**Implication:** anything a running skill needs — table schemas, column names, query
patterns, enum values — must stay in root `AGENTS.md`. Path-scoped rules only fire when
Claude reads a file inside the matching directory (e.g. `src/ratings/compute.py`). They
do **not** fire when a skill invokes a Python script or reads its HTML output.

**`skills/<name>/prompt.md`** is the authoritative source for all skill execution details:
modes, placeholder names, decision bands, argument parsing, terminal summary format. Do
not duplicate any of that in package `AGENTS.md` files — those are for developers
modifying the package, not for the skill runner.

---

## Claude Code loading mechanism

Claude Code reads `CLAUDE.md`, not `AGENTS.md` directly. The root `AGENTS.md` is loaded
because `CLAUDE.md` contains `@AGENTS.md`. Subdirectory `AGENTS.md` files require an
explicit reference to load — they are **not** auto-discovered.

The path-scoped loading mechanism for Claude Code is `.claude/rules/`:
- Files **without** `paths:` frontmatter → loaded unconditionally at every session
- Files **with** `paths:` frontmatter → lazy-loaded only when Claude reads a matching file

Each package `AGENTS.md` has `paths:` frontmatter. A symlink in `.claude/rules/` points
to it so Claude Code picks it up without duplicating content.

Other AI tools (Cursor, Copilot, etc.) auto-read `AGENTS.md` from subdirectories directly
— the file serves both audiences from one location.

---

## What stays in root `AGENTS.md`

Required for skill execution, ad-hoc queries, and MCP — cannot be distributed:

- Project Overview
- Querying the Database (patterns, heredoc rules, engine conventions)
- Environment / Dependencies / Configuration
- Common Query Patterns
- Database Schema Overview (full table inventory, PK conventions, stat abbreviations,
  enum values, column conventions, data availability notes)
- **All computed-table schemas** (`player_ratings`, `draft_ratings`, `batter_advanced_stats`,
  etc.) — needed by running skills and `/adhoc`; must not be gated behind a paths filter
- Notes / Re-running After a Sim / Saves registry

---

## Immediate — no code changes required

These packages already exist. Docs can move today.

### `src/ratings/AGENTS.md` ✅

Developer context for the ratings package (path-scoped to `src/ratings/**`):
- Module layout, invocation, weight tuning guidance
- **Schema stays in root** — `player_ratings` column list is needed at skill-execution time

### `src/rotation_analysis/AGENTS.md` ✅

Developer context (path-scoped to `src/rotation_analysis/**`):
- Module layout, `query_rotation()` return dict, tables read, key constants
- Modes table and HTML placeholder removed — those live in `skills/rotation-analysis/prompt.md`

### `.claude/rules/` symlinks ✅

- `.claude/rules/ratings.md` → `../../src/ratings/AGENTS.md`
- `.claude/rules/rotation_analysis.md` → `../../src/rotation_analysis/AGENTS.md`

### `skills/AGENTS.md`

Move the **Skill Architecture** section from root (developer context — only needed when
authoring or modifying skills, not during skill execution):
- The Division of Responsibility
- CACHED:/GENERATED: Protocol
- HTML Placeholders
- `open` Command Rules
- Context Isolation
- Python Entry Point Conventions
- Domain packages and module split (ratings model)
- `/free-agents` Highlight Columns
- Visual Style (all reports)

Add `.claude/rules/skills.md` → `../../skills/AGENTS.md` with `paths: ["skills/**"]`.

**Expected root reduction: ~8–12K**

---

## Phase-aligned — one `AGENTS.md` per new package

As each package from `PYTHON_REFACTOR_PLAN.md` is created, add its `AGENTS.md` and
`.claude/rules/` symlink at the same time.

**Rule for each new package AGENTS.md:**
- Include: module layout, public API, key constants, tables written (not tables read —
  those are in root schema)
- Exclude: anything already in the skill's `prompt.md`; any schema needed at query time

### Phase 2 packages

| New package | Root content to extract | Seed developer docs with |
|-------------|------------------------|--------------------------|
| `src/lineup_optimizer/` | None | Module layout, scoring engine API |
| `src/waiver_claim/` | None | Module layout, public API |
| `src/player_stats/` | None | Module layout, public API |
| `src/contract_extension/` | None | Module layout, public API |

### Phase 3 packages

| New package | Root content to extract | Seed developer docs with |
|-------------|------------------------|--------------------------|
| `src/trade_targets/` | None | Module layout, public API |
| `src/free_agents/` | None | Module layout, public API |

### Phase 4 packages

Phase 4 is where meaningful root extraction becomes possible. The Analytics Engine and
Draft Ratings schemas are large — but only move them if they are **not** needed by running
skills. If `/adhoc` or any skill queries those tables by column name, they stay in root.

| New package | Potential root extraction |
|-------------|--------------------------|
| `src/analytics/` (if split) | Analytics Engine section — only if no skill queries `batter_advanced_stats` columns by name at runtime (they do — likely stays in root) |
| `src/draft_ratings/` (if split) | Draft Ratings Tables section — `/draft-targets` skill queries these; likely stays in root |

**Likely outcome:** Phase 4 packages get developer context AGENTS.md files, but the
table schemas remain in root because running skills need them.

---

## Target state

| Location | Content | Audience |
|----------|---------|---------|
| Root `AGENTS.md` | Project, DB querying, all table schemas, common patterns | Skills, MCP, ad-hoc — always loaded |
| `src/ratings/AGENTS.md` | Ratings package internals | Developer editing `src/ratings/` |
| `src/rotation_analysis/AGENTS.md` | Rotation analysis internals | Developer editing `src/rotation_analysis/` |
| `skills/AGENTS.md` | Skill architecture, protocol, visual style | Developer authoring skills |
| `src/<domain>/AGENTS.md` | Per-package internals (phase 2–4) | Developer editing that package |
| `.claude/rules/*.md` | Symlinks to above AGENTS.md files with `paths:` frontmatter | Claude Code path-scoped loading |

---

## Checklist

### Immediate

- [x] Create `src/ratings/AGENTS.md` — developer context, path-scoped
- [x] Create `src/rotation_analysis/AGENTS.md` — developer context, path-scoped; pruned of skill-prompt content
- [x] Create `.claude/rules/` symlinks for ratings and rotation_analysis
- [x] Create `skills/AGENTS.md` — move Skill Architecture section; add `.claude/rules/skills.md` symlink
- [x] Verify root drops below 40K — now 39,089 bytes

### Per Phase 2–3 package (repeat for each)

- [ ] Create `src/<domain>/AGENTS.md` — developer context only (module layout, public API, constants)
- [ ] Add `.claude/rules/<domain>.md` symlink with `paths: ["src/<domain>/**"]`
- [ ] Confirm nothing in the new file duplicates `skills/<name>/prompt.md`

### Per Phase 4 package (if package is created)

- [ ] Evaluate whether Analytics Engine / Draft Ratings schemas are query-time (stay in root) or dev-only (can move)
- [ ] Create developer context AGENTS.md regardless; only extract root schema if skill doesn't need it

---

## Out of scope

- Trimming or rewriting the Database Schema Overview (reference-complete by design)
- Moving `PYTHON_REFACTOR_PLAN.md` content — deleted once the refactor is done
- Rewriting `skills/<name>/prompt.md` files

---

*Coordinate with `PYTHON_REFACTOR_PLAN.md` — this plan has no independent phases.*
