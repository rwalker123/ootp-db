"""Pure formatting helpers for the contract extension advisor."""

from config import (
    GRADE_A_PLUS, GRADE_A, GRADE_B_PLUS, GRADE_B, GRADE_C_PLUS, GRADE_C, GRADE_D,
    INJURY_IRON_MAN_MAX, INJURY_DURABLE_MAX, INJURY_NORMAL_MAX, INJURY_FRAGILE_MAX,
    TRAIT_POOR_MAX, TRAIT_BELOW_AVG_MAX, TRAIT_AVERAGE_MAX, TRAIT_GOOD_MAX,
)


def letter_grade(score):
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


def fmt_salary(val):
    if val is None or val == 0:
        return "—"
    v = int(val)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v}"


def injury_label(val):
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
    if val is None:
        return "#888"
    v = int(val)
    if v <= INJURY_DURABLE_MAX:
        return "#1a7a1a"
    if v <= INJURY_NORMAL_MAX:
        return "#cc7700"
    return "#cc2222"


def trait_label(val):
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
    """Green=high by default; invert=True means green=low (e.g. greed)."""
    if val is None:
        return "#888"
    v = int(val)
    if invert:
        if v <= INJURY_DURABLE_MAX:
            return "#1a7a1a"
        if v <= INJURY_NORMAL_MAX:
            return "#cc7700"
        return "#cc2222"
    else:
        if v >= TRAIT_GOOD_MAX:
            return "#1a7a1a"
        if v >= TRAIT_BELOW_AVG_MAX:
            return "#cc7700"
        return "#cc2222"


def pop_label(val):
    if val is None:
        return "—"
    v = max(0, min(6, int(val)))
    labels = (
        "None",
        "Below Avg",
        "Average",
        "Notable",
        "Popular",
        "Star",
        "Icon",
    )
    return labels[v]


def pop_color(val):
    if val is None:
        return "#888"
    v = int(val)
    if v >= 5:
        return "#1a7a1a"
    if v >= 3:
        return "#f0c040"
    return "#888"


def arb_status_label(service_years):
    if service_years is None:
        return "Unknown"
    sy = float(service_years)
    if sy < 3:
        return "Pre-Arbitration"
    if sy < 6:
        arb_num = min(int(sy) - 2, 3)
        return f"Arbitration Yr {arb_num}"
    return "FA Eligible (Under Contract)"


def safe_div(n, d):
    return n / d if d and float(d) != 0 else None


def get_current_salary(d):
    cy = int(d.get("current_year") or 0)
    key = f"salary{min(cy, 9)}"
    return d.get(key)


def get_years_remaining(d):
    years = int(d.get("years") or 0)
    current_year = int(d.get("current_year") or 0)
    return max(0, years - current_year)


def _fmt_score_cell(val):
    if val is None:
        return "<td>—</td>"
    v = float(val)
    color = "#1a7a1a" if v >= 70 else "#cc7700" if v >= 40 else "#cc2222"
    return f'<td style="font-weight:bold;color:{color}">{v:.1f}</td>'


def _f1(val):
    return f"{float(val):.1f}" if val is not None else "—"


def _f2(val):
    return f"{float(val):.2f}" if val is not None else "—"


def _f3(val):
    return f"{float(val):.3f}" if val is not None else "—"


def _pct(val):
    """Format a 0–1 float as a percentage string, or '—'."""
    if val is None:
        return "—"
    return f"{float(val) * 100:.1f}%"


def _ev_color(val, pitcher=False):
    """Color for exit velocity — green=good, red=bad. Inverted for pitcher (low EV allowed = good)."""
    if val is None:
        return "#888"
    v = float(val)
    if pitcher:
        return "#1a7a1a" if v < 88 else "#cc7700" if v < 91 else "#cc2222"
    return "#1a7a1a" if v >= 92 else "#cc7700" if v >= 88 else "#cc2222"


def _pct_color(val, good_high=True, good_thresh=0.45, avg_thresh=0.32):
    """Color for percentage metrics. good_high=True means higher is better."""
    if val is None:
        return "#888"
    v = float(val)
    if good_high:
        return "#1a7a1a" if v >= good_thresh else "#cc7700" if v >= avg_thresh else "#cc2222"
    # lower is better (e.g. hard_hit% allowed)
    return "#1a7a1a" if v <= avg_thresh else "#cc7700" if v <= good_thresh else "#cc2222"


def _xwoba_color(val, pitcher=False):
    if val is None:
        return "#888"
    v = float(val)
    if pitcher:
        return "#1a7a1a" if v < 0.290 else "#cc7700" if v < 0.340 else "#cc2222"
    return "#1a7a1a" if v >= 0.360 else "#cc7700" if v >= 0.300 else "#cc2222"
