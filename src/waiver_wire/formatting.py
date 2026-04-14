"""Pure helper/formatter/color functions for the waiver wire evaluator."""

from config import (
    INJURY_IRON_MAN_MAX, INJURY_DURABLE_MAX, INJURY_NORMAL_MAX, INJURY_FRAGILE_MAX,
    TRAIT_POOR_MAX, TRAIT_BELOW_AVG_MAX, TRAIT_AVERAGE_MAX, TRAIT_GOOD_MAX,
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


def get_current_salary(row_dict):
    cy = int(row_dict.get("current_year") or 0)
    key = f"salary{min(cy, 9)}"
    return row_dict.get(key)


def get_years_remaining(row_dict):
    years = int(row_dict.get("years") or 0)
    current_year = int(row_dict.get("current_year") or 0)
    return max(0, years - current_year)


def letter_grade(score):
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C+"
    if score >= 40:
        return "C"
    if score >= 30:
        return "D"
    return "F"


def grade_badge(score):
    grade = letter_grade(score)
    bg = (
        "#1a7a1a" if grade in ("A+", "A")
        else "#2266cc" if grade in ("B+", "B")
        else "#cc7700" if grade in ("C+", "C")
        else "#cc2222"
    )
    return (
        f'<span style="background:{bg};color:white;border-radius:4px;'
        f'font-weight:bold;font-size:12px;padding:2px 6px">{grade} {score:.1f}</span>'
    )


def score_color(val):
    if val is None:
        return "#888"
    v = float(val)
    if v >= 70:
        return "#1a7a1a"
    if v >= 40:
        return "#cc7700"
    return "#cc2222"


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


def arb_status_label(service_years):
    if service_years is None:
        return "Unknown"
    sy = float(service_years)
    if sy < 3:
        return "Pre-Arb"
    if sy < 6:
        arb_num = min(int(sy) - 2, 3)
        return f"Arb Yr {arb_num}"
    return "FA Eligible"


def _score_td(val):
    if val is None:
        return "<td>—</td>"
    v = float(val)
    c = score_color(v)
    return f'<td style="font-weight:bold;color:{c}">{v:.0f}</td>'


def _war_td(val):
    if val is None:
        return "<td>—</td>"
    v = float(val)
    c = "#1a7a1a" if v >= 3 else "#cc7700" if v >= 1 else "#cc2222"
    return f'<td style="font-weight:bold;color:{c}">{v:.1f}</td>'


def _fmt_pct(val):
    if val is None:
        return "—"
    return f"{float(val) * 100:.1f}%"
