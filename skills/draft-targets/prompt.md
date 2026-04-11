# Draft Target Finder

Search for draft-eligible prospects or IFA signings matching criteria expressed in plain English.

## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the arguments to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.

**Never use `open` to launch the report.** Print the `file://` path instead and stop.

## Argument substitution

`$ARGUMENTS` is the full text of the user's invocation message (e.g. "high ceiling SS under 20").
Wherever these instructions reference `$ARGUMENTS`, use the user's full input verbatim as the search criteria.
The `<AGENT_FILLS_IN_...>` placeholders in code blocks are filled by you based on your analysis of the criteria.

## Usage

```
/draft-targets high ceiling SS under 20
/draft-targets college SP good work ethic
/draft-targets Venezuelan middle infielder
/draft-targets Dominican pitcher high ceiling
/draft-targets power bat elite ceiling affordable
/draft-targets best catching prospects
/draft-targets IFA batter prime age
```

Search for prospects matching **"$ARGUMENTS"**.

**If `$ARGUMENTS` is blank or empty** — treat it as "top prospects": apply no filters and ORDER BY `dr.rating_overall DESC`. Do not ask for criteria; run immediately.

## Prerequisites

The appropriate ratings table must exist:
- **Draft pool**: `draft_ratings` / `draft_ratings_1` / `draft_ratings_2` / `draft_ratings_3` — if missing, run `.venv/bin/python3 src/draft_ratings.py <active-save-name>` (generates all four tables)
- **IFA pool**: `ifa_ratings` table — if missing, run `.venv/bin/python3 src/ifa_ratings.py <active-save-name>`

### Step 0: Draft Year Detection (do this first)

Determine which draft class year the query refers to. The draft_ratings tables are named
by **offset from the current sim year** (not calendar year), so the names are stable across
sim advances:

| Table | Offset | Meaning |
|-------|--------|---------|
| `draft_ratings` | +0 | Current draft (upcoming) |
| `draft_ratings_1` | +1 | Next year's draft |
| `draft_ratings_2` | +2 | Two years out |
| `draft_ratings_3` | +3 | Three years out |

**If `$ARGUMENTS` contains a 4-digit year (e.g. "2029"):**
1. Query the last completed season: `SELECT MAX(year) FROM team_history WHERE league_id = 203`
2. Current draft year = last_completed_year + 1 (team_history lags by one season)
3. Compute offset = requested_year − current_draft_year
4. Map to table: offset 0 → `draft_ratings`, offset 1 → `draft_ratings_1`, etc.
5. If offset < 0 or > 3, tell the user that year is not available and stop.

**If `$ARGUMENTS` contains "next year" or "+1":** use `draft_ratings_1`.
**If `$ARGUMENTS` contains "in 2 years" or "+2":** use `draft_ratings_2`.
**If `$ARGUMENTS` contains "in 3 years" or "+3":** use `draft_ratings_3`.
**If no year indicator:** use `draft_ratings` (current draft, default).

Set `DRAFT_TABLE` to the resolved table name. Use it as the table (alias `dr`) throughout.

---

### Step 0b: Pool Detection

Determine which prospect pool the query refers to:

**IFA pool** (use `ifa_ratings` table, alias `ir`): query contains any of:
- "IFA", "international signing", "international amateur", "J2", "January signing"
- Country/region names: "Venezuelan", "Venezuela", "Dominican", "Dominican Republic",
  "Latin", "Caribbean", "Cuban", "Cuba", "Colombian", "Colombia", "Mexican", "Mexico",
  "Panamanian", "Panama", "Nicaraguan", "Nicaragua", "Brazilian", "Brazil"
- "prime age", "16-year-old", "16 year old"

**Draft pool** (use `draft_ratings` table, alias `dr`): everything else (includes
"international" alone — that filter exists in the draft pool for non-USA draftees)

Set `POOL = "ifa"` or `POOL = "draft"` and use the correct table/alias throughout.

---

