# Waiver Wire Claim Evaluator

Evaluate any player on waivers or DFA against your team's current roster at the same position,
then recommend whether to claim, pass, or monitor.

## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the arguments to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.

**Never use `open` to launch the report.** Print the `file://` path instead and stop.

## Argument substitution

`$ARGUMENTS` is the full text of the user's invocation message (e.g. "Jackson Jobe").
Before running any code block, replace all placeholders with the parsed values:
- `<FIRST>` → player's first name (first word)
- `<LAST>` → player's last name (all remaining words, e.g. "De La Cruz")
- `$ARGUMENTS` inside string literals (e.g. `raw_args="$ARGUMENTS"`) → the user's full input verbatim

## Usage

```
/waiver-claim Jordan Montgomery
/waiver-claim Mickey Moniak
/waiver-claim George Valera
```

Evaluate a waiver wire claim for **$ARGUMENTS**.

### Before Step 1: Validate input

Check whether `$ARGUMENTS` looks like a player name (at least two words, both looking like proper names).
Position groups — "infielders", "outfielders", "pitchers", "catchers", "relievers", "starters",
"closers", "shortstops", "second basemen", etc. — are **not** player names.

If $ARGUMENTS is not a player name:
1. Print exactly as a plain line (no backticks, no code block): `NEEDS_INPUT: "$ARGUMENTS" is not a player name — the skill expects a specific player (e.g. /waiver-claim Jordan Montgomery).`
2. Then look up available players at that position group and list them (use the DB query pattern from AGENTS.md)
3. **STOP** — do not proceed to Step 1

### Step 1: Generate (or retrieve cached) the report

Parse $ARGUMENTS: the first word is the first name, all remaining words form the last name (e.g., "Jackson Jobe" → first=Jackson last=Jobe; "Ronald De La Cruz" → first=Ronald last=De La Cruz).

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from waiver_wire import generate_waiver_claim_report
from shared_css import load_saves_registry
save_name = load_saves_registry()["active"]
path, data = generate_waiver_claim_report(save_name, "<FIRST>", "<LAST>", raw_args="$ARGUMENTS")
if path is None:
    print("PLAYER_NOT_FOUND")
elif data is None:
    print("CACHED:" + str(path))
else:
    print("GENERATED:" + str(path))
    for k, v in data.items():
        print(str(k) + "=" + str(v))
PYEOF
```

If the output is `PLAYER_NOT_FOUND` — the player wasn't found in the active save's roster.
Check spelling, then try a partial last name match:

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from sqlalchemy import text
from shared_css import get_engine, load_saves_registry
save = load_saves_registry()["active"]
engine = get_engine(save)
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT first_name, last_name, team_id, position, age FROM players "
        "WHERE LOWER(last_name) LIKE LOWER(:n) AND retired=0 LIMIT 10"
    ), dict(n="%<LAST>%")).fetchall()
    for r in rows:
        print(r)
PYEOF
```

Retry with the corrected name.

If the output starts with `CACHED:` — extract the path (everything after `CACHED:`), then run:

```bash
echo "file://<extracted_path>"
```

Print: `[Player name] — waiver claim report is current (cached since last import). See browser.`
Print: `~ Cache hit — report already current`
Then STOP.

If the output starts with `GENERATED:` — continue to Step 2.

### Step 2: Write the claim recommendation

The HTML file has a `<!-- WAIVER_RECOMMENDATION -->` placeholder. Replace it with a
`<div class="callout">` containing a **4-bullet** recommendation using the data printed
in Step 1. Use `<span class="good">` for positives and `<span class="poor">` for concerns.

Use `my_team_name` (from Step 1 output) whenever referring to the user's team by name in prose.
`my_team_abbr` is only for table cells or short labels where a 3-letter code is appropriate.
Never hardcode a team name — always use values from the data.

**Required bullets — write all 4:**

**1. Verdict** — Lead with a clear recommendation: **CLAIM**, **PASS**, or **MONITOR**.

Use this decision logic:

