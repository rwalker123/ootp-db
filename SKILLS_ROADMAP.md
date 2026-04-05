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

### [x] 3. Waiver Wire Evaluator (`/waiver-claim`)

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
- Follow the skill architecture in CLAUDE.md exactly.
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

### [x] 6. Lineup Optimizer (`/lineup-optimizer`)

Suggest the optimal batting order using a named lineup philosophy, platoon splits, and recent performance trends. The active team is resolved at runtime from `saves.json` — never hardcoded. User can override the team by name.

**Inputs:** `[team name (optional)] [philosophy] [vs LHP|RHP (optional)] [player exclusions (optional)]`

Examples:
- `/lineup-optimizer` — active team, Modern philosophy, no handedness specified
- `/lineup-optimizer traditional` — active team, Traditional philosophy
- `/lineup-optimizer vs lefty` — active team, Modern philosophy, opponent is LHP
- `/lineup-optimizer hot-hand vs RHP` — active team, Hot Hand philosophy vs RHP starter
- `/lineup-optimizer Cleveland platoon` — named team, Aggressive Platoon philosophy
- `/lineup-optimizer without [player name]` — exclude an injured or rested player

**Philosophy modes** (default: `modern`):
- `traditional` — conventional roles: leadoff = OBP+speed, #3 = best hitter, #4 = cleanup power
- `modern` — sabermetric: best hitter at #2 to maximize PA; wOBA-ranked order per Tango/FanGraphs research
- `platoon` — daily restructuring by opponent handedness; matchup-first, wOBA used as tiebreaker
- `hot-hand` — true-talent base order with 30-day rolling wOBA modifier applied as slot shifts

**Data sources:**
- `saves.json` — resolve active save → DB name; `teams` + `human_managers` → resolve active `team_id`. If user names a team, match via `teams.nickname` or `teams.name`.
- `batter_advanced_stats` — season wRC+, wOBA, OBP, ISO, K%, BB%, `wrc_plus_vs_lhp`, `wrc_plus_vs_rhp`, `obp_vs_lhp`, `obp_vs_rhp`, `woba_vs_lhp`, `woba_vs_rhp`
- `players_career_batting_stats` — split_id=2 (vs LHP) and split_id=3 (vs RHP): career PA, h, bb, hp, ab, sf, hr, k to compute career OBP/SLG/wOBA splits with reliable sample sizes
- `players_game_batting` — current-season game log; compute 30-day rolling wOBA (last ~30 games) for hot/cold trend detection; also compute avg exit velocity trend if available via join to `players_at_bat_batting_stats`
- `players_batting` — `batting_ratings_vsr_*` / `batting_ratings_vsl_*` ratings as fallback when career split PA < 300; also `running_ratings_speed`, `running_ratings_stealing` for baserunning value
- `player_ratings` — `rating_overall`, `rating_offense`, `rating_baserunning`, `rating_discipline`, `flag_injury_risk`; `prone_overall` for injury context
- `team_roster` — active team's roster filtered by resolved `team_id`; `list_id` to distinguish active 25-man vs non-active
- `players` — `position`, `bats` (1=R, 2=L, 3=Switch), `age`
- `players_roster_status` — exclude players on IL or DFA
- `leagues` — `dh_used` column to determine if team plays with DH
- `projected_starting_pitchers` — used to infer opponent handedness if user says "tonight" or asks for a matchup-specific lineup

**Output:**
- HTML report: lineup card (slots 1–9 with position, name, bats, key stats per slot, rationale), plus a full split stats table (season wRC+, 30-day wRC+, wRC+ vs LHP, wRC+ vs RHP, OBP, ISO, speed rating) for all eligible players
- Temperature bar per player: hot (30-day > season by .030+ wOBA), cold (below by .030+), neutral — displayed visually in the lineup card
- Handedness alternation score (0–10) with a L/R pattern diagram
- Comparison panel: show what the lineup looks like under each philosophy side-by-side (compact version)
- Terminal summary: philosophy used, projected lineup wRC+ vs named handedness, top 2 platoon mismatches flagged, any star on a notable cold streak

**Core logic:**

*Team resolution:*
- Read `saves.json` → active save name → derive DB name
- If no team name in arguments: query `human_managers` to get the manager's `team_id`
- If team name provided: match against `teams.nickname` (case-insensitive); error clearly if ambiguous

*Split source hierarchy (most to least reliable):*
1. Career splits from `players_career_batting_stats` — use only if PA vs that handedness ≥ 300
2. If 100–299 career PA: blend career split (40% weight) with season `batter_advanced_stats` split (60%)
3. If < 100 career PA: use `batting_ratings_vsr_*` / `batting_ratings_vsl_*` from `players_batting` as the proxy — do not use the tiny career sample
4. Switch hitters (bats=3): treat as neutral for platoon purposes unless they have a documented strong side (gap ≥ .040 wOBA by side with ≥ 300 PA from each side)

*Hot/cold trend detection (30-day rolling):*
- Join `players_game_batting` to get the last 30 days of game-level stats for each eligible player
- Compute 30-day wOBA from counting stats (h, d, t, hr, bb, hp, ab, sf)
- Compare to season wOBA from `batter_advanced_stats`
- Temperature thresholds:
  - **Hot:** 30-day wOBA exceeds season wOBA by ≥ .030 → flag green
  - **Cold:** 30-day wOBA below season wOBA by ≥ .030 → flag yellow
  - **Extreme cold:** gap ≥ .060 → flag red
  - **Neutral:** within .030 either direction → no flag
- Exit velocity trend (optional enrichment): if `players_at_bat_batting_stats` data is available, compute 30-day avg EV vs season avg EV. EV drop ≥ 3 mph on a cold player may indicate injury — add a flag.

