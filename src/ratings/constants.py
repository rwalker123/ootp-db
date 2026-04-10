"""Shared constants for player ratings (batch compute and per-player queries)."""

from config import (
    BATTER_WEIGHT_CONTACT,
    BATTER_WEIGHT_CLUBHOUSE,
    BATTER_WEIGHT_DEFENSE,
    BATTER_WEIGHT_DISCIPLINE,
    BATTER_WEIGHT_DURABILITY,
    BATTER_WEIGHT_OFFENSE,
    BATTER_WEIGHT_POTENTIAL,
    BATTER_WEIGHT_BASERUNNING,
    DEFENSE_BAT_FIRST_MULTIPLIER,
    DEFENSE_PREMIUM_MULTIPLIER,
    OOTP_RATING_SCALE_MAX,
    OOTP_RATING_SCALE_MIN,
    SCORE_MAX,
    PITCHER_WEIGHT_CLUBHOUSE,
    PITCHER_WEIGHT_COMMAND,
    PITCHER_WEIGHT_CONTACT_SUPPRESSION,
    PITCHER_WEIGHT_DOMINANCE,
    PITCHER_WEIGHT_DURABILITY,
    PITCHER_WEIGHT_POTENTIAL,
    PITCHER_WEIGHT_ROLE_VALUE,
    PITCHER_WEIGHT_RUN_PREVENTION,
)
from ootp_db_constants import (
    POS_CATCHER,
    POS_FIRST_BASE as POS_1B,
    POS_SECOND_BASE as POS_2B,
    POS_THIRD_BASE as POS_3B,
    POS_SHORTSTOP as POS_SS,
    POS_LEFT_FIELD as POS_LF,
    POS_CENTER_FIELD as POS_CF,
    POS_RIGHT_FIELD as POS_RF,
)

# Pre-computed scale range for (val - min) / range conversions.
SCALE_RANGE = OOTP_RATING_SCALE_MAX - OOTP_RATING_SCALE_MIN

# Positions where defense score is scaled up (premium) or down (bat-first) in batch + focus reports.
PREMIUM_DEFENSE_POS = {POS_CATCHER, POS_SS, POS_2B, POS_CF}
LOW_DEFENSE_POS = {POS_1B, POS_LF, POS_RF}


def apply_defense_position_score_multiplier(score: float, position: int) -> float:
    """Apply the same premium / low-defense scaling as :func:`score_defense` in ``compute``."""
    if position in PREMIUM_DEFENSE_POS:
        return min(float(SCORE_MAX), float(score) * DEFENSE_PREMIUM_MULTIPLIER)
    if position in LOW_DEFENSE_POS:
        return float(score) * DEFENSE_BAT_FIRST_MULTIPLIER
    return float(score)

# ZR scoring: score = clamp(50 + zr / half_range * 50)
ZR_HALF_RANGE = {
    POS_CATCHER: 1.5, POS_1B: 2.5, POS_2B: 4.5, POS_3B: 5.0,
    POS_SS: 5.5, POS_LF: 6.0, POS_CF: 9.0, POS_RF: 6.5,
}

# DP per 150G scoring
DP_SCALE = {
    POS_1B: (19, 134),
    POS_2B: (43, 116),
    POS_3B: (11, 40),
    POS_SS: (27, 111),
}

POS_FIELD_COL = {
    POS_CATCHER: "fielding_rating_pos2",
    POS_1B: "fielding_rating_pos3",
    POS_2B: "fielding_rating_pos4",
    POS_3B: "fielding_rating_pos5",
    POS_SS: "fielding_rating_pos6",
    POS_LF: "fielding_rating_pos7",
    POS_CF: "fielding_rating_pos8",
    POS_RF: "fielding_rating_pos9",
}

BATTER_WEIGHTS = {
    "offense":         BATTER_WEIGHT_OFFENSE,
    "contact_quality": BATTER_WEIGHT_CONTACT,
    "discipline":      BATTER_WEIGHT_DISCIPLINE,
    "defense":         BATTER_WEIGHT_DEFENSE,
    "potential":       BATTER_WEIGHT_POTENTIAL,
    "durability":      BATTER_WEIGHT_DURABILITY,
    "clubhouse":       BATTER_WEIGHT_CLUBHOUSE,
    "baserunning":     BATTER_WEIGHT_BASERUNNING,
}

PITCHER_WEIGHTS = {
    "run_prevention":      PITCHER_WEIGHT_RUN_PREVENTION,
    "dominance":           PITCHER_WEIGHT_DOMINANCE,
    "contact_suppression": PITCHER_WEIGHT_CONTACT_SUPPRESSION,
    "command":             PITCHER_WEIGHT_COMMAND,
    "potential":           PITCHER_WEIGHT_POTENTIAL,
    "durability":          PITCHER_WEIGHT_DURABILITY,
    "clubhouse":           PITCHER_WEIGHT_CLUBHOUSE,
    "role_value":          PITCHER_WEIGHT_ROLE_VALUE,
}
