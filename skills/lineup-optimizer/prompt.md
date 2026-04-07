# Lineup Optimizer

Generates an optimal batting order for the active team (or a named team) using a named lineup
philosophy. Accounts for career platoon splits, 30-day rolling performance trends, and star
player protection rules grounded in sabermetric research.

## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the arguments to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.

**Never use `open` to launch the report.** Print the `file://` path instead and stop.

## Argument substitution

`$ARGUMENTS` is the full text of the user's invocation message (e.g. "modern vs LHP" or "traditional without Greene").
Before running any code block, replace `$ARGUMENTS` inside string literals (e.g. `raw_args="$ARGUMENTS"`) with the user's full input verbatim.

## Usage

```
/lineup-optimizer
/lineup-optimizer traditional
/lineup-optimizer vs lefty
/lineup-optimizer platoon vs RHP
/lineup-optimizer platoon vs LHP
/lineup-optimizer favor-offense
/lineup-optimizer platoon vs LHP favor-offense
/lineup-optimizer hot-hand
/lineup-optimizer Cleveland modern vs LHP
/lineup-optimizer without Jordan Montgomery
/lineup-optimizer traditional vs RHP without Colt Keith
/lineup-optimizer primary
/lineup-optimizer modern primary vs RHP
/lineup-optimizer Torkelson starts at 1B, Montilla bench
/lineup-optimizer traditional vs RHP Dingler starts, Anderson bench, fatigue 70
/lineup-optimizer modern Lux at 2B starts, fatigue 65
```

## Philosophy Quick Reference

| Philosophy | Best Hitter Slot | Sort Metric | Hot/Cold Weight |
|-----------|-----------------|-------------|-----------------|
| `modern` | #2 (Tango-optimal: most PA + best base-out states) | Season wOBA | Low |
| `traditional` | #3 (conventional role) | Season wOBA | High |
| `platoon` | #2 | Confidence-weighted split wOBA (sqrt curve, 300 PA = full confidence) | Moderate |
| `hot-hand` | #2 | Season wOBA ± 30-day modifier | High |

Generate a batting order lineup for: **$ARGUMENTS**

### Step 1: Parse arguments

From $ARGUMENTS, identify:

- **Team name** (optional): a city name or nickname not matching a philosophy keyword or "vs"
  (e.g. "Cleveland", "Cubs", "New York"). Set TEAM to empty string if absent.
- **Philosophy** (optional): one of `modern`, `traditional`, `platoon`, `hot-hand`.
  Accept "sabermetric" → `modern`; "hot hand" → `hot-hand`.
  **Default**: `platoon` if opponent handedness is specified; otherwise `modern`.
  Rationale: specifying `vs LHP` or `vs RHP` implies the user wants platoon-aware ordering.
- **Favor offense** (optional, default false): keyword `favor-offense` or `favor offense` →
  `FAVOR_OFFENSE=true`. Reduces defense weight at premium positions (C/2B/SS/CF), giving
  batting quality more influence over who fills those spots. Default is defense-favored.
- **Opponent handedness** (optional): `vs LHP` / `vs lefty` / `vs left` → `L`;
  `vs RHP` / `vs righty` / `vs right` → `R`. Empty string if not specified.
- **Excluded players** (optional): `without <name>` or `excluding <name>` → list of strings.
- **Primary only** (optional, default false): keyword `primary` or `primary-only` → `PRIMARY_ONLY=true`.
- **Forced starts** (optional): `<name> starts [at <pos>]` or `<name> at <pos> starts` →
  list of `{"name": "<name>", "pos": <pos_code_or_None>}`. Position codes: C=2, 1B=3, 2B=4,
  3B=5, SS=6, LF=7, CF=8, RF=9, DH=0. Set pos to null if no position specified.
  Examples: `Torkelson starts at 1B` → `{"name": "Torkelson", "pos": 3}`;
  `Dingler starts` → `{"name": "Dingler", "pos": null}`.
- **Forced bench** (optional): `<name> bench` → list of name strings.
  Example: `Montilla bench, Anderson bench` → `["Montilla", "Anderson"]`.
- **Fatigue threshold** (optional): `fatigue <N>` where N is 0–100 → integer.
  Any player with fatigue_points >= N is automatically benched. Example: `fatigue 70`.

### Step 2: Generate (or retrieve cached) the report

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from lineup_optimizer import generate_lineup_report
from shared_css import load_saves_registry
save_name = load_saves_registry()["active"]
path, data = generate_lineup_report(
    save_name,
    team_query=None,          # replace None with "<TEAM>" if team was specified
    philosophy="modern",      # replace with parsed philosophy; use "platoon" if handedness specified and no explicit philosophy given
    opponent_hand=None,       # replace None with "L" or "R" if handedness was specified
    excluded_names=[],        # replace with list of excluded name strings
    primary_only=False,       # replace with True if "primary" keyword present
    forced_starts=[],         # replace with list of dicts: [dict(name="Torkelson", pos=3)]
                              # pos: C=2,1B=3,2B=4,3B=5,SS=6,LF=7,CF=8,RF=9,DH=0; None if unspecified
    forced_bench=[],          # replace with list of name strings to sit
    fatigue_threshold=None,   # replace with int (0-100) to auto-bench fatigued players
    raw_args="$ARGUMENTS",    # pass the original argument string verbatim for cache keying
)
if path is None:
    print("NOT_FOUND")
