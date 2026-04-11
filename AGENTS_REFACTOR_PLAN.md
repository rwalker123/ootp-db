# AGENTS.md Refactor Plan

Root `AGENTS.md` is ~43.7K, above the Claude Code 40K warning threshold. This plan
reduces it by distributing domain-specific content into per-package and per-directory
`AGENTS.md` files. Claude Code loads subdirectory `AGENTS.md` files automatically when
working in that context, so content moved there is still available — it just isn't loaded
on every interaction.

**This plan is intentionally aligned with `PYTHON_REFACTOR_PLAN.md`.** Each time a new
domain package is created, the matching docs move out of root at the same time. No
separate documentation pass needed.

---

## What stays in root `AGENTS.md`

These sections are needed for nearly every interaction (ad-hoc queries, all skills, MCP)
and cannot be distributed:

- Project Overview
- Querying the Database (patterns, heredoc rules, engine conventions)
- Environment / Dependencies / Configuration
- Common Query Patterns
- Database Schema Overview (full table inventory, PK conventions, stat abbreviations,
  enum values, column conventions, data availability notes)
- Notes / Re-running After a Sim / Saves registry

---

## Immediate — no code changes required

These packages already exist. Docs can move today.

### `src/ratings/AGENTS.md`

Move the **Player Ratings Table (`player_ratings`)** section from root:
- Full schema (identity, composite ratings, confidence, flags, carried-over stats)
- `python -m ratings` invocation

### `skills/AGENTS.md`

Move the **Skill Architecture** section from root:
- The Division of Responsibility
- CACHED:/GENERATED: Protocol
- HTML Placeholders
- `open` Command Rules
- Context Isolation
- Python Entry Point Conventions
- Domain packages and module split (ratings model)
- `/free-agents` Highlight Columns
- Visual Style (all reports)

**Expected root reduction: ~8–12K**

---

## Phase-aligned — one `AGENTS.md` per new package

As each package from `PYTHON_REFACTOR_PLAN.md` is created, add its `AGENTS.md` at the
same time. Nothing moves until the Python refactor for that domain is complete.

### Phase 2 packages

| New package | Docs to extract from root |
|-------------|--------------------------|
| `src/lineup_optimizer/` | None currently in root — seed with query conventions as they're defined |
| `src/waiver_claim/` | None currently in root — seed with query conventions |
| `src/player_stats/` | None currently in root — seed with query conventions |
| `src/contract_extension/` | None currently in root — seed with query conventions |

These packages are net-new docs, not extractions. They keep root size flat while giving
each domain a home for future content.

### Phase 3 packages

| New package | Docs to extract from root |
|-------------|--------------------------|
| `src/trade_targets/` | None currently in root — seed with query conventions |
| `src/free_agents/` | None currently in root — seed with query conventions |

### Phase 4 packages

| New package | Docs to extract from root |
|-------------|--------------------------|
| `src/analytics/` (if split) | **Analytics Engine** section — full `batter_advanced_stats` / `pitcher_advanced_stats` schemas, stat ready reckoner, stats-not-computable list |
| `src/draft_ratings/` (if split) | **Draft Ratings Tables** section — all four table schemas, offset-to-year mapping, HSC pool constants |
| `src/ifa_ratings/` (if split) | IFA-specific subset of Draft Ratings section (if divergence warrants its own entry) |

**Expected root reduction from Phase 4: ~6–9K additional**

---

## Target state

| Location | Content |
|----------|---------|
| Root `AGENTS.md` | Project, DB querying, schema overview, common patterns — ~28–32K |
| `src/ratings/AGENTS.md` | Player ratings table schema |
| `src/analytics/AGENTS.md` | Analytics engine, advanced stats schemas, ready reckoner |
| `src/draft_ratings/AGENTS.md` | Draft ratings tables, offset mapping |
| `skills/AGENTS.md` | Skill architecture, protocol, visual style |
| `src/<domain>/AGENTS.md` | Per-package query conventions seeded during Phase 2–3 |

---

## Checklist

### Immediate

- [ ] Create `src/ratings/AGENTS.md` — move Player Ratings Table section
- [ ] Create `skills/AGENTS.md` — move Skill Architecture section
- [ ] Remove moved sections from root `AGENTS.md`
- [ ] Verify root drops below 40K

### Per Phase 2–3 package (repeat for each)

- [ ] Create `src/<domain>/AGENTS.md` with domain query conventions at package creation time
- [ ] If any root content becomes domain-specific, move it then

### Per Phase 4 package (if package is created)

- [ ] Create `src/analytics/AGENTS.md` — move Analytics Engine section
- [ ] Create `src/draft_ratings/AGENTS.md` — move Draft Ratings section
- [ ] Remove moved sections from root `AGENTS.md`

---

## Out of scope

- Trimming or rewriting the Database Schema Overview (it's reference-complete by design)
- Moving `PYTHON_REFACTOR_PLAN.md` content — that file is deleted once the refactor is done
- Any changes to `skills/<skill-name>/prompt.md` files

---

*Coordinate with `PYTHON_REFACTOR_PLAN.md` — this plan has no independent phases.*
