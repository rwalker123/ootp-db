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
- `/player-rating Colt Keith` — default weights
- `/player-rating Colt Keith defense` — boost defense weight
- `/player-rating Colt Keith power, discipline` — boost multiple areas

## Agent prompt template

Use this as the agent prompt, substituting from $ARGUMENTS:

---

Generate an OOTP player rating report for **$ARGUMENTS** in `/Users/raywalker/source/ootp-db`.

### Step 1: Generate (or retrieve cached) the rating report

Parse the arguments: first two words are the player name, any remaining words are focus
modifiers (e.g., "defense", "power, discipline").

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from ratings import generate_rating_report
args = "<FIRST> <LAST>".split()  # substituted from $ARGUMENTS
first, last = args[0], args[1]
focus = args[2:] if len(args) > 2 else None
path, data = generate_rating_report("Tigers-2026-CBL", first, last, focus)
if data is None:
    print(f"CACHED:{path}")
else:
    print(f"GENERATED:{path}")
    for k, v in data.items():
        print(f"{k}={v}")
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

If the output starts with `GENERATED:` — continue to Step 1.5.

### Step 1.5: Fetch career trend stats (last 4 MLB seasons)

Using the first/last name and `player_type` from the data dict, run this supplemental
query to get year-by-year rate stats. Use `dict()` not `{}` for params:

```bash
cd /Users/raywalker/source/ootp-db && .venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os
load_dotenv(".env")
engine = create_engine(os.getenv("POSTGRES_URL").rstrip("/") + "/tigers_2026_cbl")

def safe_div(n, d):
    return n / d if d and d > 0 else None

with engine.connect() as conn:
    pid_row = conn.execute(text(
        "SELECT player_id FROM players WHERE first_name=:f AND last_name=:l"
    ), dict(f="<FIRST>", l="<LAST>")).fetchone()
    if not pid_row:
        print("PLAYER_NOT_FOUND")
    else:
        pid = pid_row[0]

        # Try batting first
        rows = conn.execute(text(
            "SELECT year, g, pa, ab, h, d, t, hr, bb, k, hp, sf, war "
            "FROM players_career_batting_stats "
            "WHERE player_id=:pid AND split_id=1 AND league_id=203 AND level_id=1 "
            "ORDER BY year DESC LIMIT 4"
        ), dict(pid=pid)).fetchall()

        if rows:
            print("TYPE:batter")
            for r in rows:
                yr, g, pa, ab, h, d, t, hr, bb, k, hp, sf, war = r
                singles = h - (d or 0) - (t or 0) - (hr or 0)
                avg  = safe_div(h, ab)
                obp  = safe_div((h or 0) + (bb or 0) + (hp or 0),
                                (ab or 0) + (bb or 0) + (hp or 0) + (sf or 0))
                slg  = safe_div(singles + 2*(d or 0) + 3*(t or 0) + 4*(hr or 0), ab)
                iso  = (slg - avg) if slg and avg else None
                babip = safe_div((h or 0) - (hr or 0),
                                 (ab or 0) - (k or 0) - (hr or 0) + (sf or 0))
                k_pct  = safe_div((k or 0) * 100, pa)
                bb_pct = safe_div((bb or 0) * 100, pa)
                ops = (obp + slg) if obp and slg else None
                def f(v): return f"{v:.3f}" if v is not None else "--"
                def fp(v): return f"{v:.1f}%" if v is not None else "--"
                war_str = f"{float(war):.1f}" if war is not None else "--"
                print(f"YEAR:{yr} G:{g} PA:{pa} HR:{hr} AVG:{f(avg)} OBP:{f(obp)} "
                      f"SLG:{f(slg)} OPS:{f(ops)} ISO:{f(iso)} BABIP:{f(babip)} "
                      f"K%:{fp(k_pct)} BB%:{fp(bb_pct)} WAR:{war_str}")
        else:
            # Try pitching
            rows = conn.execute(text(
                "SELECT year, g, gs, ip, ha, hra, bb, k, er, bf, hp, gb, fb, war "
                "FROM players_career_pitching_stats "
                "WHERE player_id=:pid AND split_id=1 AND league_id=203 AND level_id=1 "
                "ORDER BY year DESC LIMIT 4"
            ), dict(pid=pid)).fetchall()
            if rows:
                print("TYPE:pitcher")
                for r in rows:
                    yr, g, gs, ip, ha, hra, bb, k, er, bf, hp, gb, fb, war = r
                    ip_f = float(ip) if ip else 0
                    era   = safe_div((er or 0) * 9, ip_f)
                    whip  = safe_div((ha or 0) + (bb or 0), ip_f)
                    k_pct = safe_div((k or 0) * 100, bf)
                    bb_pct= safe_div((bb or 0) * 100, bf)
                    kbb   = (k_pct - bb_pct) if k_pct and bb_pct else None
                    hr9   = safe_div((hra or 0) * 9, ip_f)
                    total_bf = (gb or 0) + (fb or 0)
                    gb_pct = safe_div((gb or 0) * 100, total_bf)
                    def f(v, d=2): return f"{v:.{d}f}" if v is not None else "--"
                    def fp(v): return f"{v:.1f}%" if v is not None else "--"
                    war_str = f"{float(war):.1f}" if war is not None else "--"
                    print(f"YEAR:{yr} G:{g} GS:{gs} IP:{f(ip_f,1)} ERA:{f(era)} "
                          f"WHIP:{f(whip)} K%:{fp(k_pct)} BB%:{fp(bb_pct)} "
                          f"K-BB%:{fp(kbb)} HR/9:{f(hr9)} GB%:{fp(gb_pct)} WAR:{war_str}")
            else:
                print("NO_CAREER_DATA")
PYEOF
```

Record all printed stats by year. You now have everything needed for Step 2.

### Step 2: Write the rating summary

The HTML file has a `<!-- RATING_SUMMARY -->` placeholder. Replace it with a **5-bullet**
analysis using the data dict from Step 1 and the WAR trend from Step 1.5.

**Required bullets — write all 5:**

1. **Overall** — rating grade in league context, position rank (e.g. "3rd among all SS"), key stat (wRC+ or FIP)
2. **Strengths / Weaknesses** — 2-3 top sub-scores vs bottom sub-scores; reference bands. For the Defense sub-score, note the position-specific factors that drove it: for catchers highlight framing and CS%; for middle infielders (2B/SS) note DP rate and ZR; for CF note range (ZR) and putout rate; for corner OF note arm and ZR
3. **Durability & Personality** — injury risk flag, proneness profile, work ethic, leadership if flagged
4. **Focus modifier impact** — if focus modifiers were passed, explain how re-weighting changes the picture; skip this bullet if no modifiers
5. **Future Outlook** — synthesize the year-by-year trend data from Step 1.5 with the rating factors:
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
open /Users/raywalker/source/ootp-db/reports/ratings/<filename>.html
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