### Step 1: Parse Criteria

#### If POOL = "draft" — filter `{DRAFT_TABLE} dr`:

| User says | SQL filter |
|-----------|-----------|
| SP / pitcher | `dr.player_type='pitcher'` |
| batter / hitter / position player | `dr.player_type='batter'` |
| C / catcher | `dr.position=2` |
| 1B / first base | `dr.position=3` |
| 2B / second base | `dr.position=4` |
| 3B / third base | `dr.position=5` |
| SS / shortstop | `dr.position=6` |
| LF / left field | `dr.position=7` |
| CF / center field | `dr.position=8` |
| RF / right field | `dr.position=9` |
| OF / outfielder | `dr.position IN (7,8,9)` |
| IF / infielder | `dr.position IN (3,4,5,6)` |
| middle infielder | `dr.position IN (4,6)` |
| lefty bat / left-handed hitter | `dr.bats=2` |
| righty bat | `dr.bats=1` |
| switch hitter | `dr.bats=3` |
| lefty arm / LHP | `dr.throws=2` |
| righty arm / RHP | `dr.throws=1` |
| under N / age < N | `dr.age < N` |
| N or younger | `dr.age <= N` |
| high ceiling | `dr.flag_high_ceiling=1` (pot >= 55) |
| elite ceiling / blue chip | `dr.flag_elite_ceiling=1` (pot >= 65) |
| college / safe / advanced / low risk | `dr.college=1` |
| high school / HS / prep / upside | `dr.college=0` |
| international / IFA | `dr.flag_international=1` |
| domestic / USA | `dr.domestic=1` |
| good work ethic / high work ethic | `dr.work_ethic > 130` |
| elite work ethic | `dr.flag_elite_we=1` |
| high IQ / smart | `dr.intelligence > 130` |
| affordable / low demands | `dr.flag_demanding=0` |
| above-slot / demanding | `dr.flag_demanding=1` |
| power bat / power hitter | `dr.rating_tools > 60` |
| offense focused / offensive | `dr.rating_tools > 50` |
| rating > N | `dr.rating_overall > N` |
| top prospects / best | (no filter — just ORDER BY rating_overall DESC) |
| highest potential | ORDER BY dr.pot DESC, dr.rating_overall DESC |

#### If POOL = "ifa" — filter `ifa_ratings ir`:

| User says | SQL filter |
|-----------|-----------|
| SP / pitcher | `ir.player_type='pitcher'` |
| batter / hitter / position player | `ir.player_type='batter'` |
| C / catcher | `ir.position=2` |
| 1B / first base | `ir.position=3` |
| 2B / second base | `ir.position=4` |
| 3B / third base | `ir.position=5` |
| SS / shortstop | `ir.position=6` |
| LF / left field | `ir.position=7` |
| CF / center field | `ir.position=8` |
| RF / right field | `ir.position=9` |
| OF / outfielder | `ir.position IN (7,8,9)` |
| IF / infielder | `ir.position IN (3,4,5,6)` |
| middle infielder | `ir.position IN (4,6)` |
| lefty bat | `ir.bats=2` |
| righty bat | `ir.bats=1` |
| switch hitter | `ir.bats=3` |
| LHP | `ir.throws=2` |
| RHP | `ir.throws=1` |
| age 16 / prime age | `ir.age=16` OR `ir.flag_prime_age=1` |
| age N / under N | `ir.age=N` OR `ir.age < N` |
| Venezuelan | `ir.nation_id=51` |
| Dominican / Dominican Republic | `ir.nation_id=55` |
| Cuban / Cuba | `ir.nation_id=56` |
| Mexican / Mexico | `ir.nation_id=130` |
| Colombian / Colombia | `ir.nation_id=40` |
| Panamanian / Panama | `ir.nation_id=143` |
| (other nations — use nation name) | `ir.nation ILIKE '%Venezuela%'` etc. |
| high ceiling | `ir.flag_high_ceiling=1` |
| elite ceiling / blue chip | `ir.flag_elite_ceiling=1` |
| good work ethic | `ir.work_ethic > 130` |
| elite work ethic | `ir.flag_elite_we=1` |
| high IQ / smart | `ir.intelligence > 130` |
| affordable / low demands | `ir.flag_demanding=0` |
| power bat / power hitter | `ir.rating_tools > 60` |
| offense focused / offensive | `ir.rating_tools > 50` |
| top prospects / best | (no filter — ORDER BY ir.rating_overall DESC) |
| highest potential | ORDER BY ir.pot DESC, ir.rating_overall DESC |

