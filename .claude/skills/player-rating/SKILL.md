---
name: player-rating
description: Show a player's composite rating breakdown with optional focus weighting.
argument-hint: <first-name> <last-name> [focus-area]
---

# Player Rating Lookup

Show a player's composite rating with sub-score breakdown and analysis.

## IMPORTANT: Always use a fresh agent

To prevent context bleedover between players, you MUST delegate this entire task to a
fresh Agent (subagent_type: "general-purpose", model: "sonnet"). Pass the full player 
name, any focus modifiers, and all instructions below to the agent. Do NOT do the work 
inline.

## Usage
- `/player-rating Roger Clemens` — default weights
- `/player-rating Ozzie Smith defense` — boost defense weight
- `/player-rating Barry Bonds power, discipline` — boost multiple areas

## Agent prompt template

Use this as the agent prompt, substituting from $ARGUMENTS:

---

Generate an OOTP player rating report for **$ARGUMENTS**.

### Step 1: Generate (or retrieve cached) the rating report

Parse the arguments: first two words are the player name, any remaining words are focus
modifiers (e.g., "defense", "power, discipline").

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from ratings import generate_rating_report, fetch_career_trend_stats
from shared_css import load_saves_registry, get_engine
save_name = load_saves_registry()["active"]
args = "<FIRST> <LAST>".split()  # substituted from $ARGUMENTS
first, last = args[0], args[1]
focus = args[2:] if len(args) > 2 else None
path, data = generate_rating_report(save_name, first, last, focus)
if data is None:
    print(f"CACHED:{path}")
else:
    print(f"GENERATED:{path}")
    for k, v in data.items():
        print(f"{k}={v}")
    engine = get_engine(save_name)
    career_lines = fetch_career_trend_stats(engine, first, last)
    for line in career_lines:
        print(line)
PYEOF
```

If the output starts with `CACHED:` — extract the path (everything after `CACHED:`), then run:

```bash
open <extracted_path>
```

Then print:
`[Player name] — report is current (generated since last import). See browser for full ratings.`
`~ Cache hit — skipped regen | est. 1–2¢`
Then STOP — do not regenerate or read the HTML file.

If the output starts with `GENERATED:` — continue to Step 2. The output also contains:
- `key=value` lines from the data dict (player name, team, ratings, flags)
- `TYPE:batter` or `TYPE:pitcher` followed by `YEAR:...` lines (last 4 MLB seasons)

### Step 2: Write the rating summary

The HTML file has a `<!-- RATING_SUMMARY -->` placeholder. Replace it with a **5-bullet**
analysis using the data dict from Step 1 and the WAR trend from Step 1.5.

**Required bullets — write all 5:**

1. **Overall** — rating grade in league context, position rank (e.g. "3rd among all SS"), key stat (wRC+ or FIP)
2. **Strengths / Weaknesses** — 2-3 top sub-scores vs bottom sub-scores; reference bands. For the Defense sub-score, note the position-specific factors that drove it: for catchers highlight framing and CS%; for middle infielders (2B/SS) note DP rate and ZR; for CF note range (ZR) and putout rate; for corner OF note arm and ZR
3. **Durability & Personality** — injury risk flag, proneness profile, work ethic, leadership if flagged
4. **Focus modifier impact** — if focus modifiers were passed, explain how re-weighting changes the picture; skip this bullet if no modifiers
5. **Future Outlook** — synthesize the year-by-year trend data (YEAR: lines from Step 1 output) with the rating factors:
   - **Trend direction**: for batters, look at OPS/ISO/BABIP/WAR direction over the last 3-4 seasons — rising, flat, or declining; for pitchers, use ERA/WHIP/K-BB%/WAR
   - **Consistency**: note if the stats are stable year-to-year or volatile (high variance = projection risk)
   - **OA→POT gap**: gap ≥ 10 = meaningful upside remaining; gap < 5 = near ceiling — combine with age to assess likelihood of realizing it
   - **Age curve**: < 26 = pre-peak; 26–30 = peak years; 31–33 = late peak; > 33 = decline phase — does the trend direction match expectations for this age?
   - **Development score**: high development (work ethic + IQ) amplifies upside for young players; for veterans it suggests slower decline
   - Conclude with a one-sentence projection: e.g. "Trending up heading into his peak years — projects as a frontline [pos] through age 30" or "Declining ERA/WAR at age 33 fits the aging curve — value a 1-2 year commitment max"

If no career data exists (< 2 seasons), note it and base the outlook on OA/POT + age + development score alone.

Use `<span class="good">` for strengths and `<span class="poor">` for weaknesses.
Wrap in `<div class="summary"><ul>...</ul></div>`.

Read the HTML file, replace `<!-- RATING_SUMMARY -->` with the summary, write it back.

Then open the report — use the exact path that was printed after `GENERATED:` above:

```bash
open reports/ratings/<filename>.html
```

### Step 3: Print terminal summary

Print 2-3 lines: player name, team, overall rating + grade, position rank, key stat
(wRC+ or FIP), WAR, and any flags.

Then print: `~ Model: claude-sonnet-4-6 | ~6–12K in / ~2–4K out | est. 5–10¢`

CRITICAL: Use ONLY this player's name. Do not reference any other player.

### Stats reference bands
| Hitting | Good | Average | Poor |
|---------|------|---------|------|
| wRC+ | 115+ | 100 | <85 |
| wOBA | .360+ | .320 | <.300 |
| K% | <18% | ~22% | >28% |
| BB% | 10%+ | ~8% | <6% |
| Barrel% | 10%+ | ~6-7% | <4% |

| Pitching | Good | Average | Poor |
|----------|------|---------|------|
| FIP | <3.50 | ~4.00 | >4.50 |
| K-BB% | 18%+ | ~14% | <8% |
| WHIP | <1.15 | ~1.30 | >1.40 |

| Fielding (Defense sub-score inputs) | Good | Average | Poor |
|--------------------------------------|------|---------|------|
| ZR (zone rating) | >+3 | ~0 | <-3 |
| FPct | ≥.985 | ~.978 | ≤.960 |
| CS% (catchers) | >32% | ~18% | <10% |
| Framing (catchers) | >5 | ~0 | <-5 |
| DP/150G (2B) | >100 | ~82 | <55 |
| DP/150G (SS) | >90 | ~72 | <40 |
| Arm value (OF) | >+2 | ~0 | <-2 |
| PO/G (CF) | >2.7 | ~2.35 | <1.5 |

---
