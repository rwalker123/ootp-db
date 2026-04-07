# Free Agent Finder

Search for free agents matching criteria expressed in plain English.

## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the arguments to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.

## Argument substitution

`$ARGUMENTS` is the full text of the user's invocation message (e.g. "lefty SP under 28 with low injury risk").
Wherever these instructions reference `$ARGUMENTS`, use the user's full input verbatim as the search criteria.
The `<AGENT_FILLS_IN_...>` placeholders in code blocks are filled by you based on your analysis of the criteria — they are not substituted from the user's message directly.

## Usage

```
/free-agents lefty SP under 28 with FIP under 3.5 and low injury risk
/free-agents contact SS, low greed, durable
/free-agents power bats high ceiling affordable
/free-agents starting pitcher under 30, good work ethic, WAR above 3
```

Search for free agents matching **"$ARGUMENTS"**.

### Step 1: Parse Criteria

**Default player_type rule:** Unless the query explicitly mentions pitchers, SP, RP, closer,
or reliever, always add `pr.player_type='batter'` to the filters. A generic batting search
("best bat", "power hitter", "contact SS") must never return pitchers.

Translate the natural language query into SQL filters using this mapping:

| User says | SQL filter |
|-----------|-----------|
| SP / starter / starting pitcher | `pr.player_type='pitcher'` (overrides batter default) + prefer starters (gs > g/2 in pitcher_advanced_stats) |
| RP / reliever / closer | `pr.player_type='pitcher'` (overrides batter default) + prefer relievers |
| C, 1B, 2B, 3B, SS, LF, CF, RF | `pr.position=2/3/4/5/6/7/8/9` |
| OF / outfielder | `pr.position IN (7,8,9)` |
| IF / infielder | `pr.position IN (3,4,5,6)` |
| batter / hitter / position player | `pr.player_type='batter'` |
| pitcher | `pr.player_type='pitcher'` (overrides batter default) |
| lefty bat / left-handed hitter | `p.bats=2` |
| righty bat | `p.bats=1` |
| switch hitter | `p.bats=3` |
| lefty arm / lefty pitcher / LHP | `p.throws=2` |
| righty arm / RHP | `p.throws=1` |
| under N / age < N / younger than N | `pr.age < N` |
| N or younger | `pr.age <= N` |
| low injury risk / durable / healthy | `pr.prone_overall < 100` |
| high injury risk filter (avoid) | `pr.prone_overall < 150` |
| affordable / low greed / cheap | `pr.greed < 120` |
| budget / very affordable | `pr.greed < 100` |
| demanding / skip greedy | `pr.greed > 160` (to exclude, use `pr.greed <= 160`) |
| high ceiling / upside | `pr.flag_high_ceiling=true` |
| leader / captain | `pr.flag_leader=true` |
| good work ethic | `pr.work_ethic > 130` |
| elite work ethic | `pr.work_ethic > 160` |
| high IQ / smart | `pr.intelligence > 130` |
| wRC+ > N | join batter_advanced_stats: `bas.wrc_plus > N` |
| FIP < N | join pitcher_advanced_stats: `pas.fip < N` |
| WAR > N | `pr.war > N` |
| rating > N | `pr.rating_overall > N` |
| contact hitter | `pr.rating_contact_quality > 55` |
| power hitter | `bas.iso > 0.180` (join batter_advanced_stats) |
| good defense | `pr.rating_defense > 60` |

Build a list of active filters from the query. Include any filter you are confident
applies; omit anything ambiguous. Default limit: 25 results.

Also pick **highlight columns** — up to 2 extra stat columns to show in the table based
on the query's focus. Use at most 2. If no clear focus, use `None`.

| Query focus              | highlight value                                                        |
|--------------------------|------------------------------------------------------------------------|
| defense / fielding       | `[("rating_defense", "Defense")]`                                      |
| offense / hitting        | `[("rating_offense", "Offense"), ("rating_contact_quality", "Contact")]` |
| discipline / plate eye   | `[("rating_discipline", "Discipline")]`                                |
| potential / upside       | `[("rating_potential", "Potential")]`                                  |
| durability / health      | `[("rating_durability", "Durability")]`                                |
| development / work ethic | `[("rating_development", "Dev")]`                                      |
| clubhouse / leadership   | `[("rating_clubhouse", "Clubhouse")]`                                  |
| speed / baserunning      | `[("rating_baserunning", "Speed")]`                                    |
| (pitcher) command        | `[("rating_defense", "Command")]`                                      |
| (pitcher) dominance / K  | `[("rating_discipline", "Dominance")]`                                 |
| no clear focus           | `None`                                                                 |

### Step 2: Generate the HTML report

Using the WHERE clause, JOIN clause, order_by, and highlight from Step 1:

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from free_agents import generate_free_agents_report
from shared_css import load_saves_registry
where = "<AGENT_FILLS_IN_SQL_WHERE_CLAUSE>"
join = "<AGENT_FILLS_IN_JOIN_CLAUSE_IF_NEEDED>"
criteria = "<AGENT_FILLS_IN_CRITERIA_LABEL>"
highlight = <AGENT_FILLS_IN_HIGHLIGHT_OR_NONE>
save_name = load_saves_registry()["active"]
path, rows = generate_free_agents_report(save_name, criteria, where, join,
    highlight=highlight)
print(f"GENERATED:{path}")
print(f"RESULT_COUNT:{len(rows)}")
for r in rows:
    print(r)
PYEOF
```

If `RESULT_COUNT:0` — relax filters one at a time (drop the most restrictive first), retry
with a revised WHERE clause, and note which filters were relaxed in the analysis.

If > 0 results — continue to Step 3.

### Step 3: Write the callout summary

The HTML file has a `<!-- FA_CALLOUT_SUMMARY -->` placeholder. Replace it with a
`<div class="summary">` containing 2–4 sentences:
- Lead with the top recommendation (or "no clear fit" if market is thin)
- Note market depth/quality and any caveats (filters relaxed, positional mismatch)

Read the file, replace the placeholder, write it back. Then open the report — use the exact path printed after `GENERATED:` above:

```bash
open <path-from-GENERATED-output>
```

### Step 4: Print Terminal Summary

Print the criteria string and result count, then a compact table of top results:

```
Free agents: "lefty SP under 28, low injury risk" — 8 results

 #  Name                    Pos  Age  OA  Rating   FIP    WAR  Injury    Greed
 1  Noah Schultz            SP   24   61   69.2   2.95   2.9   Normal    Average
 2  ...
```

Use wRC+ label for batters, FIP for pitchers. Show up to 15 rows in terminal.

CRITICAL: Do not reference any player not in the results. Report only what the data shows.

### Position code reference
1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF
bats: 1=R, 2=L, 3=S  |  throws: 1=R, 2=L

### Stats reference bands
| Hitting | Good | Average | Poor |
|---------|------|---------|------|
| wRC+ | 115+ | 100 | <85 |
| K% | <18% | ~22% | >28% |
| BB% | 10%+ | ~8% | <6% |

| Pitching | Good | Average | Poor |
|----------|------|---------|------|
| FIP | <3.50 | ~4.00 | >4.50 |
| K-BB% | 18%+ | ~14% | <8% |
| WHIP | <1.15 | ~1.30 | >1.40 |
