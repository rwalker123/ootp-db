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

### [ ] 6. Rotation Analysis (`/rotation-analysis`)

Build an optimal **five-man starting rotation** (with clear **depth order** for spots 6–7+) from the pool of starters on a team. Compare the recommendation to OOTP’s own projection, surface **depth and workload risk**, and optionally evaluate a **six-man**, **short-rest**, or **partial opener** plan when the user asks. **Opener:** a reliever starts and is expected to cover **about 1–3 innings** (often only 1), followed by a **bulk** arm (typically a traditional starter) for the middle and late innings — commonly a **platoon flip** (e.g. **LHP opener** then **RHP bulk**). Real teams **rarely** use an opener every day; the skill takes **`openers=N`** so only **N** of the five rotation slots use opener+bulk — the other **5−N** slots stay **traditional starter only**.

**Inputs:** `[team name (optional)] [mode (optional)] [opener | openers=N (optional)] [constraints (optional)]` — bare **`opener`** means **`openers=1`** (the usual case); use **`openers=2`**, **`openers=0`**, etc. when you need an explicit count.

Examples:
- `/rotation-analysis` — active team; default mode balances current run prevention, durability, and `rating_now`
- `/rotation-analysis Cleveland` — named team, same defaults
- `/rotation-analysis ace-first` — weight top-of-rotation FIP/WAR heavily for ordering 1–3
- `/rotation-analysis innings` — prioritize pitchers with high recent IP/GS and low injury flags (workload absorbers)
- `/rotation-analysis six-man` — split innings across six arms; show who drops to long relief / swingman
- `/rotation-analysis opener` — shorthand for **`openers=1`**: one rotation day uses opener+bulk; the other four are normal starters (typical real-world pattern)
- `/rotation-analysis openers=1` — same as **`opener`** (explicit count)
- `/rotation-analysis openers=2` — two rotation slots get an opener; three stay traditional
- `/rotation-analysis balanced opener` — bulk order from `balanced`; one opener pairing (`openers=1`)
- `/rotation-analysis ace-first opener` — same with `ace-first` bulk ordering
- `/rotation-analysis without [player name]` — exclude an injured or traded starter from the pool

**Modes / philosophies** (default: `balanced`):
- `balanced` — blend `rating_now`, career/season FIP (and xFIP as regression check), durability / injury context, and age-weighted upside (`rating_potential` lightly) for slots 1–5
- `ace-first` — sort primarily by current run prevention (FIP, xFIP, K-BB%) and `rating_now`; durability is a tiebreaker, not primary
- `innings` — prioritize arms likely to take the ball every fifth day: career + recent GS/IP, `rating_durability`, low `flag_injury_risk` / `prone_overall`; FIP secondary
- `six-man` — select six starters by the same score as `balanced`, show projected innings share vs five-man baseline, and name the **odd man out** for bullpen or spot starts
- `playoff` — optional compact mode: rank top 4 by FIP + recent performance for a short series; flag L/R mix at the front
- `opener` / `openers=N` — **modifier**. Bare **`opener`** ⇒ **`N=1`**. **`openers=N`** with `N` integer **0–5**: **`openers=0`** turns opener logic off; **omit** both `opener` and any `openers=*` ⇒ no openers. Combine with `balanced`, `ace-first`, or `innings` for **bulk** slot ordering. The five rotation slots are still the five bulk starters; only **N** of those days also list an **opener** (from the RP pool) ahead of the bulk arm. **`N` is not “five openers”** — it is “how many games in the turn use this tactic,” usually **1** (sometimes 2). Pick **which** N slots get openers by ranking bulk days where an opener helps most (default heuristic: e.g. worst season FIP among the five, largest FIP−xFIP gap, or best expected gain from an opposite-hand first inning — configurable); allow user hints later (“opener when [pitcher] starts”). For each chosen slot only: score openers for short stints (K%, WHIP, FIP/xFIP, `rating_now`, **vs LHB / vs RHB** from `pitcher_advanced_stats` when the user names an opponent or lineup handedness). **Pairing rule:** when multiple openers are similar quality, prefer **opposite hand** to the bulk pitcher (LHP opener + RHP bulk, or reverse). If `N` exceeds the count of **viable** opener candidates (after exclusions), cap `N`, warn, and list who was skipped.

