---
name: trade-targets
description: Find realistic trade return candidates on other MLB teams in exchange for one or more Tigers players. Shows value-matched targets by position need with contract details.
argument-hint: <player(s) to offer, optionally what you need, e.g. "Colt Keith" or "Framber Valdez, want young IF">
---

# Trade Target Finder

Given one or more Tigers players to offer, find realistic return candidates on other teams.

## IMPORTANT: Always use a fresh agent

Delegate this entire task to a fresh Agent (subagent_type: "general-purpose", model: "sonnet").
Do NOT do the work inline.

## Usage

```
/trade-targets Colt Keith
/trade-targets Jackson Jobe and Kyle Finnegan
/trade-targets surplus outfielders, need starting pitching
/trade-targets Framber Valdez, want a young corner infielder with upside
/trade-targets Riley Greene, controllable SP in return
```

## Agent prompt template

Use this as the agent prompt, substituting from $ARGUMENTS:

---

Find trade targets for the Detroit Tigers based on: **"$ARGUMENTS"** in `/Users/raywalker/source/ootp-db`.

### Step 1: Look Up Offered Player(s)

Query the Tigers roster to identify what's being offered:

```bash
.venv/bin/python3 << 'PYEOF'
import json
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os
from pathlib import Path
load_dotenv(Path(".env"))
save = json.loads(open("saves.json").read())["active"]
db = save.lower().replace("-", "_").replace(" ", "_")
engine = create_engine(f"{os.getenv('POSTGRES_URL')}/{db}")
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT p.player_id, p.first_name, p.last_name, pr.position, pr.age,
               pr.oa, pr.pot, pr.rating_overall, pr.player_type, pr.wrc_plus, pr.war,
               pc.years, pc.current_year, pc.salary0, prs.mlb_service_years
        FROM players p
        JOIN player_ratings pr ON pr.player_id = p.player_id
        LEFT JOIN players_contract pc ON pc.player_id = p.player_id
        LEFT JOIN players_roster_status prs ON prs.player_id = p.player_id
        WHERE p.team_id = 10 AND p.free_agent = 0 AND p.retired = 0
        ORDER BY pr.rating_overall DESC
    """)).fetchall()
    for r in result:
        print(r)
PYEOF
```

Identify the player(s) matching `$ARGUMENTS`. If the user named specific players, find exact name matches. If they described a category (e.g., "surplus outfielders"), pick the lowest-rated players at that position.

**Record for each offered player:**
- player_id, name, position, age, rating_overall, player_type
- wrc_plus (displayed as FIP for pitchers), war
- years_remaining = years - current_year, salary0 as approximate current salary
- mlb_service_years (controls pre-arb / arb / FA status)

Build the `offered_where` SQL fragment to match these players by name, e.g.:
`p.last_name = 'Keith' AND p.first_name = 'Colt'`
For multiple players: `(p.last_name = 'Jobe') OR (p.last_name = 'Finnegan')`

### Step 2: Assess Trade Value

Use the offered player's **OA** (OOTP's own 20-80 rating) as the trade value currency — not
`rating_overall`. The OOTP AI evaluates trades using OA, not composite analytical scores.

Map the offered player's OA to a target OA range:

| Offered OA | Value tier | Target OA range |
|------------|-----------|----------------|
| 75+        | Elite      | 68–80          |
| 65–74      | Above avg  | 58–74          |
| 55–64      | Average    | 48–65          |
| 45–54      | Below avg  | 38–56          |
| <45        | Fringe     | 30–50          |

Adjust the range (max ±4 OA points total, not cumulative):
- **Pre-arb** (mlb_service_years < 3): +4 (locked-in cheap years are premium)
- **FA-year** (years_remaining ≤ 1): −4 (rental discount)
- **Package deal** (2+ players): use the highest-OA player's tier as the anchor

### Step 3: Identify Tigers' Needs

If `$ARGUMENTS` specifies a target type (e.g., "need starting pitching", "want a SS"), use that.
Otherwise, check which positions are thin:

```bash
.venv/bin/python3 << 'PYEOF'
import json
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os
from pathlib import Path
load_dotenv(Path(".env"))
save = json.loads(open("saves.json").read())["active"]
db = save.lower().replace("-", "_").replace(" ", "_")
engine = create_engine(f"{os.getenv('POSTGRES_URL')}/{db}")
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT pr.position, count(*) as cnt,
               round(avg(pr.rating_overall)::numeric, 1) as avg_rating,
               max(pr.rating_overall) as best_rating
        FROM team_roster tr
        JOIN player_ratings pr ON pr.player_id = tr.player_id
        WHERE tr.team_id = 10 AND tr.list_id IN (1, 2)
        GROUP BY pr.position
        ORDER BY avg_rating ASC
    """)).fetchall()
    for r in result:
        print(r)
PYEOF
```

Identify the 2–3 thinnest positions (lowest avg_rating or fewest players). Exclude the offered player's position from the needs list.

### Step 4: Build the target_where Clause

Combine position need, value range, and any explicit user criteria:

