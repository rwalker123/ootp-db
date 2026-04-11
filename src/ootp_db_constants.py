"""OOTP-defined enum values, split_id constants, and at-bat result codes.

These are fixed values defined by the OOTP Baseball game engine — do not change them.
All application-level thresholds (grade cutoffs, injury tiers, wOBA weights, etc.)
belong in config.py, not here.
"""

# ---------------------------------------------------------------------------
# League / Level IDs
# ---------------------------------------------------------------------------
MLB_LEAGUE_ID = 203
MLB_LEVEL_ID = 1
AAA_LEVEL_ID = 2
AA_LEVEL_ID = 3
A_LEVEL_ID = 4        # All A-ball (no High-A/Low-A split in this save)
# Note: level_id=5 = All-Star teams / unassigned players (not a playing level)
ROOKIE_LEVEL_ID = 6

# ---------------------------------------------------------------------------
# Sub-league IDs
# ---------------------------------------------------------------------------
SUB_LEAGUE_AL = 0
SUB_LEAGUE_NL = 1

# ---------------------------------------------------------------------------
# Position codes
# ---------------------------------------------------------------------------
POS_PITCHER = 1
POS_CATCHER = 2
POS_FIRST_BASE = 3
POS_SECOND_BASE = 4
POS_THIRD_BASE = 5
POS_SHORTSTOP = 6
POS_LEFT_FIELD = 7
POS_CENTER_FIELD = 8
POS_RIGHT_FIELD = 9

POS_MAP = {
    1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B",
    6: "SS", 7: "LF", 8: "CF", 9: "RF",
}
# Reverse lookup used by lineup optimizer
POS_STR_MAP = {v: k for k, v in POS_MAP.items()}
POS_STR_MAP["dh"] = 0
# Also provide lowercase versions used by lineup_optimizer
POS_STR_MAP["p"] = 1
POS_STR_MAP["c"] = 2
POS_STR_MAP["1b"] = 3
POS_STR_MAP["2b"] = 4
POS_STR_MAP["3b"] = 5
POS_STR_MAP["ss"] = 6
POS_STR_MAP["lf"] = 7
POS_STR_MAP["cf"] = 8
POS_STR_MAP["rf"] = 9

# ---------------------------------------------------------------------------
# Bats / Throws codes
# ---------------------------------------------------------------------------
BATS_RIGHT = 1
BATS_LEFT = 2
BATS_SWITCH = 3

THROWS_RIGHT = 1
THROWS_LEFT = 2

BATS_MAP = {1: "R", 2: "L", 3: "S"}
THROWS_MAP = {1: "R", 2: "L"}

# ---------------------------------------------------------------------------
# Pitcher role codes
# ---------------------------------------------------------------------------
ROLE_SP = 11
ROLE_RP = 12
ROLE_CL = 13

# Note: role codes 2–9 appear on retired/imported historical players where role
# equals their position code — a data artifact, not active pitcher sub-roles.
# In-game sub-roles (Emergency SP, Opener, Stopper) do not appear as distinct
# role codes in the CSV export.
ROLE_MAP = {0: "—", 11: "SP", 12: "RP", 13: "CL"}

# ---------------------------------------------------------------------------
# Game type codes
# ---------------------------------------------------------------------------
GAME_TYPE_REGULAR = 0
GAME_TYPE_SPRING = 2
GAME_TYPE_PLAYOFFS = 3
GAME_TYPE_ALLSTAR = 4
GAME_TYPE_FUTURES = 8

# ---------------------------------------------------------------------------
# Nation IDs
# ---------------------------------------------------------------------------
NATION_USA = 206

# ---------------------------------------------------------------------------
# Scouting team IDs
# ---------------------------------------------------------------------------
SCOUTING_TRUE_RATINGS = 0   # scouting_team_id=0, coach_id=-1 → ground-truth ratings

# ---------------------------------------------------------------------------
# At-bat result codes (players_at_bat_batting_stats.result)
# ---------------------------------------------------------------------------
RESULT_K = 1
RESULT_BB = 2
RESULT_GROUNDOUT = 4
RESULT_FLYOUT = 5
RESULT_SINGLE = 6
RESULT_DOUBLE = 7
RESULT_TRIPLE = 8
RESULT_HR = 9
RESULT_HBP = 10

# ---------------------------------------------------------------------------
# Draft hsc_status codes
# Players with draft_eligible=1 are grouped into draft classes by hsc_status.
# Only draft_league_id = MLB_LEAGUE_ID players belong to the MLB draft.
# ---------------------------------------------------------------------------
# Current MLB draft pool (upcoming draft)
HSC_CURRENT_POOL = (4, 5, 6, 9, 10)

# Future draft classes (years ahead of current season)
HSC_FUTURE_1 = (3, 8)   # 1 year out
HSC_FUTURE_2 = (2, 7)   # 2 years out
HSC_FUTURE_3 = (1,)     # 3 years out

# ---------------------------------------------------------------------------
# split_id constants
# ---------------------------------------------------------------------------

# --- Career batting & pitching (players_career_batting_stats, players_career_pitching_stats) ---
# In standard CSV exports, split_id=0 does NOT appear. Overall regular-season career rows use
# split_id=1 for all years (real history + simulated seasons combined).
SPLIT_CAREER_OVERALL = 1     # overall regular season (only overall bucket for batting/pitching)
SPLIT_CAREER_VS_LHP = 2      # batter vs LHP / pitcher vs LHB
SPLIT_CAREER_VS_RHP = 3      # batter vs RHP / pitcher vs RHB
SPLIT_CAREER_POSTSEASON = 21  # playoff stats

# --- Career fielding (players_career_fielding_stats) only — NOT the same as batting/pitching ---
# OOTP stores two disjoint era buckets (year ranges depend on the save). Both are needed for
# all-time games/totals across real history + sim. Use IN (0, 1); do not assume career batting rules.
SPLIT_CAREER_FIELDING_SIM_ERA = 0       # simulated-era bucket (e.g. current sim years in export)
SPLIT_CAREER_FIELDING_HISTORICAL = 1    # historical bucket (pre-sim / prior-era rows in export)

# --- Current-season team stat tables ---
# (team_batting_stats, team_bullpen_pitching_stats, team_starting_pitching_stats,
#  team_fielding_stats_stats)
# NOTE: batting and pitching overall use *different* values — OOTP inconsistency.
SPLIT_TEAM_BATTING_OVERALL = 0    # overall current season (batting stats)
SPLIT_TEAM_PITCHING_OVERALL = 1   # overall current season (pitching stats, MLB teams)
SPLIT_TEAM_VS_LHP = 2             # vs LHP (batting) / vs LHB (pitching)
SPLIT_TEAM_VS_RHP = 3             # vs RHP / vs RHB

# --- team_history_batting_stats / team_history_pitching_stats ---
# Do NOT filter by split_id in these tables. OOTP uses different (split_id, level_id)
# combinations depending on era (real history vs simulated seasons). The JOIN to
# team_history with league_id=203 is sufficient; filtering by split_id drops data.
