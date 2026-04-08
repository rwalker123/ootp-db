# Trade Target Finder

Given one or more players to offer or acquire, find the matching trade candidates.

## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the arguments to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.

**Never use `open` to launch the report.** Print the `file://` path instead and stop.

## Argument substitution

`$ARGUMENTS` is the full text of the user's invocation message (e.g. "Riley Greene" or "acquiring Aaron Judge").
Wherever these instructions reference `$ARGUMENTS`, use the user's full input verbatim.
The `<AGENT FILLS: ...>` and `<PLAYER_NAME_OR_EMPTY>` / `<MODE>` placeholders in code blocks are derived by you from the query — they are not direct substitutions from the user's message.

## Usage

```
/trade-targets Jack Morris
/trade-targets Jackson Jobe and Kyle Finnegan
/trade-targets surplus outfielders, need starting pitching
/trade-targets Framber Valdez, want a young corner infielder with upside
/trade-targets Riley Greene, controllable SP in return
/trade-targets acquiring Aaron Judge
/trade-targets what would it cost to get Shohei Ohtani
/trade-targets targeting Corbin Carroll
```

Find trade targets based on: **"$ARGUMENTS"**.

### Step 0: Parse Arguments and Run Pre-flight Lookup

**Direction detection** — scan `$ARGUMENTS` for keywords (case-insensitive):
- `acquiring`, `targeting`, `want to get`, `to get`, `cost to get`, `what would it cost` → **mode = "acquiring"**
- Everything else (default) → **mode = "offering"**

**Mode meanings:**
- `offering`: You're trading away a player on your team. `offered_where` matches your player; `target_base_where` filters other teams.
- `acquiring`: You want a player on another team. `offered_where` matches that player; `target_base_where` filters players on your team you'd give up.

**Player name extraction** — parse `$ARGUMENTS` for the key player name(s):
- Named player (e.g., "Jack Morris", "acquiring Aaron Judge") → extract "First Last"
- Multiple players (e.g., "Jackson Jobe and Kyle Finnegan") → extract first player name for the primary lookup; build `offered_where` to cover both by name
- Category only (e.g., "surplus outfielders, need SP") → set player_name to empty string

Then run the pre-flight lookup (substituting the parsed values):

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from trade_targets import lookup_trade_context
from shared_css import load_saves_registry
save_name = load_saves_registry()["active"]
lookup_trade_context(save_name, player_name="<PLAYER_NAME_OR_EMPTY>", mode="<MODE>")
PYEOF
```

Parse the output:
- `MY_TEAM_ID=<n>` → `my_team_id`
- `MY_TEAM_ABBR=<abbr>` / `MY_TEAM_NAME=<name>` → used in the callout (Step 6)
- `TRADE_POS_ADJUSTMENTS=<json>` → position-class OA adjustment table (parse as JSON; string keys)
- `TRADE_TIER2_OA_ABOVE=<n>` → how far above the band ceiling the add-on tier extends
- `PLAYER=<pipe-delimited>` → matched player fields in order:
  `player_id|first_name|last_name|position|age|oa|pot|rating_overall|player_type|wrc_fip|war|yrs_remaining|salary|svc_years|team_abbr`
- `POSITION_DISCOUNT=<n>` → printed immediately after each PLAYER= line; the OA adjustment for that player's position/role
- `NEED=<pos>|<cnt>|<avg_rating>|<best_rating>` → positional needs, ascending by avg_rating (offering mode only)

**After parsing:**

For a matched `PLAYER` line, record the player data and build `offered_where`:
- `p.first_name = 'First' AND p.last_name = 'Last'`
- For multiple players: `(p.last_name = 'Jobe') OR (p.last_name = 'Finnegan')`

For a category-only query (no PLAYER line), build `offered_where` from the positional criteria in `$ARGUMENTS` targeting your team (e.g., `p.team_id = my_team_id AND pr.position IN (7,8,9) ORDER BY pr.rating_overall ASC LIMIT 1`).

### Step 1: Assess Trade Value

Use the offered player's **OA** (OOTP's own 20-80 rating) as the trade value currency — not
`rating_overall`. The OOTP AI evaluates trades using OA, not composite analytical scores.

**Apply position-class adjustment** to get the effective OA:

```
effective_oa = raw_oa + position_discount
```

- For a named player: use `POSITION_DISCOUNT` from the pre-flight output.
- For a category-only query: look up the offered player's position in `TRADE_POS_ADJUSTMENTS`.
  Key format: string integers for position players (`"3"` = 1B), string role names for pitchers
  (`"sp"`, `"rp"`, `"closer"`). Infer the pitcher sub-role from context (SP vs. RP/Closer).

**Apply contract adjustments** (max ±4 OA total, not cumulative, applied after position adj):
- **Pre-arb** (svc_years < 3): +4 (locked-in cheap years are a premium)
- **FA-year** (yrs_remaining ≤ 1): −4 (rental discount)
- **Package deal** (2+ players): use the highest-OA player as the anchor

**Map effective_oa to the target band** using this tier table:

| Effective OA | Value tier | Target OA band |
|-------------|-----------|----------------|
| 75+         | Elite      | 68–80          |
| 65–74       | Above avg  | 58–74          |
| 55–64       | Average    | 48–65          |
| 45–54       | Below avg  | 38–56          |
| <45         | Fringe     | 30–50          |

Record `oa_floor` and `oa_ceil` from this table. These are passed directly to Python — do **not**
include an OA filter in `target_base_where`.

Python will internally build:
- **Tier 1** (straight swap): `pr.oa BETWEEN oa_floor AND oa_ceil`
- **Tier 2** (add-on required): `pr.oa BETWEEN oa_ceil+1 AND oa_ceil+TRADE_TIER2_OA_ABOVE`

### Step 2: Identify Your Team's Needs (offering mode only)

Skip this step in **acquiring** mode — you already know what you're giving up (players on your team in the target OA range).

If `$ARGUMENTS` specifies a target type (e.g., "need starting pitching", "want a SS"), use that directly.
Otherwise use the `NEED=` lines from the Step 0 output — identify the 2–3 thinnest positions (lowest avg_rating or fewest players) and exclude the offered player's position.

### Step 3: Build the target_base_where Clause

Build a SQL WHERE clause with **position and type filters only** — no OA filter. OA is handled by Python via `oa_floor` and `oa_ceil`.

**Position filters:**
| User says | SQL |
|-----------|-----|
| SP / starter / starting pitcher | `pr.player_type='pitcher' AND pr.position=1 AND p.role=11` |
| RP / reliever | `pr.player_type='pitcher' AND p.role IN (12,13)` |
| closer | `pr.player_type='pitcher' AND p.role=13` |
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

`rating_overall` is **not** used for filtering — it is the sort order, so the analytically
best targets within each OA band surface first.

Default target_base_where (no position specified): `1=1` (no position filter; OA band is the only constraint).

**Tradeable signal** — teams trade players they have a surplus of, or want to shed salary on, not
their best player at a position. Note in the Step 6 analysis which targets look like realistic
move candidates based on:
- High salary relative to their OA (potential salary-dump trade)
- Veteran age (32+) on a rebuilding team
- Short years_remaining (rental a contender might flip)

### Step 4: Generate the HTML Report

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from trade_targets import generate_trade_targets_report
from shared_css import load_saves_registry
save_name = load_saves_registry()["active"]
my_team_id = <MY_TEAM_ID>
offered_where = "<AGENT FILLS: SQL WHERE matching offered/targeted player(s)>"
target_base_where = "<AGENT FILLS: position/type SQL WHERE, no OA filter>"
target_join = "<AGENT FILLS: JOIN clause for bas/pas, or empty string>"
offer_label = "<AGENT FILLS: human label, e.g. 'Babe Ruth' or 'Mickey Mantle'>"
highlight = <AGENT FILLS: list of (col_key, label) tuples or None>
mode = "<AGENT FILLS: 'offering' or 'acquiring'>"
oa_floor = <AGENT FILLS: integer, band floor from Step 1>
oa_ceil = <AGENT FILLS: integer, band ceiling from Step 1>
path, data = generate_trade_targets_report(
    save_name, offer_label, offered_where, target_base_where,
    oa_floor=oa_floor, oa_ceil=oa_ceil,
    my_team_id=my_team_id, mode=mode,
    target_join=target_join, highlight=highlight
)
print("GENERATED:" + str(path))
print("OFFERED:" + str(len(data["offered"])))
print("TIER1:" + str(len(data["tier1"])))
print("TIER2:" + str(len(data["tier2"])))
for r in data["tier1"]:
    print(r)
print("---TIER2---")
for r in data["tier2"]:
    print(r)
PYEOF
```

