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

Skills are reusable, project-specific Claude Code commands that combine a Python data layer with an LLM analysis layer to produce rich HTML reports. Each skill lives in `.claude/skills/<skill-name>/SKILL.md` — a plain Markdown prompt that defines exactly how Claude should interpret your arguments, query the database, and write its analysis.

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
/player-rating Colt Keith
/player-rating Colt Keith defense
/player-rating Jackson Jobe command, stuff
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