elif data is None:
    print(f"CACHED:{path}")
else:
    print(f"GENERATED:{path}")
    for k, v in data.items():
        print(f"{k}={v}")
PYEOF
```

If `NOT_FOUND` — team not found or no batters in database. Try to find the team:

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from sqlalchemy import text
from dotenv import load_dotenv
from shared_css import load_saves_registry, get_engine
load_dotenv(".env")
save_name = load_saves_registry()["active"]
engine = get_engine(save_name)
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT team_id, name, nickname, abbr FROM teams "
        "WHERE league_id = 203 ORDER BY name LIMIT 30"
    )).fetchall()
    for r in rows:
        print(r)
PYEOF
```

Retry with the correct team name or nickname from the list.

If `CACHED:` — extract the path (everything after `CACHED:`), run:

```bash
echo "file://<extracted_path>"
```

Print: `[team_name] lineup — [phil_label] | [hand_label] — cached (current). See browser.`
Print: `~ Cache hit — report already current`
Then STOP.

If `GENERATED:` — continue to Step 3.

### Step 3: Write the lineup analysis

The HTML file contains a `<!-- LINEUP_ANALYSIS -->` placeholder. Replace it with a
`<div class="callout">` containing a **4-bullet** analysis using the data printed in Step 2.

Use `team_name` from Step 2 output whenever referring to the team by name. Never hardcode
a team name.

**Required bullets — write all 4:**

**1. Philosophy Rationale** — explain what this philosophy optimizes for:

- **modern**: "Best hitter bats #2 — Tango's research (*The Book*, 2007) shows the #2 slot
  gets ~70 more PA than cleanup per season AND sees more runners on base than leadoff. wOBA
  is the primary sort metric. Lineup protection is treated as a myth — no weak bats inserted
  behind stars."
- **traditional**: "Conventional construction — leadoff sets the table, best hitter anchors
  #3, cleanup drives in runs at #4. Sort metric is wOBA but slot mapping follows the historic
  archetype. Hot/cold trends have higher weight."
- **platoon**: "Lineup restructured to exploit today's opponent handedness ({hand_label}).
  Sort metric = confidence-weighted split wOBA using a sqrt curve: a player with 300+ career
  PA vs this handedness gets full weight on their split wOBA; fewer PA = proportionally less
  weight, blending toward season wOBA. Grounded in Tango's finding that < 300 PA vs a
  handedness is mostly noise."
- **hot-hand**: "Modern base order with 30-day rolling wOBA modifier applied as rank shifts.
  Hot players (30-day wOBA exceeds season by ≥.030) boosted one rank; cold players penalized.
  Stars (wOBA ≥.370 or rating ≥70) receive half the cold penalty to protect against small-
  sample noise — 30-day slumps are ~70-80% noise at this sample size."

**2. Key Lineup Decisions** — call out 2–3 specific slot assignments:

- Who bats leadoff and why (OBP? Speed rating? Matchup advantage?)
- Who bats #2 and why (best wOBA? Switch hitter neutralizing platoon concern?)
- Any notable placement: big platoon split exploited, a switch hitter at #2 neutralizing
  a handedness disadvantage, a high-OBP bat at leadoff.