If `TIER1:0 AND TIER2:0` — broaden one filter at a time: widen the position filter (e.g., IF instead of SS)
or remove the most restrictive filter, then retry once and note what changed. A non-empty Tier 2
with an empty Tier 1 is expected and correct — do **not** broaden in that case.

If `OFFERED:0` — the player name wasn't found. Re-check the Step 1 results for near-matches
(spelling, hyphenation). Retry with corrected name.

### Step 5: Write the Callout Summary

The HTML file has a `<!-- TRADE_CALLOUT_SUMMARY -->` placeholder. Replace it with a
`<div class="summary">` containing 2–4 sentences:

**If Tier 1 has players:**
- Lead with what `{my_team_name}` can realistically get in a straight swap (value tier + position)
- Name the top 1–2 specific Tier 1 targets and why they fit
- If Tier 2 also has players, note that better options exist but require an add-on
- Flag concerns: no-trade clauses, injury risk, thin market

**If Tier 1 is empty:**
- Lead with: "No straight-swap candidates were found at this value level."
- If Tier 2 has players: name the top 1–2 and state what kind of add-on (OA range of extra piece needed) would close the gap
- If both are empty: the market is thin; suggest broadening the position filter

**Acquiring mode:**
- Lead with what it would cost `{my_team_name}` to acquire the target (OA tier + what you'd give up)
- Name the top 1–2 specific direct-match players from your roster
- If no direct matches, name top add-on tier candidates and estimate what extra would be needed
- Flag concerns: giving up too much, no-trade on target, whether it's the right time to buy

Read the file, replace the placeholder, write it back. Then print the report path:

```bash
echo "file://<path-from-GENERATED-output>"
```

### Step 6: Print Terminal Summary

```
Trade targets: "Lou Whitaker" — 5 direct, 12 with add-on

Offering:
  Lou Whitaker     3B   26   OA:51   Adj:+0   Eff OA:51   Band:38–56   Rating:57.7   wRC+:108   WAR:2.1   $2.5M   5y left

Straight Swap (OA 38–56):
 #  Name                  Pos  Team  Age  OA  Rating   wRC+  WAR   Salary  Yrs
 1  ...

Add-On Required (OA 57–66):
 #  Name                  Pos  Team  Age  OA  Rating   wRC+  WAR   Salary  Yrs
 1  ...
```

Use wRC+ label for batters, FIP for pitchers. Show up to 8 players per tier in the terminal table.

CRITICAL: Only reference players in the query results. Do not invent trade packages.

### Position code reference
1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF
role: 11=SP, 12=RP, 13=Closer
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