- **CLAIM** if: candidate `rating_overall` is higher than the worst incumbent by ≥5 points,
  and contract cost is manageable (salary ≤ incumbent salary or fills a genuine gap)
- **PASS** if: candidate is worse than best incumbent, has a concerning contract (high salary +
  multiple years remaining for a backup-level player), or has `flag_injury_risk` + `prone_label`
  of Fragile/Wrecked with your team already carrying injury-prone players at the position
- **MONITOR** if: candidate is comparable to incumbents but the timing isn't urgent (no open
  40-man spot, or `days_waivers_left` = 3 — can wait to see if they clear), or if the player
  could be claimed for depth but isn't an upgrade

State the verdict clearly and give the one-sentence primary reason:
> **CLAIM** — Candidate is a significant upgrade over [worst_incumbent_name] at [position]
> with manageable contract obligation.

**2. Value Comparison** — Side-by-side analysis of candidate vs incumbents:
- Compare `rating_overall` to `best_incumbent_rating` and `worst_incumbent_rating`
- `rating_vs_best`: if negative, candidate is WORSE than the best — note the gap
- `rating_vs_worst`: if positive, candidate is BETTER than worst — note upgrade opportunity
- **Batters** — cite `adv_avg_ev`, `adv_hard_hit_pct`, `adv_barrel_pct`, `adv_xwoba` to
  assess whether the WAR/wRC+ reflects real contact quality:
  - `adv_hard_hit_pct` ≥ 45% + `adv_xwoba` ≥ .360 → "Elite contact quality backs up the production"
  - `adv_hard_hit_pct` < 32% or `adv_xwoba` < .300 → "Soft contact — production may be unsustainable"
  - Platoon flag: if `adv_wrc_plus_vs_lhp` and `adv_wrc_plus_vs_rhp` differ by ≥ 30 points
    (and sample is meaningful, `adv_pa_vs_lhp`/`adv_pa_vs_rhp` ≥ 50), call out the platoon split
    and note whether it fits your team's needs (e.g. lineup has LHP or RHP gaps)
- **Pitchers** — cite `adv_fip`, `adv_xfip`, `adv_k_bb_pct`, `adv_hard_hit_pct_against`,
  `adv_barrel_pct_against`, `adv_xwoba_against`:
  - `adv_hard_hit_pct_against` < 34% + `adv_xwoba_against` < .290 → "Contact suppressor — ERA/FIP likely to hold"
  - `adv_hard_hit_pct_against` > 42% or `adv_xwoba_against` > .340 → "Hittable — ERA may regress upward"
  - Platoon flag: if `adv_era_vs_lhb` and `adv_era_vs_rhb` differ by ≥ 1.50 (and
    `adv_bf_vs_lhb`/`adv_bf_vs_rhb` ≥ 30), note the split and how it fits your team's bullpen usage
- Note whether the candidate brings unique positional value: if `positional_flexibility` list
  is non-empty, that flexibility adds roster utility beyond the direct comparison

**3. Contract & Roster Cost** — Evaluate what claiming this player costs:
- Cite `current_salary` and `years_remaining` explicitly
- If `needs_dfa_to_claim` is True: identify who on your team's roster the agent would DFA —
  the weakest incumbent at the position with options remaining or FA-eligible status
- If `no_trade` is True: flag that the player cannot be traded after claiming — this limits
  future flexibility
- `arb_status` context: Pre-Arb players are cheap but controlled; FA Eligible players must
  be paid their full contract; note if the cost-per-WAR seems reasonable
- Compare candidate salary to incumbent salary — is this an upgrade at a lower or similar cost?

**4. Risk Assessment** — Key concerns:
- Injury: if `flag_injury_risk` or `prone_label` in [Fragile, Wrecked] → flag as primary risk;
  recommend shorter commitment (claim for depth only, not as a starter)
- Performance: if candidate WAR ≤ 0 or rating < 40, flag as replacement-level concern
- **Contact regression (batters):** if `adv_xwoba` < .300 or `adv_barrel_pct` < 4% → "Soft
  contact profile suggests current stats overstate true value; expect regression"
