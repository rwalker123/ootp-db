"""Display and HTML formatting helpers for lineup optimizer reports."""

import html as html_mod

from ootp_db_constants import BATS_MAP


def letter_grade(score):
    for threshold, grade in ((90, "A+"), (80, "A"), (70, "B+"), (60, "B"), (50, "C+"), (40, "C"), (30, "D")):
        if score >= threshold:
            return grade
    return "F"


def grade_color(score):
    if score >= 70: return "#1a7a1a"
    if score >= 50: return "#2266cc"
    if score >= 40: return "#cc7700"
    return "#cc2222"


def woba_color(val):
    if val is None: return "#888"
    if val >= 0.360: return "#1a7a1a"
    if val >= 0.320: return "#cc7700"
    return "#cc2222"


def wrc_color(val):
    if val is None: return "#888"
    if val >= 115: return "#1a7a1a"
    if val >= 85: return "#cc7700"
    return "#cc2222"


def fmt_woba(val):
    return f"{val:.3f}" if val is not None else "—"


def fmt_int(val):
    return str(int(val)) if val is not None else "—"


def _fatigue_color(val):
    if val is None or val == 0:
        return "#aaa"
    if val >= 70: return "#cc2222"
    if val >= 40: return "#cc7700"
    return "#1a7a1a"


def temp_emoji(flag):
    """Inline emoji badge appended to player name — replaces the old Temp column."""
    emojis = dict(
        hot_extreme=' 🔥🔥',
        hot=' 🔥',
        cold=' 🧊',
        cold_extreme=' 🧊🧊',
        neutral='',
    )
    return emojis.get(flag, '')


def handedness_pattern(lineup):
    return "-".join(BATS_MAP.get(lineup[s].get("bats") or 1, "?") for s in range(1, 10) if s in lineup)


def iso_td(val):
    if val is None:
        return "<td>—</td>"
    if val >= 0.200: c = "#1a7a1a"
    elif val >= 0.120: c = "#cc7700"
    else: c = "#cc2222"
    return f'<td style="color:{c};font-weight:bold">{val:.3f}</td>'


def woba_td(val):
    if val is None:
        return "<td>—</td>"
    c = woba_color(val)
    return f'<td style="color:{c};font-weight:bold">{val:.3f}</td>'


def wrc_td(val):
    if val is None:
        return "<td>—</td>"
    c = wrc_color(val)
    return f'<td style="color:{c};font-weight:bold">{int(val)}</td>'