**Position filters:**
| User says | SQL |
|-----------|-----|
| SP / starter / starting pitcher | `pr.player_type='pitcher' AND pr.position=1` |
| RP / reliever / closer | `pr.player_type='pitcher'` |
| C, 1B, 2B, 3B, SS, LF, CF, RF | `pr.position=2/3/4/5/6/7/8/9` |
| OF / outfielder | `pr.position IN (7,8,9)` |
| IF / infielder | `pr.position IN (3,4,5,6)` |
| corner IF | `pr.position IN (3,5)` |
| middle IF | `pr.position IN (4,6)` |
| batter / hitter / position player | `pr.player_type='batter'` |

**Other filters:**
| User says | SQL |
|-----------|-----|
| young / under N / under-N | `pr.age < N` |
| controllable / years of control | `(pc.years - pc.current_year) >= 2` |
| affordable / cheap | `pc.salary0 < 10000000` |
| high ceiling / upside / prospect | `pr.flag_high_ceiling=true` |
| good defense | `pr.rating_defense > 60` |
| durable / low injury risk | `pr.prone_overall < 100` |
| wRC+ > N | join batter_advanced_stats: `bas.wrc_plus > N` |
| FIP < N | join pitcher_advanced_stats: `pas.fip < N` |
| WAR > N | `pr.war > N` |

Always include the OA value range: `pr.oa BETWEEN {floor} AND {ceil}`

`rating_overall` is **not** used for filtering — it is the sort order (`order_by="pr.rating_overall DESC"`),
so the analytically best targets within the OA band surface first. Do not use `rating_overall` in the WHERE clause.

Default target_where (no position specified): `pr.oa BETWEEN {floor} AND {ceil}`

**Tradeable signal** — teams trade players they have a surplus of, or want to shed salary on, not
their best player at a position. Note in the Step 6 analysis which targets look like realistic
move candidates based on:
- High salary relative to their OA (potential salary-dump trade)
- Veteran age (32+) on a rebuilding team  
- Short years_remaining (rental a contender might flip)

### Step 5: Generate the HTML Report

```bash
.venv/bin/python3 << 'PYEOF'
import sys, json
sys.path.insert(0, "src")
from trade_targets import generate_trade_targets_report
save_name = json.loads(open("saves.json").read())["active"]
offered_where = "<AGENT FILLS: SQL WHERE matching offered Tigers player(s)>"
target_where = "<AGENT FILLS: SQL WHERE for return targets>"
target_join = "<AGENT FILLS: JOIN clause for bas/pas, or empty string>"
offer_label = "<AGENT FILLS: human label, e.g. 'Colt Keith'>"
highlight = <AGENT FILLS: list of (col_key, label) tuples or None>
path, data = generate_trade_targets_report(
    save_name, offer_label, offered_where, target_where,
    target_join=target_join, highlight=highlight
)
print(f"GENERATED:{path}")
print(f"OFFERED:{len(data['offered'])}")
print(f"TARGETS:{len(data['targets'])}")
for r in data["targets"]:
    print(r)
PYEOF
```

If `TARGETS:0` — broaden one filter at a time: widen the OA range by ±5 points, or expand the position filter (e.g., IF instead of SS), then retry once and note what changed.

If `OFFERED:0` — the player name wasn't found. Re-check the Step 1 results for near-matches (spelling, hyphenation). Retry with corrected name.

### Step 6: Write the Callout Summary

The HTML file has a `<!-- TRADE_CALLOUT_SUMMARY -->` placeholder. Replace it with a
`<div class="summary">` containing 2–4 sentences:
- Lead with what the Tigers can realistically get back (value tier + position)
- Name the top 1–2 specific targets and why they fit
- Flag any concerns: no-trade clauses, injury risk, value mismatch, thin market
- If filters were relaxed: note which one and what that means for the market

Read the file, replace the placeholder, write it back. Then open the report — use the exact path printed after `GENERATED:` above:

```bash
open /Users/raywalker/source/ootp-db/reports/<save_name>/trade_targets/<slug>.html
```

### Step 7: Print Terminal Summary

```
Trade targets: "Colt Keith" — 18 return candidates

Offering:
  Colt Keith     3B   26   OA:51   Rating:57.7   wRC+:108   WAR:2.1   $2.5M   5y left

Top return targets:
 #  Name                  Pos  Team  Age  OA  Rating   wRC+  WAR   Salary  Yrs
 1  ...
```

Use wRC+ label for batters, FIP for pitchers. Show up to 15 targets in the table.

Then print: `~ Model: claude-sonnet-4-6 | ~12–20K in / ~4–6K out | est. 10–16¢`

CRITICAL: Only reference players in the query results. Do not invent trade packages.

### Position code reference
1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF
bats: 1=R, 2=L, 3=S  |  throws: 1=R, 2=L

### Highlight columns (pick up to 2 based on query focus)

| Query focus | highlight value |
|-------------|----------------|
| defense / fielding | `[("rating_defense", "Defense")]` |
| offense / hitting | `[("rating_offense", "Offense"), ("rating_contact_quality", "Contact")]` |
| potential / upside / ceiling | `[("rating_potential", "Potential")]` |
| durability / health | `[("rating_durability", "Durability")]` |
| development / work ethic | `[("rating_development", "Dev")]` |
| no clear focus | `None` |

---
