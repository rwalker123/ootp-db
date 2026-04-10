"""Rating engine configuration — tunable constants.

Edit this file to adjust scoring behaviour without touching src/ratings/ compute logic.
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
# xwOBA is the primary single-number offensive snapshot; wRC+ is supporting evidence.
OFFENSE_WRC_WEIGHT = 0.3
OFFENSE_XWOBA_WEIGHT = 0.7

# wRC+ scale anchors for score_offense.
# LEAGUE_AVG_WRC: baseline — a player at this level scores at the midpoint.
# ELITE_WRC: ceiling — maps to a perfect score of 100; 150+ is considered elite.
# WRC_SCORE_FLOOR: floor — below this wRC+, score approaches 0.
LEAGUE_AVG_WRC = 100
ELITE_WRC = 170
WRC_SCORE_FLOOR = 50
WRC_UNKNOWN_DEFAULT = 95  # assumed wRC+ for players with no track record (95% of league average)

# General scoring scale constants.
# SCORE_MAX: upper bound of all 0–100 composite scores.
# PERCENTILE_AVG: league average percentile — used as the regression target for
#                 thin-sample players (regress toward average, not toward zero).
SCORE_MAX = 100
PERCENTILE_AVG = 50

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
# Batter dimension weights  (must sum to 1.0)
# ---------------------------------------------------------------------------
BATTER_WEIGHT_OFFENSE     = 0.30
BATTER_WEIGHT_CONTACT     = 0.18
BATTER_WEIGHT_DISCIPLINE  = 0.08
BATTER_WEIGHT_DEFENSE     = 0.14
BATTER_WEIGHT_POTENTIAL   = 0.15
BATTER_WEIGHT_DURABILITY  = 0.08   # injury risk only (Performance + Trade)
BATTER_WEIGHT_CLUBHOUSE   = 0.02   # leadership + greed(inv) + loyalty (Trade only)
BATTER_WEIGHT_BASERUNNING = 0.05

# ---------------------------------------------------------------------------
# Pitcher dimension weights  (must sum to 1.0)
# ---------------------------------------------------------------------------
PITCHER_WEIGHT_RUN_PREVENTION      = 0.30
PITCHER_WEIGHT_DOMINANCE           = 0.15
PITCHER_WEIGHT_CONTACT_SUPPRESSION = 0.15
PITCHER_WEIGHT_COMMAND             = 0.10
PITCHER_WEIGHT_POTENTIAL           = 0.15
PITCHER_WEIGHT_DURABILITY          = 0.08   # injury risk only (Performance + Trade)
PITCHER_WEIGHT_CLUBHOUSE           = 0.02   # leadership + greed(inv) + loyalty (Trade only)
PITCHER_WEIGHT_ROLE_VALUE          = 0.05

# ---------------------------------------------------------------------------
# Development / age-decay curve
# ---------------------------------------------------------------------------

# Age at or below which a player gets full ceiling credit (floor).
# Anyone younger than this is treated as if they are exactly this age —
# we don't have enough evidence that very young players develop faster.
DEVELOPMENT_MIN_AGE = 23

# Age at or above which ceiling credit reaches zero (peak age).
# Based on community observation that OOTP players stop progressing ~27;
# treat as a configurable assumption, not a hard game mechanic.
DEVELOPMENT_MAX_AGE = 27

# Curve shape for the age-decay — same exponent pattern as REGRESSION_EXPONENT:
#   0.50 = sqrt    — generous, a 26-year-old still gets ~50% credit
#   0.75           — moderate
#   1.0  = linear  — proportional, clean straight-line decay
#   2.0            — steep, only the youngest get meaningful credit
# Applied as: ((max_age - age) / (max_age - min_age)) ** DEVELOPMENT_EXPONENT
DEVELOPMENT_EXPONENT = 0.75

# Trait blend for "development" (work ethic, intelligence, adaptability).
# Used inside rating_potential (OA/POT gap × realization multiplier × age credit).
# Weights must sum to 1.0.
DEVELOPMENT_TRAIT_WEIGHT_WORK_ETHIC   = 0.40
DEVELOPMENT_TRAIT_WEIGHT_INTELLIGENCE = 0.40
DEVELOPMENT_TRAIT_WEIGHT_ADAPTABILITY = 0.20

# Maps development trait score (0–100) to a multiplier on the OA/POT ceiling gap
# before age credit: m = MIN + (score/100)×(MAX−MIN). MAX > 1 allows exceeding
# the naive ceiling score when traits are elite; MIN < 1 dings poor traits.
DEVELOPMENT_REALIZATION_MULT_MIN = 0.88
DEVELOPMENT_REALIZATION_MULT_MAX = 1.12

# ---------------------------------------------------------------------------
# wOBA linear weights (FanGraphs-style, used across analytics, report, lineup)
# Canonical source: analytics.py values at project inception.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# OOTP rating scale
# ---------------------------------------------------------------------------
# The min/max of the scale chosen in Game Settings → Global Settings →
# Player Rating Scales. Default is 20-80. If you change this in OOTP,
# update these values to match — all (val - min) / range conversions use them.
OOTP_RATING_SCALE_MIN = 20
OOTP_RATING_SCALE_MAX = 80

# ---------------------------------------------------------------------------
# Hitter archetype classification thresholds
# Applied in ratings.queries.classify_batter_archetype(); requires pa >= ARCHETYPE_MIN_PA.
# ---------------------------------------------------------------------------
ARCHETYPE_MIN_PA = 50           # minimum PA before an archetype is assigned

# Speedster / Table-Setter
ARCHETYPE_SPEED_SB        = 15   # sb >= this
ARCHETYPE_SPEED_XSLG_MAX  = 0.420
ARCHETYPE_SPEED_XBA_MIN   = 0.250
ARCHETYPE_SPEED_K_MAX     = 0.22  # either xba OR k_pct qualifies

# Patient Slugger
ARCHETYPE_PATIENT_BB_MIN   = 0.10
ARCHETYPE_PATIENT_XWOBA_MIN = 0.360
ARCHETYPE_PATIENT_XSLG_MIN  = 0.480

# All-or-Nothing Masher
ARCHETYPE_MASHER_BARREL_MIN = 0.10
ARCHETYPE_MASHER_XSLG_MIN   = 0.480
ARCHETYPE_MASHER_K_MIN      = 0.28

# Contact Hitter
ARCHETYPE_CONTACT_K_MAX   = 0.18
ARCHETYPE_CONTACT_XBA_MIN = 0.270
ARCHETYPE_CONTACT_XSLG_MAX = 0.460  # not a power hitter

# Empty Average Bat
ARCHETYPE_EMPTY_XBA_MIN    = 0.250
ARCHETYPE_EMPTY_XSLG_MAX   = 0.380
ARCHETYPE_EMPTY_BARREL_MAX = 0.05

# ---------------------------------------------------------------------------
# Platoon split PA thresholds
# ---------------------------------------------------------------------------
# Minimum PA vs a handedness to give full trust to split stats.
# LHP threshold is lower because batters face fewer LHP (~27% of PAs).
# At PA=0 → fully regressed to WRC_UNKNOWN_DEFAULT / PERCENTILE_AVG.
# At PA=threshold → full trust (pa_trust = 1.0).
PLATOON_LHP_PA_THRESHOLD = 140
PLATOON_RHP_PA_THRESHOLD = 360

WOBA_BB = 0.69
WOBA_HBP = 0.72
WOBA_1B = 0.87
WOBA_2B = 1.27
WOBA_3B = 1.62
WOBA_HR = 2.10

# ---------------------------------------------------------------------------
# Trade value — position class OA adjustments
# ---------------------------------------------------------------------------
# Applied to the offered player's raw OA before computing the return band.
# Positive = premium position (you can ask for more in return).
# Negative = discount position (you'll get less in return).
# String keys for pitcher sub-roles ("sp", "rp", "closer").
# Integer keys for position players by OOTP position code (2=C … 9=RF).
TRADE_POSITION_ADJUSTMENTS = {
    "sp":      3,   # SP: scarce, always in demand
    "rp":     -5,   # RP: deep market discount
    "closer": -2,   # Closer: some premium over generic RP
    2:          3,  # C: scarce
    3:         -3,  # 1B: limited defensive value
    4:          0,  # 2B
    5:          0,  # 3B
    6:          2,  # SS: premium up-the-middle
    7:          0,  # LF
    8:          2,  # CF: premium up-the-middle
    9:          0,  # RF
}

# How far above the matched band ceiling the "add-on required" tier extends.
TRADE_TIER2_OA_ABOVE = 10
