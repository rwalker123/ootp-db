# OOTP Analyst

Turn your OOTP Baseball 27 save into a full analytics suite. OOTP Analyst imports your data, computes advanced metrics, and puts AI-driven scouting tools at your fingertips.

AI features run locally through [Claude](https://claude.ai) — no data leaves your machine. The project currently depends on Claude, but could be adapted to work with your preferred LLM. PRs welcome!

**How it works:**
```
OOTP CSV export → importer → PostgreSQL → analytics engine → Claude skills + web UI
```
OOTP exports your save as CSV files, which the importer loads into a local PostgreSQL database. Each import runs an analytics pipeline on top of the raw data — computing advanced stats like wRC+, FIP, and xFIP, along with composite player ratings. Because advanced stats accumulate across imports rather than being overwritten, you build up a multi-year picture of your players over time. Claude Code skills query that database to generate scouting reports, free agent searches, and draft analyses. A lightweight web UI ties it all together for triggering imports and browsing reports without touching the terminal.

OOTP Analyst has been developed and tested on **macOS with the standalone version** of OOTP Baseball 27. It has not been tested with the Steam version or on Windows. Pull requests adding support for either are very welcome.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Quick Start](#quick-start)
- [The Web UI](#the-web-ui)
  - [Saves Table](#saves-table)
  - [Discovered Saves](#discovered-saves)
  - [Ad-Hoc Query](#ad-hoc-query)
  - [Pre-Built Reports](#pre-built-reports)
- [Manual Usage](#manual-usage)
- [Claude Code Skills](#claude-code-skills)
  - [`/player-stats`](#player-stats-first-last)
  - [`/player-rating`](#player-rating-first-last-focus)
  - [`/free-agents`](#free-agents-natural-language-criteria)
  - [`/draft-targets`](#draft-targets-natural-language-criteria)
  - [`/trade-targets`](#trade-targets-player-or-criteria)
  - [`/contract-extension`](#contract-extension-first-last)
  - [`/waiver-claim`](#waiver-claim-first-last)
  - [`/lineup-optimizer`](#lineup-optimizer-options)
- [Contributing](#contributing)

## Prerequisites

- [Python 3.11+](https://www.python.org/downloads/)
- [PostgreSQL](https://www.postgresql.org/download/) running locally
- [Claude Code CLI](https://claude.ai/code)
- [OOTP Baseball 27](https://www.ootpdevelopments.com/out-of-the-park-baseball-home/)

### Installing Python

**macOS:** The easiest option is [Homebrew](https://brew.sh):
```bash
brew install python@3.11
```
Or download the installer from [python.org](https://www.python.org/downloads/).

**Windows:** Download the installer from [python.org](https://www.python.org/downloads/). Make sure to check "Add Python to PATH" during installation.

**Linux (Debian/Ubuntu):**
```bash
sudo apt update && sudo apt install python3.11 python3.11-venv
```

### Installing PostgreSQL

**macOS:** The simplest option is [Postgres.app](https://postgresapp.com) — download, drag to Applications, and launch. It runs in your menu bar. Then add the CLI tools to your PATH (instructions on the Postgres.app site).

Alternatively via Homebrew:
```bash
brew install postgresql@16
brew services start postgresql@16
```

**Windows:** Download the installer from [postgresql.org](https://www.postgresql.org/download/windows/). The installer includes pgAdmin and sets up a service automatically.

**Linux (Debian/Ubuntu):**
```bash
sudo apt update && sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

After installing on Linux, create a superuser role matching your OS username so the importer can connect without a password:
```bash
sudo -u postgres createuser --superuser $USER
```

## Setup

Download and unzip: `https://github.com/rwalker123/ootp-db/archive/refs/heads/main.zip`

> If you plan to contribute to the project, see [Contributing](#contributing) below for the fork-and-clone workflow instead.

```bash
# Enter the unzipped directory
cd ootp-db-main

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
```

Edit `.env` if needed — the default works for most setups:

```
POSTGRES_URL=postgresql://postgres@localhost:5432
```

> If the importer can't find your OOTP saves automatically, you can add `OOTP_CSV_PATH=` to `.env` pointing to your OOTP installation directory.

## Quick Start

1. Make sure [Python 3.11+](https://www.python.org/downloads/) is installed
2. Run:
   ```bash
   ./web-server.sh
   ```
   This sets up the virtual environment, installs dependencies, and opens the web UI at `http://localhost:8000`. The UI shows any remaining pre-requisites (PostgreSQL, etc.) and guides you through setup.

3. The UI auto-discovers OOTP 27 saves. If your saves don't appear, set `OOTP_CSV_PATH` in `.env` to your OOTP installation directory (see Configuration above).
4. Before exporting, configure what gets included: go to **Game > Game Settings > Database tab** and click **Database Tools > Configure data export to CSV files**. I Enabled these two options, no guarantee that removing options will work (AI might not be able to find tables it is looking for):
   - **Additional complete scouted ratings** — required for full player rating reports
   - **Game logs** — required for play-by-play and game log queries

5. Export your data: click **Database Tools > Export CSV Files**. Do not use the MySQL export option.
6. Click **Import** next to a save to load it into the database.
7. Note that in my research, it appears advanced analytic stats are only for the current season. When you import data, previous season advanced analytics are not overwritten. Theoretically, this can give you a long term analysis that the AI can use to evaluate trends in your players.

That's it. You can refresh your import at any time to get the latest save data.

## The Web UI

The web UI is the main control panel for managing your saves and running imports. Open it by running `./web-server.sh` — it will launch automatically at `http://localhost:8000`.

### Saves Table

![OOTP Analyst Import screen](docs/screenshots/OOTP%20Analyst%20Import.png)

The top section lists every save that has been imported at least once. Each row shows:

- **Save** — the name of the `.lg` save file, with the active save highlighted in green. The active save is the one all reports query against.
- **Database** — the PostgreSQL database name derived from the save name (e.g. `My-Save-2026` → `my_save_2026`).
- **Last Import** — the date and time of the most recent successful import.
- **Refresh** — re-runs the full import pipeline for that save (loads CSVs, recomputes advanced stats and ratings). Use this after each sim to refresh your data.
- **Set Active** — sets this save as the active save, directing all reports to query its database.

### Discovered Saves

Below the imported saves, the UI lists any OOTP saves it found on your system that haven't been imported yet. These rows show only the save name — the database and last import columns are empty until you run an import. Click **Import** to load a new save for the first time.

If a save you expect isn't showing up, set `OOTP_CSV_PATH` in `.env` to point to your OOTP installation directory.

### Ad-Hoc Query

![OOTP Analyst Query screen](docs/screenshots/OOTP%20Analyst%20Query.png)

The **Ad-Hoc Query** field lets you ask natural language questions about your save data. Type any question and click **Run** — the AI translates it into SQL, queries the active database, and renders the results as a formatted report with tables and a written summary.

The report appears inline below the query field and includes a small toolbar in the top-right corner. Use **Copy** to copy the full report to your clipboard. Results are in-memory only — they are not saved to disk and will be cleared when you close or refresh the page.

> **Tip:** The AI will naturally frame reports around your team when it knows who you manage. In the screenshot above, it calls out the Tigers specifically in the summary — because that context lives in Claude's memory. Tell Claude which team you manage once and it will color-code its analysis accordingly from that point on.

### Pre-Built Reports

![OOTP Analyst Pre-Built Reports](docs/screenshots/OOTP%20Analyst%20PreBuilt.png)

Below the query field, the UI surfaces all previously generated reports organized by type — Draft Targets, Free Agents, IFA Targets, Player Reports, and Rating Reports. Each entry shows the report name, when it was generated, and an **Open** button to relaunch it in your browser.

Reports are saved as HTML files on disk, so they persist across sessions. When you re-import a save, any report older than the import is flagged as out of date, giving you a clear signal of what's stale and worth regenerating. More report types are on the way — give the existing ones a try.


## Under the Hood

## Manual Usage

These are the scripts the web UI runs behind the scenes. If you're using the web interface, you don't need to run these directly.

### Import Save

Pass your save name as the argument:

```bash
./import.sh {save_name}
```

This runs the full pipeline:

1. Loads all CSVs into PostgreSQL (`{save_name}`)
2. Computes advanced batting/pitching stats (wRC+, FIP, xFIP, exit velo, etc.)
3. Computes composite 0–100 player ratings
4. Computes draft prospect ratings
5. Computes IFA prospect ratings

Example output:

```
Created database: {save_name}
✓ players (1842 rows)
✓ teams (30 rows)
✓ leagues (2 rows)
...
Done: 45 tables, 28,391 rows in 12.3s
```

## Re-running After a Sim

Just run the same command again. All tables are dropped and recreated, so the database always reflects the latest state of your OOTP save.

```bash
./import.sh {save_name}
```

---

## Claude Code Skills

Skills are reusable, project-specific commands that combine a Python data layer with an LLM analysis layer to produce rich HTML reports. Each skill lives in `.claude/skills/<skill-name>/SKILL.md` — a plain Markdown prompt that defines exactly how Claude should interpret your arguments, query the database, and write its analysis.

Invoke a skill by typing `/skill-name` in the Claude Code chat prompt.

### Customizing a skill

Open its `SKILL.md` and edit freely — adjust the analysis tone, change which stats are highlighted, add a new filter option, or modify the HTML output. Claude reads `SKILL.md` fresh on every invocation, so changes take effect immediately with no restart needed.

### Creating a new skill

Ask Claude to build one for you. A prompt like the following will generate a skill that fits the patterns established in this project:

```
Create a new Claude Code skill called /team-report that generates an HTML report for a
given team. Follow the skill architecture in CLAUDE.md exactly: Python entry point in
src/ handles all DB queries and HTML generation; the agent only parses arguments, writes
analysis into the <!-- SUMMARY --> placeholder, and opens the report. Use shared_css.py
for styling and follow the CACHED:/GENERATED: protocol.
```

The key constraint to include: *"Follow the skill architecture in CLAUDE.md exactly."* This ensures the Python/agent division of responsibility, caching protocol, and visual style are all consistent with the existing skills.

---

### `/player-stats <first> <last>`

Full statistical profile for any player — career batting or pitching stats, advanced metrics (wRC+, OPS+, FIP, xFIP, K-BB%, barrel%), current-season splits, and an LLM-written analysis summary. Opens an HTML report in your browser.

```
/player-stats Bryce Harper
/player-stats Aaron Judge
/player-stats Tarik Skubal
```

Reports are cached by player until the next DB import.

---

### `/player-rating <first> <last> [focus]`

Composite 0–100 rating breakdown with 9 sub-scores: contact, power, plate discipline, speed, defense, durability, work ethic, intelligence, and clutch. Optionally pass focus keywords to re-weight the scores toward a particular skill set. Opens an HTML report.

```
/player-rating Bryce Harper
/player-rating Gunner Henderson defense
/player-rating Paul Skenes command, stuff
/player-rating Riley Greene power, discipline
```

---

### `/free-agents <natural language criteria>`

Search all current free agents using plain-English criteria. Translates your query into SQL filters across `player_ratings`, `batter_advanced_stats`/`pitcher_advanced_stats`, and contract tables. Returns a ranked list with ratings, key stats, salary expectations, and an LLM callout summary. Opens an HTML report.

```
/free-agents lefty SP under 28 low injury risk
/free-agents contact SS low greed durable
/free-agents power bat high ceiling affordable
/free-agents starting pitcher under 30 good work ethic WAR above 3
/free-agents FIP under 3.5 righty starter
```

Supported filters: position, age, handedness, stat thresholds (FIP, ERA, WAR, wRC+, OPS), injury risk, work ethic, IQ, greed/salary demands, ceiling flags.

---

### `/draft-targets <natural language criteria>`

Search the **summer draft pool** or **IFA signing pool** for prospects matching your criteria. Automatically routes to the correct pool based on keywords:

- **IFA pool** (Venezuelan/Dominican/Latin 16–18 year-olds, signed in January): triggered by country names ("Venezuelan", "Dominican", "Cuban", etc.) or terms like "IFA", "international signing", "prime age"
- **Draft pool** (domestic + some international players, signed in summer): everything else

Returns a ranked list with OA/POT ratings, tools scores, development traits, and signing risk flags.

**Draft pool examples:**
```
/draft-targets high ceiling SS under 20
/draft-targets college SP good work ethic
/draft-targets power bat elite ceiling affordable
/draft-targets best catching prospects
/draft-targets highest potential starting pitcher
```

**IFA pool examples:**
```
/draft-targets Venezuelan middle infielder
/draft-targets Dominican pitcher high ceiling
/draft-targets best IFA prospects prime age
/draft-targets IFA catcher high work ethic
/draft-targets top Venezuelan outfielders
```

**Flags in reports:**
- 🌟 Elite ceiling (POT ≥ 65)
- ⬆ High ceiling (POT ≥ 55)
- 👶 Prime signing age (16) — IFA only
- ⚡ Elite work ethic
- 🧠 High IQ
- 💰 Demanding / above-slot bonus risk

---

### `/trade-targets <player or criteria>`
Given one or more players you're willing to move, finds realistic return candidates on other teams. Value-matching is based on OOTP's own OA rating (the currency the AI uses when evaluating trades), not the composite analytical score — so the results reflect what other teams would actually consider giving up rather than who is analytically equivalent.

```
/trade-targets Kirk Gibson
/trade-targets Riley Greene for one or more minor league prospects
/trade-targets Framber Valdez, want a young corner infielder with upside
/trade-targets Jackson Jobe and Kyle Finnegan
/trade-targets surplus outfielders, need starting pitching
```

Describe what you're offering in plain English, and optionally what you want back. The skill looks up the offered player(s) on the Tigers roster, assesses their OA-based trade value, checks which positions are thin on Detroit's roster, and builds a filtered candidate list from other MLB teams.

You can also steer the search toward a specific return type — asking for "minor league prospects" or "controllable arms" will shift the query accordingly, as shown below.

![Trade Targets prompt in the web UI](docs/screenshots/OOTP%20Analyst%20Trade%20Prompt.png)

The resulting HTML report opens in your browser with two sections: **What You're Offering** (the offered player's stats, contract, and service time) and the ranked return candidates, sorted by `rating_overall` so the best analytical value within the OA band surfaces first.

![Trade Targets HTML report](docs/screenshots/OOTP%20Analyst%20Trade%20Query.png)

The LLM analysis at the top explains the value tier, names the top specific targets, and flags move candidates — players whose teams are likely to trade them (expensive contracts relative to OA, veterans on rebuilding clubs, or rentals a contender might flip).

**Flags in reports:**
- 🔒 No-trade clause — acquiring team must negotiate carefully
- 📈 High ceiling — POT significantly above current OA
- ⭐ Premium target — Rating ≥ 75; may require sweetening the package
- ⚡ Elite work ethic
- 🧠 High IQ

---

### `/contract-extension <first> <last>`

Recommends a contract extension offer (years + AAV + total value) for any MLB-level player. Combines market rate analysis from comparable contracts, projected WAR trajectory, aging curve, and personality traits into a concrete negotiation range with floor/target/ceiling AAV.

```
/contract-extension Colt Keith
/contract-extension Jackson Jobe
/contract-extension Riley Greene
```

The HTML report opens in your browser with five sections:

- **Current Contract** — active deal details and year-by-year salary timeline
- **Performance History** — last 5 MLB seasons with rate stats and WAR by year
- **Market Comparables** — up to 10 active players at the same position with similar OA ratings, showing their current contracts and service time for market context
- **Personality & Risk Profile** — greed, loyalty, play-for-winner, work ethic, injury proneness
- **Extension Recommendation** — LLM-written analysis covering the recommended deal, performance projection, leverage/urgency, risk flags, and negotiation notes

**Core analysis logic:**
- **Base AAV** is derived from the median comparable salary, scaled by OA
- **Years** cover peak years for young players; avoid buying into the decline phase (age 33+) for veterans
- **Greed > 150**: budget 15–20% above market for the opening ask; **Greed < 80**: may accept below-market
- **Loyalty > 150**: press a ~10% hometown discount; **low loyalty**: pay full market or risk losing them at FA
- **Injury risk**: flag shortens the recommended commitment by 1 year and reduces AAV 10–15%

Reports are cached by player until the next DB import.

**Flags in reports:**
- ⚕ Injury Risk — `flag_injury_risk` is set; factor into deal length
- 📈 High Ceiling — large OA/POT gap; upside premium may be warranted for young players
- 💰 High Greed — player will demand above-market terms
- ❤ Loyal — hometown discount may be available
- ⚡ Elite Work Ethic
- 🧠 High IQ
- 🔒 No-Trade Clause

---

### `/waiver-claim <first> <last>`

Evaluates any player on waivers or DFA against the Tigers' current roster at the same position. Produces a side-by-side comparison with rating deltas, contract obligation, positional flexibility, and a 40-man roster status check, then delivers a clear **CLAIM / PASS / MONITOR** verdict.

```
/waiver-claim Jordan Montgomery
/waiver-claim Mickey Moniak
/waiver-claim George Valera
```

Works for any player — not just those currently on waivers. You can evaluate a DFA'd player, or run it speculatively on any roster player you're considering targeting.

The HTML report opens in your browser with six sections:

- **Claim Recommendation** — LLM-written verdict (CLAIM / PASS / MONITOR) with value comparison, contract cost analysis, and risk flags
- **Your Roster Comparison** — all your players at the same position group (OF grouped together; SP and RP/CL grouped separately), ordered by rating, with the waiver candidate highlighted
- **Current Season Stats** — batting (AVG/OBP/SLG/OPS/wRC+/WAR/Avg EV) or pitching (ERA/FIP/xFIP/WHIP/K%/BB%/WAR)
- **Rating Breakdown** — 9-dimension composite score breakdown (offense, contact, discipline, defense, baserunning, potential, durability, development, clubhouse)
- **Contract Obligation** — full salary timeline if claimed, years remaining, and total obligation
- **Positional Flexibility** — fielding ratings at all playable positions (≥ 40 on 20–80 scale), useful for utility claim decisions
- **40-Man Roster Status** — current count vs. 40-man limit; flags if a DFA is required before claiming

**Verdict logic:**
- **CLAIM** — candidate rating is ≥ 5 points above the weakest incumbent at the position, and contract cost is manageable
- **PASS** — candidate is worse than incumbents, carries an expensive multi-year obligation, or has high injury risk at an already-healthy position
- **MONITOR** — lateral move, or timing isn't urgent (plenty of claim window left, roster is full)

**Key data in the comparison:**
- `rating_vs_best`: candidate rating minus your best player at the position — negative means a downgrade
- `rating_vs_worst`: candidate rating minus your weakest player at the position — positive means a clear upgrade opportunity
- Contract obligation is shown in full; the LLM flags the specific player who would need to be DFA'd if the 40-man is at capacity

Reports are cached by player until the next DB import.

---

### `/lineup-optimizer [options]`

Generates an optimal batting order for your active team (or any named team) using one of five lineup philosophies grounded in sabermetric research. Accounts for career platoon splits, 30-day rolling performance trends, star player protection rules, and positional eligibility floors. Opens an HTML report in your browser.

```
/lineup-optimizer
/lineup-optimizer traditional
/lineup-optimizer vs lefty
/lineup-optimizer platoon vs RHP
/lineup-optimizer aggressive-platoon vs LHP
/lineup-optimizer hot-hand
/lineup-optimizer favor-offense
/lineup-optimizer Cleveland modern vs LHP
/lineup-optimizer without Colt Keith
/lineup-optimizer hot-hand vs RHP without Jordan Montgomery
/lineup-optimizer primary
/lineup-optimizer Torkelson starts at 1B, Montilla bench
/lineup-optimizer traditional vs RHP Dingler starts, Anderson bench, fatigue 70
```

All arguments are optional and combinable. The active team is read from `saves.json` automatically; pass a city name or nickname to target a different team.

#### Philosophies

| Flag | Slot for best hitter | Sort metric | Hot/cold weight |
|------|---------------------|-------------|-----------------|
| `modern` *(default)* | **#2** — maximizes PA + optimal base-out states (Tango/*The Book*) | Season wOBA | Low |
| `traditional` | **#3** — conventional "franchise player" slot | Season wOBA | High |
| `platoon` | **#2** | Blended split wOBA (100+ PA threshold) | Moderate |
| `aggressive-platoon` | **#2** | Blended split wOBA (30+ PA threshold) | Moderate |
| `hot-hand` | **#2** | Season wOBA ± 30-day rolling modifier | High |

**Why #2 in the modern philosophy?** Tango's simulation research (*The Book*, 2007) shows the #2 slot gets ~70 more plate appearances per season than cleanup (#4) and encounters more runners on base than leadoff (#1). The combined PA and base-out advantage makes it the highest-leverage offensive slot in the lineup. Lineup "protection" (inserting a weak bat behind a star) is treated as a myth — the stat is not supported in the research.

#### Opponent handedness

Adding `vs LHP` or `vs RHP` (or `vs lefty` / `vs righty`) adjusts the platoon sort:

- **`platoon` / `aggressive-platoon`**: reshuffles the full sort using matchup-weighted wOBA. The split source hierarchy:

  | Career PA vs handedness | `platoon` | `aggressive-platoon` |
  |------------------------|-----------|----------------------|
  | 300+ | 70% split + 30% season | 70% split + 30% season |
  | 100–299 | 40% split + 60% season | 40% split + 60% season |
  | 30–99 | ratings proxy (±.008) | **40% split + 60% season** |
  | < 30 | ratings proxy (±.008) | ratings proxy (±.008) |

- **Other philosophies**: highlights the favorable split column in the report for reference but does not change slot assignments.

#### Hot/cold trend detection

The skill queries the last 30 game entries per player from the current-season game log and computes a rolling 30-day wOBA. Players are labeled:

| Label | Signal |
|-------|--------|
| **HOT** | 30-day wOBA exceeds season wOBA by ≥ .060 |
| Warm | Exceeds by .030–.059 |
| Cool | Below by .030–.059 |
| **COLD** | Below by ≥ .060 |

Under `hot-hand`, hot players move up one rank position; cold players move down (with a reduced penalty for stars). Under `traditional`, hot/cold trends directly influence slot assignments. Under `modern` and `platoon`, temperature flags are shown in the report for context but do not change the order.

**Star player protection:** A player with career wOBA ≥ .370 or `rating_overall` ≥ 70 is classified as a star (marked ★ in the report). Stars receive half the cold-streak rank penalty of non-stars — a 30-day slump is ~70–80% statistical noise at that sample size, and the opportunity cost of benching a star is 4–7× higher per PA than benching a role player.

#### Position eligibility

Players are eligible at any position where OOTP has assigned them a fielding rating above the floor, with sufficient career experience. Two separate floors apply:

| Position type | Rating floor | Experience floor |
|--------------|-------------|-----------------|
| **Premium defensive positions** (C, 2B, SS, CF) | **≥ 50** | ≥ 5 career games |
| **Corner positions** (1B, 3B, LF, RF) | ≥ 40 | ≥ 5 career games |

The higher floor for premium positions prevents a first baseman with a 45 2B rating from displacing a natural middle infielder — the defensive gap at these positions is too consequential to ignore.

**Batter relief rule:** At premium positions, players whose OOTP-designated primary is a corner/batter spot (1B/3B/LF/RF) are deprioritized in favor of natural defenders. They can still fill a premium spot if no natural defender is available.

**Primary position bonus:** Players competing at their OOTP-designated primary position receive a small scoring bonus, keeping designated 1B players at 1B rather than losing the spot to a 3B filling in.

**Emergency fallback:** If no player meets both floors for a position, the optimizer falls back to anyone with a non-zero fielding rating. Emergency assignments are flagged with a `[!]` badge in the report.

Pass `primary` to restrict every player to their declared primary position only.

#### Defense vs. offense at premium positions

By default, the optimizer gives **significant weight to fielding ratings** at premium defensive positions (C/2B/SS/CF) — a 25-point fielding gap meaningfully influences who gets assigned there. Pass `favor-offense` to reduce that weight if you'd rather let batting quality dominate the decision:

```
/lineup-optimizer favor-offense
/lineup-optimizer platoon vs LHP favor-offense
```

#### Sample-size regression

Rankings use a PA-regressed wOBA rather than raw observed wOBA. At 150 career MLB plate appearances the blend is 50/50 observed vs. a ratings-derived expectation; at 0 PA it is 100% ratings-based. This prevents a 9-game call-up on a hot streak from displacing an established starter, while still allowing a highly-rated prospect (0 PA, first start) to earn a spot on talent. The PA column is shown in amber when a player has fewer than 80 PA.

#### Excluding players

Pass `without <player name>` to remove a player from the eligible pool — useful for rest days, injuries, or "what if" scenarios.

#### Manager overrides (force-start / force-bench)

OOTP's in-game "Force Start" and "Force Bench" settings are not exported to CSV, so they cannot be read directly. Instead, pass them as skill arguments. Because you have to retype them each run, save your preferred combination as a prompt snippet and paste it in.

| Syntax | Effect |
|--------|--------|
| `<name> starts` | Guarantees the player a lineup spot at their primary position |
| `<name> starts at <pos>` | Locks the player to that specific position, bypassing eligibility floors |
| `<name> at <pos> starts` | Same as above, alternate word order |
| `<name> bench` | Sits the player regardless of their stats |
| `fatigue <N>` | Auto-benches any player whose `fatigue_points` ≥ N (0–100 scale) |

Multiple overrides can be chained with commas:

```
/lineup-optimizer traditional vs RHP Torkelson starts at 1B, Dingler starts, Montilla bench, fatigue 70
```

Forced starters are shown with a blue `[F]` badge in the report. Forced-bench and fatigued players appear with labeled badges in the roster section. Any run with overrides bypasses the report cache.

#### The HTML report

- **Lineup card** — slots 1–9 with position, handedness, temperature tag, wRC+, PA, OBP, ISO, season wOBA, split wOBA vs LHP/RHP, 30-day rolling wOBA, fatigue, and speed rating
- **L/R alternation score** (0–10) and the full L/R/S pattern string
- **Philosophy comparison panel** — when using a non-modern philosophy, shows side-by-side which slots differ from the Tango-optimal Modern ordering
- **Full roster stats table** — all eligible batters with Starting/Bench/Fatigued/[F] Bench labels
- **LLM analysis** — four-bullet breakdown covering the philosophy rationale, key slot decisions, hot/cold interpretation, and handedness balance assessment

Reports are cached per team + philosophy + handedness until the next DB import. Runs with any overrides (forced starts/bench, fatigue threshold, favor-offense) always regenerate.

---

## Contributing

Contributions are welcome. Only the repo owner can merge PRs.

### Workflow

1. Fork the repo: `https://github.com/rwalker123/ootp-db/fork` — creates your own copy, no need to be added as a collaborator.
2. Clone your fork:
   ```bash
   git clone https://github.com/<your-username>/ootp-db.git
   cd ootp-db
   ```
3. Complete the [Setup](#setup) steps above (venv, pip install, .env), then also activate git hooks:
   ```bash
   pre-commit install
   ```
4. Create a branch from `main`:
   ```bash
   git checkout -b feat/your-feature
   ```
5. Make your changes and commit them — direct commits to `main` are blocked.
6. Push to your fork:
   ```bash
   git push origin feat/your-feature
   ```
7. Open a pull request against `rwalker123/ootp-db main`.
8. The repo owner ([@rwalker123](https://github.com/rwalker123)) reviews and merges all PRs.

Branches are automatically deleted after a PR is merged.
