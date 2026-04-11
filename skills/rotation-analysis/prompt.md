# Rotation Analysis

Builds an optimal starting rotation (5-man by default, 6-man on request) for the active
team or a named team. Scores pitchers using a named mode, surfaces vulnerability flags,
optionally plans opener+bulk pairings, and diffs the recommendation vs OOTP's own projected
rotation.

## Context isolation

If you have the ability to delegate this to a sub-agent or fresh context, do so — pass
these full instructions and the arguments to it. Otherwise, treat this as an isolated task:
do not reference or carry over any player names, stats, analysis, or conclusions from
earlier in this conversation.

**Never use `open` to launch the report.** Print the `file://` path instead and stop.

## Argument substitution

`$ARGUMENTS` is the full text of the user's invocation message (e.g. "ace-first" or "opener without Skubal").
Before running any code block, replace `$ARGUMENTS` inside string literals (e.g. `raw_args="$ARGUMENTS"`)
with the user's full input verbatim.

## Usage

```
/rotation-analysis
/rotation-analysis ace-first
/rotation-analysis innings
/rotation-analysis six-man
/rotation-analysis opener
/rotation-analysis openers=2
/rotation-analysis balanced opener
/rotation-analysis ace-first openers=2
/rotation-analysis Cleveland
/rotation-analysis Cleveland ace-first
/rotation-analysis without Tarik Skubal
/rotation-analysis innings without Casey Mize
/rotation-analysis with Jackson Jobe
/rotation-analysis include Jackson Jobe
/rotation-analysis with Jackson Jobe without Casey Mize
```

## Mode Quick Reference

| Mode | Primary Sort Signal | Use When |
|------|---------------------|----------|
| `balanced` (default) | Blend of rating_now + FIP + xFIP + durability | General-purpose optimal rotation |
| `ace-first` | Heavily weights FIP + xFIP; best run-preventer at #1 | Want pure run-prevention ordering |
| `innings` | Weights durability + career GS heavily; FIP secondary | Need workload absorbers, minimize bullpen strain |
| `six-man` | Balanced scoring across 6 slots | Managing workload or recovering from injury |

## Step 1: Parse arguments

From `$ARGUMENTS`, identify:

- **Team name** (optional): a city name or nickname not matching a mode keyword (e.g. "Cleveland", "Tigers").
  Default: active human manager's team.
- **Mode** (optional): one of `balanced`, `ace-first`, `innings`, `six-man`.
  Accept "ace first" → `ace-first`; "innings eater" → `innings`; "6-man" or "6 man" → `six-man`.
  Default: `balanced`.
- **Opener count** (optional):
  - Bare `opener` → `n_openers=1`
  - `openers=N` (e.g. `openers=2`) → `n_openers=N`
  - Omitted → `n_openers=0`
  - `openers=0` → `n_openers=0` (explicitly no openers)
  - Invalid N → treat as 0
- **Excluded players** (optional): `without <name>` — player is removed from the starter pool.
  Multiple `without` clauses allowed (e.g. "without Skubal without Mize").
- **Forced players** (optional): `with <name>` or `include <name>` — player is guaranteed a
  rotation slot regardless of score (useful for prospects/call-ups you want to evaluate in context).
  Multiple `with`/`include` clauses allowed. Forced pitchers show a `[F]` badge in the report.

Set variables: `TEAM`, `MODE`, `N_OPENERS`, `EXCLUDED` (list).

## Step 2: Run Python

Run the following Python command (fill in variables from Step 1):

```bash
( cd src && ../.venv/bin/python3 -m rotation_analysis "$SAVE_NAME" $MODE ${N_OPENERS:+openers=$N_OPENERS} ${TEAM:+"$TEAM"} ${EXCLUDED:+without "$EXCLUDED"} )
```

Or, more reliably, use a heredoc to call the function directly:

