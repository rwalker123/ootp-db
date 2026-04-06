"""Rating engine configuration — tunable constants.

Edit this file to adjust scoring behaviour without touching ratings.py logic.
All values are project-wide defaults; individual skill calls can pass overrides.
"""

# ---------------------------------------------------------------------------
# Sample size / regression thresholds
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Career stats lookback
# ---------------------------------------------------------------------------

# Years of career stats to include when computing ratings and comparisons.
# Applied as: year >= (current_year - CAREER_STATS_LOOKBACK_YEARS)
# Keeps ratings focused on recent performance; prevents pre-sim ghost stats
# (e.g. NL pitcher batting from 2021) from inflating scores.
CAREER_STATS_LOOKBACK_YEARS = 3

# Batters: career PA at which stats are given full (100%) trust.
# Below this, a power ramp blends stats toward the regression anchor.
# Formula: (pa / PA_REGRESSION_THRESHOLD) ** REGRESSION_EXPONENT
PA_REGRESSION_THRESHOLD = 500

# Maximum wRC+ headroom above 100 (league average) allowed at full PA trust.
# At 0 PA: cap = 100 (no headroom). At PA_REGRESSION_THRESHOLD: unconstrained.
# Prevents extreme hot-streak outliers (e.g. wRC+=368 from 13 PA) from
# contributing noise to rating_offense regardless of regression weight.
# Formula: max_wrc = 100 + (pa / PA_REGRESSION_THRESHOLD) ** REGRESSION_EXPONENT * WRC_CAP_HEADROOM
WRC_CAP_HEADROOM = 200

# Pitchers: career MLB IP at which OOTP ratings are no longer blended in.
# Below this, stuff/movement/control are blended in (up to OOTP_MAX_BLEND_WEIGHT).
# Uses the same REGRESSION_EXPONENT as the batter PA ramp.
IP_REGRESSION_THRESHOLD = 100

# Fielding: minimum games at a position to use actual fielding stats.
# Below this, score falls back to OOTP position rating only.
FIELDING_MIN_GAMES = 10

# Minimum catcher CS attempts to score caught-stealing; below this → 50 (average).
CATCHER_MIN_CS_ATTEMPTS = 5

# ---------------------------------------------------------------------------
# Regression curve shape
# ---------------------------------------------------------------------------

# Exponent for the stats-trust ramp used in both batter PA and pitcher IP regression.
#   0.50 = sqrt       — generous (13 PA → 16%, 150 PA → 55%, 300 PA → 77%)
#   0.75              — moderate  (13 PA →  7%, 150 PA → 40%, 300 PA → 68%)
#   0.88              — stricter  (13 PA →  4%, 150 PA → 33%, 300 PA → 64%)
#   1.0  = linear     — harshest  (13 PA →  3%, 150 PA → 30%, 300 PA → 60%)
# Applied as: (sample / threshold) ** REGRESSION_EXPONENT
REGRESSION_EXPONENT = 0.88

# ---------------------------------------------------------------------------
# Offense score blend
# ---------------------------------------------------------------------------

# wRC+ and xwOBA weights in score_offense (must sum to 1.0).
# wRC+ captures accumulated value; xwOBA captures contact quality / luck-neutral hitting.
OFFENSE_WRC_WEIGHT = 0.7
OFFENSE_XWOBA_WEIGHT = 0.3

# ---------------------------------------------------------------------------
# Pitcher OOTP blend (thin-sample IP)
# ---------------------------------------------------------------------------

# Maximum fraction of the run-prevention score that OOTP stuff/movement/control
# can contribute for a pitcher with 0 career MLB IP. Tapers to 0 at IP_REGRESSION_THRESHOLD.
OOTP_MAX_BLEND_WEIGHT = 0.6

# ---------------------------------------------------------------------------
# Defense position multipliers
# ---------------------------------------------------------------------------

# Premium defensive positions (C, SS, 2B, CF) get their defense weight boosted.
DEFENSE_PREMIUM_MULTIPLIER = 1.3

# Bat-first positions (1B, LF, RF) get their defense weight reduced.
DEFENSE_BAT_FIRST_MULTIPLIER = 0.7

# ---------------------------------------------------------------------------
# Player flag thresholds
# ---------------------------------------------------------------------------

# prone_overall >= this → flag_injury_risk = True
INJURY_PRONE_THRESHOLD = 175

# personality_leader >= this → flag_leader = True
LEADER_THRESHOLD = 150

# (pot - oa) >= this → flag_high_ceiling = True
CEILING_GAP_THRESHOLD = 10

# ---------------------------------------------------------------------------
# Flag adjustments to overall rating
# ---------------------------------------------------------------------------

INJURY_OVERALL_DEDUCTION = 10   # subtracted when flag_injury_risk is True
LEADER_OVERALL_BONUS = 3        # added when flag_leader is True

# ---------------------------------------------------------------------------
# Pitcher IP targets for role value scoring
# Starters are scored on IP/STARTER_IP_TARGET; relievers on G/RELIEVER_G_TARGET.
# ---------------------------------------------------------------------------

STARTER_IP_TARGET = 200
RELIEVER_G_TARGET = 70
STARTER_MIN_GS = 5   # GS >= this triggers the starter scoring path

# ---------------------------------------------------------------------------
# Grade thresholds (our letter-grade scoring system)
# Used by letter_grade() in contract_extension, free_agents, draft_targets,
# ifa_targets, waiver_wire, trade_targets, and lineup_optimizer.
# ---------------------------------------------------------------------------
GRADE_A_PLUS = 90
GRADE_A = 80
GRADE_B_PLUS = 70
GRADE_B = 60
GRADE_C_PLUS = 50
GRADE_C = 40
GRADE_D = 30

# ---------------------------------------------------------------------------
# Injury proneness tier thresholds (prone_overall field, 0–200 scale)
# ---------------------------------------------------------------------------
INJURY_IRON_MAN_MAX = 25    # prone_overall <= 25  → "Iron Man"
INJURY_DURABLE_MAX = 75     # prone_overall <= 75  → "Durable"
INJURY_NORMAL_MAX = 125     # prone_overall <= 125 → "Normal"
INJURY_FRAGILE_MAX = 174    # prone_overall <= 174 → "Fragile"
                             # prone_overall > 174  → "Wrecked"

# ---------------------------------------------------------------------------
# Personality trait thresholds (0–200 scale)
# ---------------------------------------------------------------------------
TRAIT_POOR_MAX = 50
TRAIT_BELOW_AVG_MAX = 100
TRAIT_AVERAGE_MAX = 130
TRAIT_GOOD_MAX = 160
                  # > 160 → "Elite"

# ---------------------------------------------------------------------------
# Greed thresholds (0–200 scale)
# ---------------------------------------------------------------------------
GREED_LOW_MAX = 80
GREED_AVERAGE_MAX = 130
GREED_HIGH_MAX = 160
                 # > 160 → "Very High" / "Demanding"

# ---------------------------------------------------------------------------
# wOBA linear weights (FanGraphs-style, used across analytics, report, lineup)
# Canonical source: analytics.py values at project inception.
# ---------------------------------------------------------------------------
WOBA_BB = 0.69
WOBA_HBP = 0.72
WOBA_1B = 0.87
WOBA_2B = 1.27
WOBA_3B = 1.62
WOBA_HR = 2.10