*Star player protection rule (all philosophies):*
- Define "star" as: career wOBA ≥ .370 OR `rating_overall` ≥ 70
- Stars on a cold streak are penalized at most **half** the normal slot shift of a non-star
- Stars cannot drop below slot #4 regardless of cold streak under any philosophy except Traditional
- Rationale: the opportunity cost of benching a star is 4–7× higher per PA than benching a role player — the research strongly argues against knee-jerk slot drops for stars

*Slot assignments by philosophy:*

**TRADITIONAL:**
- #1: highest OBP player with speed rating > 55; K% < 22% preferred; SB threat a plus
- #2: second-best OBP; contact over power; situational hitter archetype
- #3: best hitter by batting average + wOBA combined; the "franchise player" slot
- #4 (Cleanup): highest ISO; HR leader; pure power
- #5: second power bat; "protection" for #4
- #6–#7: sorted by wOBA descending
- #8: weakest bat in the lineup (often C)
- #9 (DH league): weakest remaining; (NL: pitcher slot)
- Hot hand weight: **high** — hot player moves up 1–2 slots, cold player moves down 1–2 slots regardless of star status

**MODERN (default):**
- Based on Tango/FanGraphs wOBA-rank ordering (The Book, 2007)
- Sort all eligible players by season wOBA. Assign slots:
  - #1 → 2nd-best wOBA (high PA count + good base-out distributions)
  - #2 → best wOBA (maximum value in highest-leverage slot)
  - #3 → 4th-best wOBA
  - #4 → 3rd-best wOBA
  - #5 → 5th-best, #6 → 6th-best, etc.
  - #9 (DH league) → worst bat, but if his OBP > .310 treat as second leadoff opportunity
- Adjustments to wOBA rank: GDP-prone (slow C/1B with GDP/PA > 0.04) → move down 1 slot; net-positive SB (SB rate × speed rating bonus) at slots 1–3 → move up 1 slot
- Hot hand weight: **low** — only 30+ day extreme cold/hot (red/green flags) trigger any slot change, and stars are immune
- Note: lineup protection is treated as a myth — do not slot weak hitters behind stars to "protect" them

**PLATOON:**
- Base each player's sort score on matchup-weighted wOBA:
  - vs RHP tonight: `sort_score = wOBA_vs_RHP × 0.70 + wOBA_season × 0.30`
  - vs LHP tonight: `sort_score = wOBA_vs_LHP × 0.70 + wOBA_season × 0.30`
  - No handedness specified: use season wOBA (fall back to Modern ordering)
- Apply split source hierarchy — never use < 100 PA raw split; use ratings proxy instead
- Slots 1–5 sorted by matchup-weighted score, with speed bonus at #1
- Flag players with large platoon gap (wOBA split ≥ .040) who are in a disadvantaged matchup — suggest bench/DH swap if a better-matched alternative is available
- Hot hand weight: **moderate** — 30-day handedness-specific trend (e.g. cold vs LHP specifically) can influence platoon decisions; season-level wOBA still dominant

**HOT HAND:**
- Start from Modern slot assignments (wOBA-ranked base order)
- Apply temperature modifier to slot ranking:
  - Green (hot ≥ .030): move up 1 slot rank
  - Red (extreme cold ≥ .060): move down 2 slot ranks (non-star) or 1 slot rank (star)
  - Yellow (cold ≥ .030): move down 1 slot rank (non-star) or 0 (star)
  - Neutral: no change
- Star protection: career wOBA ≥ .370 or `rating_overall` ≥ 70 → cannot drop below slot #4; cold penalty halved
- Exit velocity enrichment: if EV trend data available, an extreme-cold player with declining EV gets an injury-risk flag in the report (but does not affect slot placement automatically)
- Hot hand weight: **high** — this philosophy explicitly uses the 30-day window as intended by the research (~20–30% real signal)

*Handedness alternation scoring:*
- Score 0–10: start at 10, subtract 1 for each consecutive pair of same-handedness batters beyond 2 in a row
- Subtract 2 for any run of 4+ consecutive same-hand bats
- Display L/R/S pattern string (e.g. `R-L-R-L-S-R-L-R-L`) in the report
- Flag if score < 6

*Positional constraints (all philosophies):*
- Must field all 9 positions; DH eligibility from `leagues.dh_used`
- Only active 25-man (`team_roster` list_id filter) and not on IL/DFA (`players_roster_status`) are eligible
- DH slot: filled by best available bat with no required fielding position, or by moving a starter to DH and filling their position from the bench

**Considerations:**
- Catcher is structurally the weakest bat on most rosters — slot at #8 (not #9) under Modern and Platoon philosophies; #9 is too valuable in DH lineups to waste
- Switch hitters are premium assets at #1 and #2: they neutralize platoon concerns in the two highest-PA slots
- Flag lineups with fewer than 3 RHB or 3 LHB — extreme handedness concentration is a tactical vulnerability vs specialist relievers
- "Protection" as a construction principle is not used by Modern, Platoon, or Hot Hand philosophies — the research does not support it
- If user specifies excluded players by name, resolve via `players` name lookup and remove from eligible pool before slot assignment
- Follow the skill architecture in CLAUDE.md exactly: Python generates the full HTML report, agent writes the analysis text into the placeholder, fresh agent required

---

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

- **`/rotation-analysis`** — evaluate rotation depth, innings projection, vulnerability
- **`/prospect-tracker`** — monitor minor league prospects, flag rapid development or decline
- **`/trade-deadline`** — identify buy vs sell decision based on standings and roster age/cost
