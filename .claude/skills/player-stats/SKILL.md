---
name: player-stats
description: Look up all advanced stats for an OOTP player by name, with a summary analysis.
argument-hint: <first-name> <last-name>
---

# Player Stats Lookup

Look up comprehensive stats for an OOTP player. 

## IMPORTANT: Always use a fresh agent

To prevent context bleedover between players, you MUST delegate this entire task to a 
fresh Agent (subagent_type: "general-purpose"). Pass the full player name and all 
instructions below to the agent. Do NOT do the work inline in the current conversation.

## Agent prompt template

Use this as the agent prompt, substituting the player name from $ARGUMENTS:

---

Generate an OOTP player report for **$ARGUMENTS** using `src/report.py`.

### Step 1: Generate (or retrieve cached) the report

```bash
.venv/bin/python3 << 'PYEOF'
import sys, json
sys.path.insert(0, "src")
from report import generate_player_report
save_name = json.loads(open("saves.json").read())["active"]
path, data = generate_player_report(save_name, "<FIRST>", "<LAST>")

if data is None:
    print(f"CACHED:{path}")
else:
    adv = data.get("advanced")
    padv = data.get("pitching_advanced")
    val = data.get("value")
    br = data.get("batting_ratings")
    pr = data.get("pitching_ratings")

    print(f"GENERATED:{path}")
    if val:
        print(f"OA={val[2]}, POT={val[3]}")
    else:
        print("No value ratings (free agent)")

    if br:
        print(f"Contact={br[0]}, Gap={br[1]}, Power={br[2]}, Eye={br[3]}, AvoidK={br[4]}, BABIP={br[5]}")
        print(f"Speed={br[8]}")

    if pr:
        print(f"Stuff={pr[0]}, Movement={pr[1]}, Control={pr[2]}")

    p = data["player"]
    pos = p[4]
    print(f"Position={pos}")

    has_batting = "career_overall" in data and len(data["career_overall"]) > 0
    has_pitching = "career_pitching" in data and len(data["career_pitching"]) > 0
    is_two_way = has_batting and has_pitching
    print(f"Two-way={is_two_way}, has_batting={has_batting}, has_pitching={has_pitching}")

    if adv:
        print("\nBATTING ADVANCED:")
        for k, v in adv.items():
            print(f"  {k}={v}")

    if padv:
        print("\nPITCHING ADVANCED:")
        for k, v in padv.items():
            print(f"  {k}={v}")

    if has_batting:
        print("\nBatting Career:")
        for row in data["career_overall"]:
            yr, tid, g, pa, ab, h, d, t, hr, bb, k, rbi, sb, cs, hp, sf, sh, r, war, wpa = row
            ba = h/ab if ab > 0 else 0
            print(f"  {yr}: {g}G {pa}PA .{ba:.3f} {hr}HR {war:.1f}WAR")

    if has_pitching:
        print("\nPitching Career:")
        for row in data["career_pitching"]:
            yr, tid, g, gs, w, l, s, ip, ha, hra, bb, k, er, hld, bf, hp, qs, cg, sho, gb, fb, war, wpa = row
            era = er/ip*9 if ip > 0 else 0
            print(f"  {yr}: {g}G {gs}GS {w}-{l} {float(ip):.1f}IP {era:.2f}ERA {war:.1f}WAR")
PYEOF
```

If the output starts with `CACHED:` — extract the path (everything after `CACHED:`), then run:

```bash
open <extracted_path>
```

Then print:
`[Player name] — report is current (generated since last import). See browser for full stats.`
`~ Cache hit — skipped regen | est. 1–2¢`
Then STOP — do not regenerate or read the HTML file.

If the output starts with `GENERATED:` — continue to Step 2.

If the player is not found, try a fuzzy match:
```sql
SELECT player_id, first_name, last_name FROM players WHERE last_name ILIKE '<partial>%'
```

### Step 2: Write the scouting summary and insert it

