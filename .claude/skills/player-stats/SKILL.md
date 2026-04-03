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

Generate an OOTP player report for **$ARGUMENTS** using `src/report.py` in `/Users/raywalker/source/ootp-db`.

### Step 1: Generate (or retrieve cached) the report

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from report import generate_player_report
path, data = generate_player_report("Tigers-2026-CBL", "<FIRST>", "<LAST>")

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

### Step 2: Write scouting summaries and insert them

The HTML has placeholder comments where summaries go:
- `<!-- BATTING_SUMMARY -->` — replace with a batting scouting summary (if player has batting data)
- `<!-- PITCHING_SUMMARY -->` — replace with a pitching scouting summary (if player has pitching data)
- `<!-- FIELDING_SUMMARY -->` — replace with a fielding scouting note (position players only, not pitchers)

For two-way players, write BOTH batting and pitching summaries. Each is independent — analyze batting and pitching separately.

**Fielding summary** (2-3 bullets, position players only — skip for pitchers):
- Primary position performance: ZR (positive = above avg, negative = below avg; >1.0 good, <-1.0 poor), FPct vs ~.980 MLB avg
- Position-specific highlights:
  - **Catchers**: framing value, CS% (>32% good, ~28% avg, <22% poor), PB rate
  - **Infielders**: DP rate, ZR range tendency, error frequency
  - **Outfielders**: arm value, ZR range assessment
- Cross-reference fielding ratings vs actual stats — flag if ratings and real-world performance diverge

Wrap in `<h2>Fielding Scouting Summary</h2><div class="summary"><ul>...</ul></div>`

**Batting summary** (3-5 bullets):
- Overall offensive production (wRC+/OPS+ vs benchmarks: 115+ good, 100 avg, <85 poor)
- Platoon splits (vs LHP vs RHP wRC+, xwOBA, K%)
- Contact quality (avg EV vs 88-90, hard hit% vs 39%, barrel% vs 6-7%)
- Plate discipline (K% vs 22% avg, BB% vs 8% avg)
- Defensive value and career trajectory

**Pitching summary** (3-5 bullets):
- Overall pitching performance (ERA, FIP vs benchmarks: <3.50 good, ~4.00 avg, >4.50 poor)
- Pitch arsenal and ratings
- K-BB% (18%+ good, ~14% avg, <8% poor), WHIP (<1.15 good, ~1.30 avg, >1.40 poor)
- Contact quality allowed (barrel%, hard hit%, xwOBA against)
- Platoon splits (vs LHB vs RHB) and career trajectory

Use `<span class="good">` for strengths and `<span class="poor">` for weaknesses.
Wrap each summary in `<h2>Batting Scouting Summary</h2><div class="summary"><ul>...</ul></div>` 
or `<h2>Pitching Scouting Summary</h2>...`.

CRITICAL: Use ONLY this player's name in summaries. Do not reference any other player.

Read the HTML file, replace the placeholder comments with the summaries, write it back.
Then open the report — use the exact path that was printed after `GENERATED:` above:

```bash
open /Users/raywalker/source/ootp-db/reports/players/<filename>.html
```

### Step 3: Print a 2-3 line terminal summary

Print: player name, team, position, age, OA/POT, current-season batting line (wRC+/OPS+) 
and/or pitching line (ERA/FIP), and total WAR.

Then print: `~ Model: claude-sonnet-4-6 | ~8–15K in / ~3–6K out | est. 7–14¢`

### Database conventions
- Use `.venv/bin/python3` with sqlalchemy and heredoc syntax
- MLB league_id = 203, level_id = 1
- The current sim season is 2028
- Database: tigers_2026_cbl

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