**Data sources:**
- `saves.postgresql.json` / `saves.sqlite.json` + `human_managers` / `teams` — resolve active or named `team_id` (same team-resolution pattern as `/lineup-optimizer`; never hardcode a franchise)
- `team_roster` — restrict to the org’s MLB roster; use `list_id` to focus on active / 25-man where appropriate
- `players` — `position`, `role` (11=SP, 12=RP, 13=Closer per `ootp_db_constants`), `throws` (1=R, 2=L) for opener/bulk handedness pairing, `age`
- `players_roster_status` — exclude IL, DFA, and clearly non-roster states that should not be scheduled to start
- `pitcher_advanced_stats` — IP, GS, G, FIP, xFIP, K%, BB%, WHIP, HR/9, GB%, WAR, WPA; career **vs LHB / vs RHB** columns produced by analytics (e.g. `fip_vs_lhb`, `fip_vs_rhb`, `k_pct_vs_lhb`, `k_pct_vs_rhb`) to rank openers for the first trip through the order; for bulk arms, season line still drives primary slot score
- `player_ratings` — `rating_overall`, `rating_now`, `rating_potential`, `rating_durability`, `flag_injury_risk`, `confidence`, `prone_overall` (pitchers on MLB row set)
- `players_career_pitching_stats` — career IP, GS, starts volume (`split_id` / level filters per AGENTS.md) for workload history and rookie vs established workload caps
- `players_pitching` — stuff / movement / control (and vs L/R if exported) as a tiebreaker when stats are thin or `confidence` is low
- `projected_starting_pitchers` — `starter_0` … `starter_7` as **OOTP’s baseline order**; diff the recommended order vs game projection in the report
- `players_injury_history` — optional enrichment for “innings” and “balanced” modes (recent major injuries, IL frequency)
- `players_contract` / `players_value` — optional sidebar: years of control and OA for trade-off narrative (not required for pure ordering)

**Output:**
- HTML report: **recommended rotation card** (slots 1–5 with name, age, hand, key line: FIP, xFIP, IP, GS, K-BB%, `rating_now`, durability flag)
- **Depth ladder**: ordered list for spots 6–7+ (next man up, emergency spot starter) from the same starter pool
- **vs OOTP projection** table: side-by-side slot comparison (`projected_starting_pitchers` vs model order) with ↑/↓ moves
- **Depth & vulnerability panel:**
  - innings projection heuristic (remaining season starts × recent IP/start, capped sanely) — *explicitly labeled as approximate*
  - flags: large **FIP − xFIP** gap (luck/regression risk), low `confidence`, high injury proneness, very low career GS for a #3–#5 slot
- **Six-man variant** (when requested): six names, innings share sketch, and bullpen implication
- **Opener variant** (when **`opener`** or `openers=N` with **`N≥1`**): for **N** slots only, show a **two-line row** — **Opener** (hand, ~1–3 IP note, FIP/K%, split highlights) + **Bulk** (same as standard rotation line). The **remaining 5−N** slots are **single-line** traditional starters. Call out **which** rotation days use an opener and **why those days were chosen**. Show **handedness pairing** (L/R) and a short **why this opener** blurb per tagged day. Flag if a chosen opener is the closer or would overtax thin bullpen depth (usage conflict warning)
- Terminal summary: five bulk names in order; if **`opener`** or `openers=N` with **N≥1**, note which **N** days have openers and who; one-line rationale; biggest disagreement with OOTP’s `starter_0`; top risk flag

**Core logic:**

*Starter pool construction:*
- Begin with MLB `team_id` roster players whose `role` is SP (11) or who have meaningful GS in current or recent career rows (configurable threshold in code, e.g. GS ≥ 3 in current season or prior season in `players_career_pitching_stats`)
- Exclude users’ named players and anyone on IL / ineligible via `players_roster_status`
- If fewer than five eligible starters: fill report with available arms, flag **rotation hole**, suggest trade/FA skills

