"""Shared presentation helpers used across multiple report modules.

Pure functions only — no DB access, no pandas, no heavy imports.
All color helpers return CSS hex strings; label helpers return display strings.
"""

from config import (
    GRADE_A_PLUS, GRADE_A, GRADE_B_PLUS, GRADE_B, GRADE_C_PLUS, GRADE_C, GRADE_D,
    INJURY_IRON_MAN_MAX, INJURY_DURABLE_MAX, INJURY_NORMAL_MAX, INJURY_FRAGILE_MAX,
    TRAIT_POOR_MAX, TRAIT_BELOW_AVG_MAX, TRAIT_AVERAGE_MAX, TRAIT_GOOD_MAX,
    GREED_LOW_MAX, GREED_AVERAGE_MAX, GREED_HIGH_MAX,
)

# ---------------------------------------------------------------------------
# Letter grades
# ---------------------------------------------------------------------------

def letter_grade(score):
    """Convert a 0–100 composite score to a letter grade (A+…F)."""
    if score >= GRADE_A_PLUS:
        return "A+"
    if score >= GRADE_A:
        return "A"
    if score >= GRADE_B_PLUS:
        return "B+"
    if score >= GRADE_B:
        return "B"
    if score >= GRADE_C_PLUS:
        return "C+"
    if score >= GRADE_C:
        return "C"
    if score >= GRADE_D:
        return "D"
    return "F"


def grade_badge(score):
    """Return an HTML <span> pill showing letter grade and numeric score."""
    grade = letter_grade(score)
    if grade in ("A+", "A"):
        bg = "#1a7a1a"
    elif grade in ("B+", "B"):
        bg = "#2266cc"
    elif grade in ("C+", "C"):
        bg = "#cc7700"
    else:
        bg = "#cc2222"
    return (
        f'<span style="background:{bg};color:white;border-radius:4px;'
        f'font-weight:bold;font-size:12px;padding:2px 6px">{grade} {score:.1f}</span>'
    )


def row_bg(rating):
    """Table row background color keyed by a 0–100 rating."""
    if rating >= 70:
        return "#f0fff0"
    if rating >= 50:
        return "#fffff0"
    return "white"


def score_color(val):
    """CSS color for a generic 0–100 score (green / orange / red)."""
    if val is None:
        return "#888"
    v = float(val)
    if v >= 70:
        return "#1a7a1a"
    if v >= 40:
        return "#cc7700"
    return "#cc2222"


# ---------------------------------------------------------------------------
# Injury
# ---------------------------------------------------------------------------

def injury_label(val):
    """Return a human-readable durability tier label, or '—' if unknown."""
    if val is None:
        return "—"
    v = int(val)
    if v <= INJURY_IRON_MAN_MAX:
        return "Iron Man"
    if v <= INJURY_DURABLE_MAX:
        return "Durable"
    if v <= INJURY_NORMAL_MAX:
        return "Normal"
    if v <= INJURY_FRAGILE_MAX:
        return "Fragile"
    return "Wrecked"


def injury_color(val):
    """CSS color for a durability rating (green = durable, red = fragile)."""
    if val is None:
        return "#888"
    v = int(val)
    if v <= INJURY_DURABLE_MAX:
        return "#1a7a1a"
    if v <= INJURY_NORMAL_MAX:
        return "#cc7700"
    return "#cc2222"


# ---------------------------------------------------------------------------
# Personality traits (work ethic, intelligence, adaptability)
# ---------------------------------------------------------------------------

def trait_label(val):
    """Return a tier label for a personality trait, or '—' if unknown."""
    if val is None:
        return "—"
    v = int(val)
    if v <= TRAIT_POOR_MAX:
        return "Very Low"
    if v <= TRAIT_BELOW_AVG_MAX:
        return "Low"
    if v <= TRAIT_AVERAGE_MAX:
        return "Average"
    if v <= TRAIT_GOOD_MAX:
        return "High"
    return "Elite"


def trait_color(val, invert=False):
    """CSS color for a personality trait.

    invert=True reverses the scale (green = low), for traits where low is good
    (e.g. greed).
    """
    if val is None:
        return "#888"
    v = int(val)
    if invert:
        if v <= TRAIT_BELOW_AVG_MAX:
            return "#1a7a1a"
        if v <= TRAIT_AVERAGE_MAX:
            return "#cc7700"
        return "#cc2222"
    if v >= TRAIT_GOOD_MAX:
        return "#1a7a1a"
    if v >= TRAIT_BELOW_AVG_MAX:
        return "#cc7700"
    return "#cc2222"


# ---------------------------------------------------------------------------
# Greed (separate scale from traits)
# ---------------------------------------------------------------------------

def greed_label(val):
    """Return a greed tier label (Low / Average / High / Demanding)."""
    if val is None:
        return "Unknown"
    v = int(val)
    if v < GREED_LOW_MAX:
        return "Low"
    if v <= GREED_AVERAGE_MAX:
        return "Average"
    if v <= GREED_HIGH_MAX:
        return "High"
    return "Demanding"


def greed_color(val):
    """CSS color for greed (green = low greed, red = demanding)."""
    if val is None:
        return "#888"
    v = int(val)
    if v < GREED_LOW_MAX:
        return "#1a7a1a"
    if v <= GREED_AVERAGE_MAX:
        return "#cc7700"
    if v <= GREED_HIGH_MAX:
        return "#cc5500"
    return "#cc2222"


# ---------------------------------------------------------------------------
# Salary / contract helpers
# ---------------------------------------------------------------------------

def fmt_salary(val):
    """Format a raw salary integer into a human-readable string ($XM / $XK / $X)."""
    if val is None or val == 0:
        return "—"
    v = int(val)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v}"


def get_current_salary(d):
    """Extract current-year salary from a contract row dict (salary0…salary9)."""
    cy = int(d.get("current_year") or 0)
    key = f"salary{min(cy, 9)}"
    return d.get(key)


def get_years_remaining(d):
    """Return years left on contract (never negative)."""
    years = int(d.get("years") or 0)
    current_year = int(d.get("current_year") or 0)
    return max(0, years - current_year)


def arb_status_label(service_years):
    """Return arbitration status label based on MLB service years."""
    if service_years is None:
        return "Unknown"
    sy = float(service_years)
    if sy < 3:
        return "Pre-Arb"
    if sy < 6:
        arb_num = min(int(sy) - 2, 3)
        return f"Arb Yr {arb_num}"
    return "FA Eligible"
