"""Constants for the rotation analysis skill.

Scoring weights, mode definitions, and thresholds.
All application-level thresholds live here (not in ootp_db_constants.py).
"""

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
MODES = ("balanced", "ace-first", "innings", "six-man")
MODE_LABELS = {
    "balanced": "Balanced",
    "ace-first": "Ace-First",
    "innings": "Innings Eater",
    "six-man": "Six-Man",
}

# ---------------------------------------------------------------------------
# Rotation slot counts
# ---------------------------------------------------------------------------
FIVE_MAN_SLOTS = 5
SIX_MAN_SLOTS = 6

# ---------------------------------------------------------------------------
# Starter pool thresholds
# ---------------------------------------------------------------------------
# Minimum GS in current season to include a non-SP-role player as a starter candidate
MIN_SP_GS_CURRENT = 3
# Minimum GS in most recent prior season for a non-SP-role player
MIN_SP_GS_PRIOR = 5
# Minimum GS to be included in the depth ladder (vs the rotation itself)
DEPTH_MIN_GS = 1

# ---------------------------------------------------------------------------
# Stamina thresholds (pitching_ratings_misc_stamina, 20-80 scale)
# ---------------------------------------------------------------------------
# Minimum stamina for a non-SP-role pitcher to enter the starter pool at all.
# Stamina ~30-35 = pure 1-inning reliever; ~50 = swing-man capable; 60+ = true starter.
MIN_SWING_MAN_STAMINA = 50
# Minimum stamina for any pitcher to be included in the depth ladder as a spot-start option.
MIN_DEPTH_STAMINA = 45
# Stamina normalization: stamina of STAMINA_FULL -> 100 score; STAMINA_POOR -> 0
STAMINA_FULL = 70   # stamina at or above this = full innings durability score
STAMINA_POOR = 35   # stamina at or below this = 0 innings durability score

# ---------------------------------------------------------------------------
# FIP / xFIP normalization range
# FIP of FIP_ELITE -> 100 score; FIP of FIP_POOR -> 0 score
# ---------------------------------------------------------------------------
FIP_ELITE = 2.50
FIP_POOR = 5.50
XFIP_ELITE = 2.75
XFIP_POOR = 5.50

# ---------------------------------------------------------------------------
# Vulnerability flags
# ---------------------------------------------------------------------------
# FIP is this many runs below xFIP → likely BABIP/HR luck, regression risk
FIP_XFIP_LUCK_THRESHOLD = 0.50
# IP threshold: warn if current-season IP is below this for a non-rookie starter
LOW_SAMPLE_IP = 30
# Career GS threshold: warn if pitcher has fewer than this total MLB career GS
# when slotted as #3, #4, or #5 (not the ace slots)
LOW_CAREER_GS_NON_ACE = 15

# ---------------------------------------------------------------------------
# Opener scoring
# ---------------------------------------------------------------------------
# K% thresholds for opener quality
OPENER_K_PCT_GOOD = 0.27
OPENER_K_PCT_POOR = 0.18
# WHIP thresholds
OPENER_WHIP_GOOD = 1.15
OPENER_WHIP_POOR = 1.45
# FIP thresholds for opener role (short-stint specialists can afford slightly higher)
OPENER_FIP_GOOD = 3.50
OPENER_FIP_POOR = 5.00
# Hand-mismatch bonus in opener score (added when opener hand != bulk pitcher hand)
OPENER_OPPOSITE_HAND_BONUS = 10.0
# Minimum IP in current season to be a viable opener candidate
OPENER_MIN_IP = 5

# ---------------------------------------------------------------------------
# Opener slot selection heuristics
# ---------------------------------------------------------------------------
# Which N slots get openers: by default pick the worst-FIP bulk slot(s)
# If FIP-xFIP gap exceeds this on a slot, it gets priority for opener coverage
OPENER_SLOT_LUCK_THRESHOLD = 0.40

# ---------------------------------------------------------------------------
# Scoring weight tables per mode
# Keys: rating_now, fip_score, xfip_score, durability, potential, career_gs_score
# All weights in a dict should sum to 1.0
# ---------------------------------------------------------------------------
BALANCED_WEIGHTS = {
    "rating_now":      0.30,
    "fip_score":       0.25,
    "xfip_score":      0.13,
    "durability":      0.12,
    "stamina_score":   0.15,
    "potential":       0.05,
}

ACE_FIRST_WEIGHTS = {
    "rating_now":      0.22,
    "fip_score":       0.37,
    "xfip_score":      0.22,
    "durability":      0.07,
    "stamina_score":   0.12,
    "potential":       0.00,
}

INNINGS_WEIGHTS = {
    "rating_now":      0.13,
    "fip_score":       0.17,
    "xfip_score":      0.08,
    "durability":      0.27,
    "stamina_score":   0.25,
    "career_gs_score": 0.10,
}

MODE_WEIGHTS = {
    "balanced":  BALANCED_WEIGHTS,
    "ace-first": ACE_FIRST_WEIGHTS,
    "innings":   INNINGS_WEIGHTS,
    "six-man":   BALANCED_WEIGHTS,  # six-man uses balanced ordering
}

# ---------------------------------------------------------------------------
# Career GS normalization for innings mode
# career_gs_score = clamp(career_gs / CAREER_GS_TARGET * 100, 0, 100)
# ---------------------------------------------------------------------------
CAREER_GS_TARGET = 80   # 80 career MLB GS → full workload score

# ---------------------------------------------------------------------------
# Injury history window (years to look back for recent IL stints)
# ---------------------------------------------------------------------------
INJURY_LOOKBACK_YEARS = 2

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
THROWS_LABEL = {1: "R", 2: "L"}
OPENER_SHORT_IP_LABEL = "1-3 IP"