- **Contact suppression (pitchers):** if `adv_xwoba_against` > .340 or
  `adv_hard_hit_pct_against` > 42% → "Allows hard contact consistently; ERA likely to climb"
- **K-BB% (pitchers):** if `adv_k_bb_pct` < 8% → "Poor strikeout-walk profile; limited ceiling
  even with good ERA"
- Age: if age ≥ 33 and years_remaining ≥ 2, flag decline risk
- Greed/Loyalty: `greed_label` of High/Elite means future contract negotiations will be costly;
  note if claiming this player sets up a difficult extension or re-sign situation
- If `is_on_waivers = 1` and `days_waivers_left ≤ 1`: flag urgency — decision must be made today

Format as:
```html
<div class="callout">
  <ul>
    <li><b>Verdict:</b> ...</li>
    <li><b>Value Comparison:</b> ...</li>
    <li><b>Contract &amp; Roster Cost:</b> ...</li>
    <li><b>Risk Assessment:</b> ...</li>
  </ul>
</div>
```

Read the HTML file, replace `<!-- WAIVER_RECOMMENDATION -->` with the recommendation div,
write it back. Then print the report path:

```bash
echo "file://<path-from-GENERATED-output>"
```

### Step 3: Print terminal summary

```
Waiver Claim: <Player Name> | <Pos> | <current_team> | Age <N>

Candidate:   OA:<N>  Rating:<N>  WAR:<N>  Salary:<salary>  <arb_status>
Best Tiger:  <best_incumbent_name>  Rating:<N>  (Δ <rating_vs_best>)
Worst Tiger: <worst_incumbent_name>  Rating:<N>  (Δ <rating_vs_worst>)
Verdict:     <CLAIM / PASS / MONITOR>  |  40-man: <roster_count>/40
```

CRITICAL: Only reference real data from the report. Do not invent ratings, salaries,
or roster details not shown in the output from Step 1.

---

### Decision reference bands

| Rating Delta | Interpretation |
|-------------|----------------|
| Candidate ≥ +10 above worst incumbent | Clear upgrade — strong CLAIM case |
| Candidate +5 to +9 above worst | Modest upgrade — CLAIM if cost is right |
| Candidate within ±4 of worst | Lateral move — MONITOR or PASS |
| Candidate below worst | Downgrade — PASS unless extreme depth need |

| Contract risk | Signal |
|--------------|--------|
| 0 years remaining (Pre-arb) | Low cost, high control — favorable |
| 1–2 years, ≤ $5M/yr | Manageable — claim if player quality warrants |
| 3+ years, > $10M/yr | High obligation — only claim for clear starter-level upgrade |
| No-trade clause | Limits future flexibility — factor into decision |

| Injury proneness | Interpretation |
|-----------------|----------------|
| Iron Man / Durable | Positive — low injury concern |
| Normal | Acceptable |
| Fragile / Wrecked | Significant risk — shorter commitment preferred |

| Personality | Impact on claim decision |
|------------|--------------------------|
| Greed > 150 | Re-sign or extension will be expensive — factor in |
| Loyalty > 150 | May accept a discount if extended later |
| Play for Winner > 150 | May not want to stay if your team are not contending |

### Advanced stats reference bands

| Batter contact quality | Good | Average | Poor |
|----------------------|------|---------|------|
| Avg EV | 92+ | 88–90 | <86 |
| Hard Hit% | 45%+ | ~39% | <32% |
| Barrel% | 10%+ | ~6–7% | <4% |
| xwOBA | .360+ | .320 | <.300 |

| Pitcher contact allowed | Good | Average | Poor |
|------------------------|------|---------|------|
| Hard Hit% Against | <34% | ~39% | >42% |
| Barrel% Against | <6% | ~7–8% | >10% |
| xwOBA Against | <.290 | ~.320 | >.340 |
| K-BB% | 18%+ | ~14% | <8% |

### Position code reference
1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF

### Role code reference
11=SP (Starting Pitcher), 12=RP (Relief Pitcher), 13=CL (Closer)
