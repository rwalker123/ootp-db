---
name: contract-extension
description: Recommend years and AAV for a player contract extension based on projected performance, market comparables, and personality.
argument-hint: <first-name> <last-name>
---

# Contract Extension Advisor

Generate a contract extension recommendation for any MLB-level player on the active save.

## IMPORTANT: Always use a fresh agent

Delegate this entire task to a fresh Agent (subagent_type: "general-purpose", model: "sonnet").
Do NOT do the work inline in the current conversation.

## Usage

```
/contract-extension Colt Keith
/contract-extension Jackson Jobe
/contract-extension Riley Greene
```

## Agent prompt template

Use this as the agent prompt, substituting from $ARGUMENTS:

---

Generate a contract extension advisor report for **$ARGUMENTS**.

### Step 1: Generate (or retrieve cached) the report

Parse the first two words of $ARGUMENTS as the player's first and last name.

```bash
.venv/bin/python3 << 'PYEOF'
import sys, json
sys.path.insert(0, "src")
from contract_extension import generate_contract_extension_report
from shared_css import load_saves_registry
save_name = load_saves_registry()["active"]
path, data = generate_contract_extension_report(save_name, "<FIRST>", "<LAST>")
if path is None:
    print("PLAYER_NOT_FOUND")
elif data is None:
    print(f"CACHED:{path}")
else:
    print(f"GENERATED:{path}")
    for k, v in data.items():
        print(f"{k}={v}")
PYEOF
```

If the output is `PLAYER_NOT_FOUND` — the player wasn't found in the active save's MLB roster. Check spelling (hyphens, accents), then try with a partial last name match by running a direct lookup:

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
        "SELECT first_name, last_name, team_id, position, age FROM players "
        "WHERE last_name ILIKE :n AND retired=0 AND free_agent=0 LIMIT 10"
    ), dict(n="%<LAST>%")).fetchall()
    for r in rows:
        print(r)
PYEOF
```

Retry with the corrected name.

If the output starts with `CACHED:` — extract the path (everything after `CACHED:`), then run:

```bash
open <extracted_path>
```

Then print:
`[Player name] — extension report is current (generated since last import). See browser.`
`~ Cache hit — skipped regen | est. 1–2¢`

Then STOP — do not regenerate or read the HTML file.

If the output starts with `GENERATED:` — continue to Step 2.

### Step 2: Write the extension recommendation

The HTML file has a `<!-- CONTRACT_EXTENSION_SUMMARY -->` placeholder. Replace it with
a `<div class="summary">` containing a **5-bullet** recommendation using the data printed
in Step 1. Use `<span class="good">` for strengths and `<span class="poor">` for risks.

**Required bullets — write all 5:**

**1. Contract Recommendation** — Lead with the concrete offer: recommended years + AAV + total value.

Derive the base AAV from the median comparable salary (`median_comp_salary`), adjusted:
- OA/POT gap ≥ 15 and age < 27: add 5–10% for upside premium
- Greed > 150: add 10–20% to the asking price (player will demand more)
- Greed < 80: deduct 5–10% (may accept below-market)
- Loyalty > 150: note the ~10% discount opportunity
- Injury risk flag or prone_overall = Fragile/Wrecked: reduce years by 1, reduce AAV by 10–15%
- Present a negotiation range:
  - **Floor** (lowest you might get away with): market rate × 0.82, shorten by 1 year
  - **Target** (fair deal): market rate, length covers peak years
  - **Ceiling** (max you'd offer to lock them up): market rate × 1.12, covers arb + some FA years

Use this format (with actual dollar amounts):
> Recommended: **X years / $YM AAV / $TotalM total** | Range: $FloorM–$CeilingM AAV

**2. Performance Projection** — Expected WAR/year over the contract term, based on:
- `avg_war_last_seasons` as the baseline
- Age curve: < 26 = growing (+0.3–0.5 WAR/year trajectory); 26–30 = stable peak; 31–33 = flat to slight decline (−0.3/year); > 33 = meaningful decline (−0.5/year)
- `rating_development` ≥ 60 and age < 28: amplifies upside (high work ethic + IQ compounds)
- `oa_pot_gap` ≥ 10: note remaining ceiling not yet realized
- **Contact quality (batters):** if `adv_years_available` ≥ 1, reference `adv_avg_ev`, `adv_hard_hit_pct`, `adv_barrel_pct`, `adv_xwoba` to validate or challenge the WAR projection:
  - `adv_hard_hit_pct` ≥ 45% + `adv_xwoba` ≥ .360 → "Contact quality supports the WAR floor — true production is real"
  - `adv_hard_hit_pct` < 32% or `adv_xwoba` < .300 → "Soft contact profile — WAR may not hold; regression risk"
  - If `adv_years_available` ≥ 2: note whether the trend is improving, stable, or declining
  - If `adv_years_available` = 0: omit contact quality from this bullet entirely
- **Contact quality (pitchers):** if `adv_years_available` ≥ 1, use `adv_avg_ev_against`, `adv_hard_hit_pct_against`, `adv_xwoba_against` to assess ERA/FIP sustainability:
  - `adv_hard_hit_pct_against` < 34% + `adv_xwoba_against` < .290 → "Elite contact suppressor — FIP/ERA should hold"
  - `adv_hard_hit_pct_against` > 42% or `adv_xwoba_against` > .340 → "Allows hard contact — ERA may be unsustainable"
  - If `adv_years_available` = 0: omit contact quality from this bullet entirely
- Conclude with a one-sentence projection: e.g. "Projects for 3.2–3.8 WAR/year through the deal" or "Declining trend suggests 1.5–2.0 WAR/year by year 3 of a long-term deal"

**3. Leverage & Urgency** — How much pressure does each side have?
- `years_remaining` ≤ 1: urgent — player is nearly to free agency; any extension must start now
- `years_remaining` 2–3: moderate leverage — team has time but the player is building his market value
- `years_remaining` ≥ 4: low urgency — team holds options, no rush to extend early
- `arb_status = "Pre-Arbitration"`: team has strong leverage, player cheaply controlled; suggest covering arb years + 2–3 FA years
- `arb_status = "Arbitration Yr 1/2/3"`: costs are rising; extending now locks in controlled costs
- `arb_status = "FA Eligible (Under Contract)"`: team paid market price; extension means buying back potential re-signing risk

**4. Risk Assessment** — Key concerns with this specific player:
- Injury: `flag_injury_risk` or `prone_overall` = Fragile/Wrecked → "High injury risk is the primary concern — limit total guarantee years"
- Age decline: `age_phase = "Late Peak"` or `"Decline Phase"` → "Contract would extend into decline phase (age 33+) — front-load salary, avoid buying years past age 34"
- POT/OA gap: `oa_pot_gap` < 5 → "OA and POT are nearly equal — player is near ceiling, little development upside to bet on"
- `oa_pot_gap` ≥ 15 and age ≥ 29 → "Large OA/POT gap at this age likely won't close — upside is a mirage at this stage"
- `rating_durability` < 40 → flag as durability concern

**5. Personality & Negotiation Notes** — How will talks go?
- `greed` > 150: "High Greed — expect above-market demands; budget 15–20% above comparable AAV for the asking price to start"
- `greed` < 80: "Low Greed — player may accept a below-market deal; start negotiations at or below market rate"
- `loyalty` > 150: "Strong Loyalty — likely values staying; use this to press a ~10% hometown discount"
- `loyalty` < 80: "Low Loyalty — won't take a discount; pay full market or he walks at FA"
- `play_for_winner` > 150: "Wants to win — contending teams will have an edge; consider whether `my_team_name` can offer a realistic path to the playoffs"
- `local_pop` ≥ 5: "Fan icon — losing this player would measurably hurt gate receipts; factor an additional ~5–10% premium into the ceiling offer to reflect retention value beyond pure baseball production"
- `local_pop` 3–4: "Established local favorite — moderate attendance/brand impact if traded"
- `national_pop` ≥ 5: "National star — marketing and merchandise value is significant; ownership will value retention beyond the on-field numbers"
- `local_pop` ≤ 1: "Low fan recognition — extension decision is purely performance-based"
- If the player has `flag_leader = True`: note that retaining him has clubhouse value beyond the stats

Format as:
```html
<div class="summary">
  <ul>
    <li><b>Contract Recommendation:</b> ...</li>
    <li><b>Performance Projection:</b> ...</li>
    <li><b>Leverage &amp; Urgency:</b> ...</li>
    <li><b>Risk Assessment:</b> ...</li>
    <li><b>Personality &amp; Negotiation:</b> ...</li>
  </ul>
