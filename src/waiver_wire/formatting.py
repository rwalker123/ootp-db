"""Pure helper/formatter/color functions for the waiver wire evaluator."""

from report_formatting import (
    arb_status_label,
    fmt_salary,
    get_current_salary,
    get_years_remaining,
    grade_badge,
    injury_color,
    injury_label,
    letter_grade,
    score_color,
    trait_label,
)

__all__ = [
    "arb_status_label",
    "fmt_salary",
    "get_current_salary",
    "get_years_remaining",
    "grade_badge",
    "injury_color",
    "injury_label",
    "letter_grade",
    "score_color",
    "trait_label",
]


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
