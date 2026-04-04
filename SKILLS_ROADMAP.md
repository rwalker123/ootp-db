# Skills Roadmap

Planned Claude skills that build on the `player_ratings`, `batter_advanced_stats`, and `pitcher_advanced_stats` tables.

---

## Status Key
- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete

---

## Completed Skills

- `[x]` **`/player-stats`** — Full stat report for any player (HTML, scouting summary)
- `[x]` **`/player-rating`** — Composite 0-100 rating with sub-score breakdown, 9 components, personality/durability section

---

## Planned Skills

### [x] 1. Free Agent Finder (`/free-agents`)

Identify free agents matching a natural-language criteria set.

**Inputs:** Natural language query (e.g. "lefty SP under 28 with FIP under 3.5 and low injury risk", "contact SS who won't cost more than $8M")

**Data sources:**
- `player_ratings` — composite score, sub-scores, flags
- `batter_advanced_stats` / `pitcher_advanced_stats` — stat filters
- `players_roster_status` — identify free agents (no team, or DFA/waivers)
- `players_contract` — salary expectations, years of control
- `players` — age, handedness, position

**Output:**
- Ranked list of matching free agents with key stats, rating, contract situation
- HTML report or terminal table

**Considerations:**
- Greed rating affects asking price (high greed = demanding contract)
- Loyalty affects likelihood of signing with current team
- Play for Winner affects willingness to sign with non-contenders
- Should show estimated salary range based on `players_contract`

---

### [x] 2. Draft Target Finder (`/draft-targets`)

Identify top prospects in the draft pool matching given criteria.

**Inputs:** Natural language (e.g. "best hitting prospects", "high-ceiling SS or 2B", "safe college bats")

**Data sources:**
- `players` — draft-eligible players (no team, or pre-draft pool)
- `players_value` — OA/POT ratings
- `players_batting` / `players_pitching` — talent ratings (these are populated for draft prospects)
- `players_fielding` — fielding ratings

**Output:** Ranked prospect list with OA/POT, position, handedness, key ratings, development traits (work ethic, IQ)

**Considerations:**
- Batting overall/vsR/vsL ratings are zeroed in CSV export; use `batting_ratings_talent_*` (potential) columns
- Work Ethic and Intelligence are especially important for young prospects (development floor)
- Need to identify the correct `league_id` for the draft pool (likely differs from MLB_LEAGUE_ID=203)

---

### [ ] 3. Waiver Wire Evaluator (`/waiver-claim`)

Given a player on waivers, evaluate whether to claim them and who on the current roster they would replace.

**Inputs:** Player name (waiver candidate)

**Data sources:**
- `player_ratings` — rating for waiver candidate and incumbent(s)
- `players_roster_status` — identify claimed/waiver status
- `team_roster` — Tigers current roster (team_id for Tigers needed)
- `players_contract` — cost of claiming vs incumbent salary
- `players` — age, position, service time

**Output:**
- Side-by-side comparison: waiver candidate vs best/worst incumbent at that position
- Rating delta, stat delta, salary delta
- Recommendation with rationale

**Considerations:**
- Must account for 40-man roster limits and DFA implications
- Contract obligation of claimed player vs current player
- Injury risk flags — don't claim if replacing a healthy starter with injury risk
- Positional flexibility (can they play multiple spots?)

---

### [x] 4. Trade Evaluator (`/trade-targets`)

Given players available on the Tigers, find realistic trade partners and return packages.

**Inputs:** One or more Tigers players being offered (e.g. "Hank Greenberg", or "we have a surplus of outfielders")

**Data sources:**
- `player_ratings` — value of players on both sides
- `batter_advanced_stats` / `pitcher_advanced_stats` — stats for context
- `players_contract` — salary/years, affects trade value
- `trade_history` — recent trade precedents in this save
- `team_roster` — identify roster needs by team (thin positions)
- `players_roster_status` — service time, arbitration/free agent timeline

**Output:**
- List of realistic return targets by position need
- Value comparison (composite rating + contract)
- Teams most likely to be interested (based on their roster gaps)
- Flag if asking price seems too high/low given ratings

**Considerations:**
- Players on the trading block (`list_id` in `team_roster`) are explicitly available
- High greed = high contract cost = depressed trade value
- Years of control matter: pre-arb > arb > FA-year players
- Should identify what Tigers need in return (positional gaps, rotation depth, etc.)

### [x] 5. Contract Extension Advisor (`/contract-extension`)

Recommend years and AAV for a player extension based on projected future performance. 
Follow the skill architecture in CLAUDE.md exactly and create the web page support just like all the other skills.

**Inputs:** Player name (e.g. "Hank Aaron")

**Data sources:**
- `player_ratings` — current composite rating, sub-scores, development/potential scores
- `players_value` — OA, POT, trajectory
- `players_career_batting_stats` / `players_career_pitching_stats` — WAR trend year-over-year
- `players_contract` / `players_contract_extension` — current deal, years remaining, extension offer window
- `players_roster_status` — service time (pre-arb / arb / FA eligibility)
- `players` — age, personality (greed, loyalty, play_for_winner)
- `players_salary_history` — historical salary for comparable players

**Output:**
- Recommended contract: years + AAV + total value
- Performance projection: expected WAR/year over the contract term, based on age curve + ratings trajectory
- Risk assessment: injury proneness, age decline risk, upside/downside range
- Leverage analysis: years until FA, how much urgency is there to extend now vs wait?
- Personality flags: high greed (will demand more), high loyalty (may take a discount), play-for-winner (may leave for contender)

**Core logic:**
- **Performance projection:** blend current WAR with OA/POT gap and development score. Young players (age < 27) with high development scores project upward; veterans (age > 30) project WAR decline using standard aging curve (~0.5 WAR/year decline after peak).
- **Value per WAR:** use market rate (OOTP internal economy — derive from `players_salary_history` vs WAR data across the league to estimate $/WAR). Apply discount for locked-in years (team controls risk).
- **Years recommendation:** cover peak years for young players; avoid paying for age-decline years for veterans. Flag if contract would extend into likely decline phase (age 33+).
- **Greed adjustment:** high greed (>150) → add 10-20% premium to asking price; low greed (<80) → may accept below-market. Loyalty (>150) → may accept hometown discount of ~10%.
- **Comparison:** show what similar-rated players at the same position are currently earning (`players_salary_history`)

**Considerations:**
- Players with high POT vs OA gap are risky to extend long-term (upside not yet realized — could be great or could plateau)
- Injury-prone players (prone >= 150) should get shorter deals with lower AAV
- Pre-arb players: extension usually covers arb years + some FA years; model accordingly
- The skill should output a negotiation range (floor/target/ceiling) not just a single number

---

## Future Ideas (not yet scoped)

- **`/lineup-optimizer`** — suggest optimal lineup order given platoon splits and current roster
- **`/rotation-analysis`** — evaluate rotation depth, innings projection, vulnerability
- **`/prospect-tracker`** — monitor minor league prospects, flag rapid development or decline
- **`/trade-deadline`** — identify buy vs sell decision based on standings and roster age/cost