</div>
```

Read the HTML file, replace `<!-- CONTRACT_EXTENSION_SUMMARY -->` with the summary,
write it back. Then open the report — use the exact path printed after `GENERATED:`:

```bash
open reports/<save_name>/contract_extensions/<slug>.html
```

### Step 3: Print terminal summary

```
Contract Extension: <Player Name> | <Pos> | <Team> | Age <N>

Contract:  Currently: $Xm  |  <N> years remaining  |  <Status>
Value:     OA:<N>  POT:<N>  Rating:<N>  WAR:<N>  <key_stat_label>:<N>
Recommend: <N> years / $Xm AAV / $Xm total  |  Range: $Xm–$Xm AAV
Risk:      <one-sentence risk flag or "No major flags">
```

Then print: `~ Model: claude-sonnet-4-6 | ~10–16K in / ~3–5K out | est. 8–14¢`

CRITICAL: Only reference this player. Do not invent salary numbers beyond what the
comparables support. Use `fmt_salary` style ($X.XM or $XK) for all dollar amounts.

### Stats reference bands for analysis context

| Batting | Good | Average | Poor |
|---------|------|---------|------|
| wRC+ | 115+ | 100 | <85 |
| WAR/yr | 4.0+ | 2.0 | <1.0 |

| Pitching | Good | Average | Poor |
|----------|------|---------|------|
| FIP | <3.50 | ~4.00 | >4.50 |
| WAR/yr | 3.0+ | 1.5 | <0.5 |

| Contact Quality (Batters) | Good | Average | Poor |
|--------------------------|------|---------|------|
| Avg EV | 92+ | 88–90 | <86 |
| Hard Hit% | 45%+ | ~39% | <32% |
| Barrel% | 10%+ | ~6–7% | <4% |
| xwOBA | .360+ | .320 | <.300 |

| Contact Quality (Pitchers Allowed) | Good | Average | Poor |
|------------------------------------|------|---------|------|
| Avg EV Against | <88 | 88–90 | >92 |
| Hard Hit% Against | <34% | ~39% | >42% |
| Barrel% Against | <6% | ~7–8% | >10% |
| xwOBA Against | <.290 | ~.320 | >.340 |

| Personality | High (>150) | Average (75–125) | Low (<75) |
|-------------|-------------|-----------------|-----------|
| Greed | Demanding | Market rate | Below-market |
| Loyalty | Hometown discount | Neutral | No discount |
| Play for Winner | Wants contender | Neutral | Doesn't care |

### Aging curve reference

| Age | Phase | WAR projection |
|-----|-------|---------------|
| < 26 | Pre-Peak | Rising (+0.3–0.5/year) |
| 26–30 | Peak | Stable |
| 31–33 | Late Peak | Slight decline (−0.3/year) |
| > 33 | Decline | Meaningful decline (−0.5/year) |

### Position code reference
1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF

---