If a nation name is used but the exact nation_id is unknown, use:
`ir.nation ILIKE '%<nation_name>%'`

Build a list of active filters. Determine the ORDER BY (default: `rating_overall DESC`).
Default limit: 25 results.

---

### Step 2: Generate the HTML report

#### If POOL = "draft":

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from draft_targets import generate_draft_targets_report
from shared_css import load_saves_registry
save_name = load_saves_registry()["active"]
where = "<AGENT_FILLS_IN_SQL_WHERE_CLAUSE>"
criteria = "<AGENT_FILLS_IN_CRITERIA_LABEL>"
order_by = "<AGENT_FILLS_IN_ORDER_BY>"
path, rows = generate_draft_targets_report(save_name, criteria, where, order_by=order_by)
print("GENERATED:" + str(path))
print("RESULT_COUNT:" + str(len(rows)))
for r in rows:
    print(r)
PYEOF
```

#### If POOL = "ifa":

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from ifa_targets import generate_ifa_targets_report
from shared_css import load_saves_registry
save_name = load_saves_registry()["active"]
where = "<AGENT_FILLS_IN_SQL_WHERE_CLAUSE>"
criteria = "<AGENT_FILLS_IN_CRITERIA_LABEL>"
order_by = "<AGENT_FILLS_IN_ORDER_BY>"
path, rows = generate_ifa_targets_report(save_name, criteria, where, order_by=order_by)
print("GENERATED:" + str(path))
print("RESULT_COUNT:" + str(len(rows)))
for r in rows:
    print(r)
PYEOF
```

If `RESULT_COUNT:0` — relax filters one at a time (drop the most restrictive first), retry
with a revised WHERE clause, and note which filters were relaxed in the analysis.

If > 0 results — continue to Step 3.

---

### Step 3: Write the callout summary

The HTML file has a `<!-- FA_CALLOUT_SUMMARY -->` placeholder. Replace it with a
`<div class="summary">` containing 2–4 sentences:
- Lead with the top prospect recommendation
- Note pool depth, position mix, any flags (elite ceilings, prime ages, character concerns)
- For IFA: note nation composition and signing-window timing
- If filters were relaxed, note which ones

Read the file, replace the placeholder, write it back. Then print the report path:

```bash
echo "file://<path printed after GENERATED:>"
```

### Step 4: Print Terminal Summary

Print the criteria string, pool type, and result count, then a compact table of top results:

For draft pool:
```
Draft targets [DRAFT POOL]: "$ARGUMENTS" — N results

 #  Name                  Pos  Age  OA/POT  Rating  B/T  Type  Tools  Dev    Flags
 1  Butch Broadley        P    18   26/75   B+ 75.3  R/R  HS    64.6   79.0   🌟 ⚡
```

For IFA pool:
```
Draft targets [IFA POOL]: "$ARGUMENTS" — N results

 #  Name                  Pos  Age  OA/POT  Rating  B/T  Nation          Tools  Dev    Flags
 1  Carlos Mendez         SS   16   22/68   B+ 72.1  R/R  Venezuela       61.2   74.0   🌟 👶 ⚡
```

Show up to 15 rows.

CRITICAL: Do not reference any player not in the results. Report only what the data shows.

### Position code reference
1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF
bats: 1=R, 2=L, 3=S  |  throws: 1=R, 2=L