*Opener assignment (when **`opener`** or `openers=N` with **`N≥1`**):*
- **Opener candidates:** `role` = RP (12), optionally closers (13) only if user allows or depth is thin — default policy: prefer multi-inning–capable relievers (high IP or G relative to saves, configurable); exclude anyone the user names as untouchable for bullpen role
- **Bulk candidates:** same as starter pool above; assign **five bulk slots first** (using `balanced`, `ace-first`, or `innings`), then **choose N distinct bulk slots** for opener coverage using the roadmap heuristic (worst FIP slot, best platoon-flip opportunity, etc.) — **not** all five
- **Per chosen slot:** pick one opener by (1) composite **short-outing** score, (2) matchup vs **top-of-order** if user gave a hint, (3) **opposite hand to bulk** when within a small quality threshold of the best same-hand option
- **Do not reuse** the same opener on back-to-back opener days when the roster has enough distinct candidates; if `N` > distinct viable openers, lower effective `N` or allow reuse with a **fatigue / depth warning**

*Scoring / ordering (default `balanced`):*
- Base score = weighted z-style blend of: (1) `rating_now`, (2) inverted FIP (lower better), (3) xFIP as stabilizer, (4) durability / injury flags, (5) small weight on `rating_potential` for ages under a cutoff (e.g. under 26)
- `ace-first`: weight (2) and (3) heavily; durability only after top tier is set
- `innings`: weight career GS, recent IP, and durability components heavily; deprioritize short-sample FIP outliers
- Assign slots 1–5 by descending score; **tiebreakers**: higher `rating_now`, then lower xFIP, then more career GS

*Depth and vulnerability:*
- **Depth**: rank all remaining pool members by the same score for slots 6+
- **Innings projection**: use current-season IP and GS from `pitcher_advanced_stats` to estimate IP per start; multiply by rough remaining starts — document formula in code comments / skill prompt; never present as exact OOTP simulation output
- **Vulnerability flags**: e.g. FIP materially below xFIP by more than a threshold (config; luck/regression risk), `flag_injury_risk` true, `prone_overall` above config cutoff, or rookie with fewer than N career GS slotted as #4/#5

*OOTP baseline diff:*
- Map `projected_starting_pitchers.starter_k` to players; compare rank order to model order; highlight when the game’s #1 is not the model’s #1 and why (FIP vs durability vs ratings)

**Considerations:**
- Follow the skill architecture in **CLAUDE.md** / **AGENTS.md**: Python generates HTML + prints `CACHED:` / `GENERATED:`; agent fills a single analysis placeholder and opens the report; use `ootp_db_constants` for `role`, `position`, `league_id`, and career `split_id` rules — no magic numbers
- Starters on the 40-man but in minors are out of scope unless the user explicitly asks for “all org SP”; default is **current MLB roster**
- **Doubleheaders / short rest** are not fully simulatable from CSV alone; mention as narrative only or future enhancement if game-level start data is insufficient
- If `pitcher_advanced_stats` has low IP (early season), lean more on `player_ratings` and career rows; show **low-sample warnings**
- Web UI parity: same entry point pattern as other skills (registry save, optional team override)
- **Openers:** OOTP’s `projected_starting_pitchers` reflects traditional starters only — opener lines are **strategy overlays**. Parse **`opener`** as **`N=1`**. For **`openers=N`**, validate `0≤N≤5`; malformed values → treat as **0** or error clearly. Real-world bullpen roles may conflict; surface **usage risk** when recommending a top leverage arm as opener, especially when `N` is small and the same arm would pitch often

---

### [x] 7. Lineup Optimizer (`/lineup-optimizer`)

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

## Future Ideas (not yet scoped)

- **`/prospect-tracker`** — monitor minor league prospects, flag rapid development or decline
- **`/trade-deadline`** — identify buy vs sell decision based on standings and roster age/cost