The HTML has a single placeholder: `<!-- SCOUTING_SUMMARY -->` — replace it with a unified
scouting summary covering all of the player's relevant dimensions.

Write **4–6 bullets** total, covering whichever of these apply to this player:

**Batting** (include if player has batting data):
- Overall offensive production (wRC+/OPS+ vs benchmarks: 115+ good, 100 avg, <85 poor)
- Contact quality (avg EV vs 88-90, hard hit% vs 39%, barrel% vs 6-7%)
- Plate discipline (K% vs 22% avg, BB% vs 8% avg) and platoon splits (vs LHP vs RHP)

**Pitching** (include if player has pitching data):
- Overall performance (ERA, FIP vs benchmarks: <3.50 good, ~4.00 avg, >4.50 poor)
- K-BB% (18%+ good, ~14% avg, <8% poor), WHIP (<1.15 good, ~1.30 avg, >1.40 poor)
- Contact quality allowed (barrel%, hard hit%, xwOBA against) and platoon splits (vs LHB vs RHB)

**Fielding** (position players only — skip for pitchers):
- Primary position: ZR (>1.0 good, ~0 avg, <-1.0 poor), FPct vs ~.980 MLB avg
- Position-specific: catchers (framing, CS% >32% good), infielders (DP rate, ZR),
  outfielders (arm value, range)

For two-way players, cover both batting and pitching dimensions in the same summary.

Use `<span class="good">` for strengths and `<span class="poor">` for weaknesses.
Wrap in `<div class="summary"><ul>...</ul></div>` (no h2 — the page already has the section title).

CRITICAL: Use ONLY this player's name in summaries. Do not reference any other player.

Read the HTML file, replace `<!-- SCOUTING_SUMMARY -->` with the summary, write it back.
Then open the report — use the exact path that was printed after `GENERATED:` above:

```bash
open reports/players/<filename>.html
```

### Step 3: Print a 2-3 line terminal summary

Print: player name, team, position, age, OA/POT, current-season batting line (wRC+/OPS+) 
and/or pitching line (ERA/FIP), and total WAR.

Then print: `~ Model: claude-sonnet-4-6 | ~8–15K in / ~3–6K out | est. 7–14¢`

### Database conventions
- Use `.venv/bin/python3` with sqlalchemy and heredoc syntax
- MLB league_id = 203, level_id = 1
- The current sim season is 2028
- Database: read active save from saves.json and derive db name (lowercase, hyphens/spaces → underscores)

### Stats reference bands
| Hitting | Good | Average | Poor |
|---------|------|---------|------|
| wRC+ | 115+ | 100 | <85 |
| wOBA | .360+ | .320 | <.300 |
| K% | <18% | ~22% | >28% |
| BB% | 10%+ | ~8% | <6% |
| ISO | .200+ | .170 | <.120 |
| Avg EV | 92+ | 88-90 | <86 |
| Hard Hit% | 45%+ | ~39% | <32% |
| Barrel% | 10%+ | ~6-7% | <4% |

| Fielding | Good | Average | Poor |
|----------|------|---------|------|
| FPct | ≥.985 | ~.978 | ≤.960 |
| ZR | >1.0 | ~0 | <-1.0 |
| CS% (catchers) | >32% | ~28% | <22% |

| Pitching | Good | Average | Poor |
|----------|------|---------|------|
| FIP | <3.50 | ~4.00 | >4.50 |
| xFIP | <3.60 | ~4.00 | >4.50 |
| K-BB% | 18%+ | ~14% | <8% |
| K% | 27%+ | ~22% | <18% |
| BB% | <6% | ~8% | >10% |
| WHIP | <1.15 | ~1.30 | >1.40 |
| HR/9 | <0.9 | ~1.1 | >1.4 |
| GB% | 47%+ | ~43% | <38% |
| Barrel% allowed | <6% | ~7-8% | >10% |
| Hard Hit% allowed | <34% | ~39% | >42% |
| xwOBA allowed | <.290 | ~.320 | >.340 |

---
