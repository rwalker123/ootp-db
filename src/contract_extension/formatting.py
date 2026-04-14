"""Pure formatting helpers for the contract extension advisor."""

from report_formatting import (
    arb_status_label,
    fmt_salary,
    get_current_salary,
    get_years_remaining,
    grade_badge,
    injury_color,
    injury_label,
    letter_grade,
    trait_color,
    trait_label,
)


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


def safe_div(n, d):
    return n / d if d and float(d) != 0 else None


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