- For platoon: name the biggest matchup exploit (e.g. "LHB [name] vs RHP gets .XXX vs .XXX
  matchup-weighted wOBA vs his season .XXX").
- For hot-hand ONLY: name which player's temperature flag drove the most significant rank
  shift. Do NOT mention hot/cold as a cause of placement for any other philosophy.

CRITICAL: For modern, traditional, and platoon, slot assignments are determined purely by
wOBA (or split wOBA). A hot player in a high slot is there because of their wOBA, not
their streak. Never attribute a slot assignment to hot/cold status unless philosophy is
hot-hand.

Quote actual wOBA, wRC+, OBP numbers from the lineup card. Never invent stats.

**3. Hot/Cold Report** — summarize temperature flags from `hot_players` and `cold_stars`:

- For hot-hand: hot/cold directly influenced slot assignments — explain the rank shifts.
- For modern, traditional, and platoon: hot/cold data was NOT used in construction —
  slots reflect wOBA only. Frame temperature flags as context only, not as causes.
  Wording to use: "Note: [name] is running hot but their slot reflects their season wOBA,
  not their streak — this philosophy doesn't adjust for temperature."
- If `hot_players` is not "None": name each and note their 30-day trend, but only credit
  hot-hand with acting on it. For other philosophies, add: "Research supports ~15–20%
  real signal in a 30-day streak, but this lineup ignores it by design."
- If `cold_stars` is not "None": "Cold streak noted for [name]. At [N] PA in the window,
  this is likely mostly noise — their career wOBA remains the primary signal. Star
  protection rule holds: they stay in a premium slot."
- If both are "None": "All regulars tracking near season-average pace. Lineup reflects
  true-talent order with minimal temperature noise."

**4. Alternation & Balance** — summarize from `alternation_score`, `lhb_count`, `rhb_count`:

- Quote the score (out of 10) and the L/R pattern string from the report header.
- If score ≥ 8: "Strong alternation — opposing managers can't easily exploit consecutive
  same-hand bats with specialist relievers."
- If score 6–7: "Acceptable alternation — minor clustering but within normal range."
- If score < 6: "Poor alternation — [note where consecutive same-hand run occurs].
  Consider inserting a switch hitter or opposite-hand bat at slot [N] to break up the
  [L/R] run and reduce bullpen exploitation risk."
- If `lhb_count` < 3: "⚠ Lineup has only [N] left-handed bats — vulnerable to a lefty
  specialist in late innings."
- If `rhb_count` < 3: "⚠ Only [N] right-handed bats — a right-handed specialist could
  neutralize much of this lineup."

Format as:
```html
<div class="callout">
  <ul>
    <li><b>Philosophy:</b> ...</li>
    <li><b>Key Decisions:</b> ...</li>
    <li><b>Hot/Cold:</b> ...</li>
    <li><b>Balance:</b> ...</li>
  </ul>
</div>
```

Read the HTML file, replace `<!-- LINEUP_ANALYSIS -->` with the callout div, write it back.
Then print the report path:

```bash
echo "file://<path_from_GENERATED>"
```

### Step 4: Print terminal summary

```
Lineup: <team_name> | <phil_label> | <hand_label>

  #1  <name> (<pos>, bats <bats>)   wRC+:<N>  wOBA:.<NNN>
  #2  <name> (<pos>, bats <bats>)   wRC+:<N>  wOBA:.<NNN>  [★ if star]
  #3  <name> (<pos>, bats <bats>)   wRC+:<N>  wOBA:.<NNN>
  #4  <name> (<pos>, bats <bats>)   wRC+:<N>  wOBA:.<NNN>
  #5–9  (one line per slot, abbreviated)

Avg wRC+: <N>  |  L/R Pattern: <pattern>  |  Alternation: <N>/10
Hot: <hot_players or None>  |  Cold Stars: <cold_stars or None>
```

CRITICAL: Only reference real data from the Step 2 output and the HTML report. Do not
invent ratings, wOBA values, or stats not present in the data.

---

## Decision reference bands

| wOBA | Tier |
|------|------|
| .370+ | Elite |
| .340–.369 | Above Average |
| .310–.339 | Average |
| .290–.309 | Below Average |
| <.290 | Poor |

| wRC+ | Tier |
|------|------|
| 130+ | Elite |
| 115–129 | Above Average |
| 85–114 | Average |
| 70–84 | Below Average |
| <70 | Poor |

| Alternation Score | Interpretation |
|------------------|----------------|
| 9–10 | Excellent — strong L/R variety |
| 7–8 | Good — minor clustering |
| 5–6 | Mediocre — noticeable imbalance |
| <5 | Poor — bullpen matchup vulnerability |

## Philosophy slot mappings

| Philosophy | Sort metric | #1 | #2 | #3 | #4 | #5–9 |
|-----------|------------|----|----|----|----|------|
| `modern` | season wOBA | rank 2 | rank 1 (best) | rank 4 | rank 3 | ranks 5–9 |
| `traditional` | season wOBA | rank 3 | rank 4 | rank 1 (best) | rank 2 | ranks 5–9 |
| `platoon` | confidence-weighted split wOBA | rank 2 | rank 1 | rank 4 | rank 3 | ranks 5–9 |
| `hot-hand` | season wOBA ± temp modifier | rank 2 | rank 1 | rank 4 | rank 3 | ranks 5–9 |

## Star player protection rule

A star (career wOBA ≥ .370 OR rating_overall ≥ 70) receives half the cold-streak rank
penalty of a non-star. Under hot-hand, a cold-extreme star loses at most 1 rank position;
a cold (non-extreme) star loses 0 positions. Stars are marked ★ in the lineup card.

## Platoon scoring formula

**Veteran** (502+ total PA in 3-year window):
```
confidence   = sqrt(min(split_pa / 300, 1.0))
platoon_score = split_woba × confidence
```

**Rookie** (10–501 total PA):
```
split_conf    = sqrt(min(split_pa / 300, 1.0))
new_formula   = split_woba × split_conf
pa_weight     = sqrt(min(total_pa / 502, 1.0))
platoon_score = new_formula × pa_weight + blended_woba × (1 − pa_weight)
```

Below 10 total PA: use blended_woba only.

Switch hitters (bats = S) → treated as neutral unless documented large split.

## Position code reference

1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF | Bats: 1=R, 2=L, 3=S
