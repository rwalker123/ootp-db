# OOTP Analyst

Turn your OOTP Baseball 27 save into a full analytics suite. OOTP Analyst imports your data, computes advanced metrics, and puts AI-driven scouting tools at your fingertips.

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

```bash
# Clone and enter the project
cd ootp-db

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

3. Once pre-reqs are met, the UI auto-discovers OOTP 27 saves. Click **Import** next to a save to load it into the database. If your saves don't appear, set `OOTP_CSV_PATH` in `.env` to your OOTP installation directory (see Configuration above).

That's it. You can refresh you import at any time to get the lastest save data.

## Exporting CSVs from OOTP

Before running the importer, export your data from within OOTP:

1. Open your save in OOTP Baseball 27
2. Go to **Game > Game Settings > Database tab**
3. Click **Database Tools > Export CSV Files**

This writes CSV files to `saved_games/<save_name>.lg/import_export/csv` inside your OOTP directory.

**Important:** Do not use the MySQL export option -- it generates MySQL-specific SQL that is not compatible with PostgreSQL.

## Usage

Pass your save name as the argument:

```bash
./import.sh Tigers-2026-CBL
```

This runs the full pipeline:

1. Loads all CSVs into PostgreSQL (`tigers_2026_cbl`)
2. Computes advanced batting/pitching stats (wRC+, FIP, xFIP, exit velo, etc.)
3. Computes composite 0–100 player ratings
4. Computes draft prospect ratings
5. Computes IFA prospect ratings

Example output:

```
Created database: tigers_2026_cbl
✓ players (1842 rows)
✓ teams (30 rows)
✓ leagues (2 rows)
...
Done: 45 tables, 28,391 rows in 12.3s
```

## Re-running After a Sim

Just run the same command again. All tables are dropped and recreated, so the database always reflects the latest state of your OOTP save.

```bash
./import.sh Tigers-2026-CBL
```

---

## Claude Code Skills

These skills are available when running Claude Code in this project directory. Invoke them with `/skill-name` in the chat prompt.

---

### `/player-stats <first> <last>`

Full statistical profile for any player — career batting or pitching stats, advanced metrics (wRC+, OPS+, FIP, xFIP, K-BB%, barrel%), current-season splits, and an LLM-written analysis summary. Opens an HTML report in your browser.

```
/player-stats Colt Keith
/player-stats Jackson Jobe
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