```bash
.venv/bin/python3 << 'PYEOF'
import sys
sys.path.insert(0, "src")
from rotation_analysis import generate_rotation_report
from shared_css import load_saves_registry
save = load_saves_registry()["active"]
path, data = generate_rotation_report(
    save,
    team_query=TEAM_OR_NONE,
    mode="MODE",
    n_openers=N_OPENERS,
    six_man=SIX_MAN_BOOL,
    excluded_names=EXCLUDED_LIST,
    raw_args="$ARGUMENTS",
)
if path is None:
    print("ERROR: team not found or no eligible starters")
    sys.exit(1)
prefix = "CACHED" if data is None else "GENERATED"
print(f"{prefix}:{path}")
if data:
    import json
    print(json.dumps(data, default=str))
PYEOF
```

Replace:
- `TEAM_OR_NONE` with a quoted team name string, or `None`
- `"MODE"` with the mode string (e.g. `"balanced"`)
- `N_OPENERS` with the integer (e.g. `1`)
- `SIX_MAN_BOOL` with `True` or `False`
- `EXCLUDED_LIST` with a Python list of strings, or `[]`

**On `CACHED:<path>`:** print the file path and stop — no further action needed.

**On `GENERATED:<path>`:** continue to Step 3.

## Step 3: Write analysis into the HTML placeholder

Read the generated HTML file. Locate the comment:

```html
<!-- ROTATION_SUMMARY -->
```

Replace it with an analysis block:

```html
<div class="summary">
  <ul style="margin:0;padding-left:20px;line-height:1.9">
    <li><!-- Overall rotation strength assessment: composite scores, FIP range, #1 starter quality --></li>
    <li><!-- Biggest disagreement with OOTP's projected rotation and why the model differs --></li>
    <li><!-- Top risk or vulnerability flag (injury risk, regression candidate, low-sample arm) --></li>
    <li><!-- Opener recommendation if n_openers > 0: which slot benefits most and why; or "No opener plan requested" if n_openers=0 --></li>
  </ul>
</div>
```

Write real analysis sentences for each bullet using data from the JSON output:
- `rotation_names`: ordered list of 5 (or 6) starter names
- `mode`: scoring mode used
- `n_starters`, `n_openers`
- `top_flag`: first vulnerability flag found (if any)
- `ootp_disagree`: first slot where model and OOTP differ (`model_name`, `ootp_name`, `move_str`)

Write the updated HTML back to the same file path.

## Step 4: Print terminal summary

After writing the analysis, print a concise terminal summary:

```
Rotation Analysis — <Team> | <Mode>
  #1 <Name> (FIP <x.xx>)
  #2 <Name> (FIP <x.xx>)
  #3 <Name> (FIP <x.xx>)
  #4 <Name> (FIP <x.xx>)
  #5 <Name> (FIP <x.xx>)
  [#6 <Name> (FIP <x.xx>)  ← only if six-man]

  [Opener plan: Slot #N — <Opener> → <Bulk>  ← only if openers > 0]
  Risk: <top_flag or "None">
  OOTP diff: <model_name> vs <ootp_name> at #<slot>  (or "Agrees with OOTP #1" if same)

Report: file://<path>
```

Print `Report: file://<path>` at the end so the user can click it.

## Decision reference bands

**FIP / xFIP:**
- ≤ 3.00 → elite (green)
- 3.01–4.00 → average (orange)
- > 4.00 → poor (red)

**K-BB%:**
- ≥ 18% → good
- < 8% → concerning

**WHIP:**
- ≤ 1.15 → elite
- 1.16–1.40 → average
- > 1.40 → poor

**Score (0–100 composite):**
- ≥ 70 → top-of-rotation quality
- 50–69 → mid-rotation viable
- 40–49 → back-end / depth
- < 40 → spot-start / emergency

**Vulnerability flags to mention by name if present:**
- "Regression risk" → FIP is materially below xFIP (pitcher may regress)
- "Low sample" → fewer than 30 IP this season (treat projections as low-confidence)
- "Injury risk flag" → player_ratings flagged this pitcher
- "Inexperienced starter" → fewer than 15 career MLB GS at a non-ace slot
- "Low confidence rating" → scoring is stats-only (no scouted current ratings)
