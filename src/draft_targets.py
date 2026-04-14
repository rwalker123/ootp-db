#!/usr/bin/env python3
"""Draft prospect search report generator for OOTP Baseball."""

import json
import re
from datetime import datetime
from pathlib import Path

from config import (
    GRADE_A_PLUS, GRADE_A, GRADE_B_PLUS, GRADE_B, GRADE_C_PLUS, GRADE_C, GRADE_D,
    TRAIT_POOR_MAX, TRAIT_BELOW_AVG_MAX, TRAIT_AVERAGE_MAX, TRAIT_GOOD_MAX,
    GREED_LOW_MAX, GREED_AVERAGE_MAX, GREED_HIGH_MAX,
)
from ootp_db_constants import POS_MAP, BATS_MAP, THROWS_MAP, NATION_USA
from report_write import write_report_html, report_filename
from shared_css import (
    db_name_from_save,
    get_engine,
    get_last_import_iso_for_save,
    get_report_css,
    get_reports_dir,
)
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def greed_label(val):
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
    return (f'<span style="background:{bg};color:white;border-radius:4px;'
            f'font-weight:bold;font-size:12px;padding:2px 6px">{grade} {score:.1f}</span>')


def row_bg(rating):
    if rating >= 70:
        return "#f0fff0"
    if rating >= 50:
        return "#fffff0"
    return "white"


def generate_draft_targets_report(save_name, criteria_label, where_clause,
                                   order_by="dr.rating_overall DESC", limit=25):
    """Generate a draft prospect search HTML report.

    Always regenerates — no caching, criteria vary per search.

    Returns (path_str, results_list) where results_list is list of dicts.
    """
    engine = get_engine(save_name)
    last_import = get_last_import_iso_for_save(save_name)
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    where_clause = where_clause or "1=1"

    sql = f"""
        SELECT dr.player_id, dr.first_name, dr.last_name, dr.position, dr.age,
               dr.player_type, dr.bats, dr.throws, dr.college, dr.domestic,
               dr.oa, dr.pot, dr.rating_overall,
               dr.rating_ceiling, dr.rating_tools, dr.rating_development,
               dr.rating_defense, dr.rating_proximity,
               dr.flag_elite_ceiling, dr.flag_high_ceiling,
               dr.flag_elite_we, dr.flag_elite_iq, dr.flag_demanding,
               dr.flag_international, dr.flag_hs,
               dr.work_ethic, dr.intelligence, dr.greed
        FROM draft_ratings dr
        JOIN players p ON p.player_id = dr.player_id
        WHERE p.picked_in_draft = 0
          AND {where_clause}
        ORDER BY {order_by}
        LIMIT {limit}
    """

    with engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()

    results = []
    for r in rows:
        results.append(dict(
            player_id=r[0], first_name=r[1], last_name=r[2], position=r[3],
            age=r[4], player_type=r[5], bats=r[6], throws=r[7],
            college=r[8], domestic=r[9], oa=r[10], pot=r[11],
            rating_overall=r[12], rating_ceiling=r[13], rating_tools=r[14],
            rating_development=r[15], rating_defense=r[16], rating_proximity=r[17],
            flag_elite_ceiling=r[18], flag_high_ceiling=r[19],
            flag_elite_we=r[20], flag_elite_iq=r[21], flag_demanding=r[22],
            flag_international=r[23], flag_hs=r[24],
            work_ethic=r[25], intelligence=r[26], greed=r[27],
        ))

    args_key = {"criteria": criteria_label}

    # Build results table rows
    table_rows = ""
    for i, r in enumerate(results, 1):
        pos_name = POS_MAP.get(r["position"], str(r["position"]))
        bats_str = BATS_MAP.get(r["bats"] or 0, "?")
        throws_str = THROWS_MAP.get(r["throws"] or 0, "?")
        oa_v = int(r["oa"]) if r["oa"] is not None else 0
        pot_v = int(r["pot"]) if r["pot"] is not None else 0
        rating = r["rating_overall"] or 0
        we_v = r["work_ethic"] or 0
        iq_v = r["intelligence"] or 0
        greed_v = r["greed"]
        t_val = r["rating_tools"] or 0
        d_val = r["rating_development"] or 0

        col_label = (
            '<span style="background:#1a7a1a;color:white;border-radius:3px;'
            'padding:1px 5px;font-size:11px">COL</span>'
            if r["college"]
            else '<span style="background:#cc7700;color:white;border-radius:3px;'
            'padding:1px 5px;font-size:11px">HS</span>'
        )
        dom_label = (
            "DOM"
            if r["domestic"]
            else '<span style="background:#7733cc;color:white;border-radius:3px;'
            'padding:1px 5px;font-size:11px">INTL</span>'
        )

        flags = ""
        if r["flag_elite_ceiling"]:
            flags += "🌟 "
        elif r["flag_high_ceiling"]:
            flags += "⬆ "
        if r["flag_elite_we"]:
            flags += "⚡"
        if r["flag_elite_iq"]:
            flags += "🧠"
        if r["flag_demanding"]:
            flags += "💰"

        def _fmt_score(v):
            color = "#1a7a1a" if v >= 70 else "#cc7700" if v >= 40 else "#cc2222"
            return f'<td style="font-weight:bold;color:{color}">{v:.1f}</td>'

        bg = row_bg(rating)
        table_rows += (
            f'<tr style="background:{bg}">'
            f'<td>{i}</td>'
            f'<td class="left"><b>{r["first_name"]} {r["last_name"]}</b></td>'
            f'<td>{pos_name}</td>'
            f'<td>{int(r["age"]) if r["age"] else "?"}</td>'
            f'<td>{oa_v}/{pot_v}</td>'
            f'<td>{grade_badge(rating)}</td>'
            f'<td>{bats_str}/{throws_str}</td>'
            f'<td>{col_label}</td>'
            f'<td>{dom_label}</td>'
            f'{_fmt_score(t_val)}'
            f'{_fmt_score(d_val)}'
            f'<td style="color:{greed_color(greed_v)};font-weight:bold">{greed_label(greed_v)}</td>'
            f'<td>{flags}</td>'
            f'</tr>\n'
        )

    # Personality spotlight section
    spotlight = ""
    elite_we = [r for r in results if (r["work_ethic"] or 0) > TRAIT_GOOD_MAX]
    elite_iq = [r for r in results if (r["intelligence"] or 0) > TRAIT_GOOD_MAX]
    high_greed = [r for r in results if (r["greed"] or 0) > GREED_HIGH_MAX]

    if elite_we or elite_iq:
        names = ", ".join(
            f"{r['first_name']} {r['last_name']}"
            for r in (elite_we + [r for r in elite_iq if r not in elite_we])
        )
        spotlight += (
            f'<div style="background:#f0fff0;border:1px solid #88cc88;padding:10px 14px;'
            f'border-radius:4px;margin:8px 0;font-size:13px">'
            f'<b>⚡🧠 Elite Work Ethic / High IQ:</b> {names}</div>'
        )
    if high_greed:
        names = ", ".join(f"{r['first_name']} {r['last_name']}" for r in high_greed)
        spotlight += (
            f'<div style="background:#fff0f0;border:1px solid #cc8888;padding:10px 14px;'
            f'border-radius:4px;margin:8px 0;font-size:13px">'
            f'<b>💰 Above-Slot Risk:</b> {names} — may require above-slot bonus to sign.</div>'
        )

    _ootp_kwargs_esc = json.dumps(dict(
        where_clause=where_clause, order_by=order_by, limit=limit
    )).replace('"', '&quot;')
    _args_esc = criteria_label.replace('&', '&amp;').replace('"', '&quot;')
    _ootp_meta = (
        '<meta name="ootp-skill" content="draft-targets">'
        f'<meta name="ootp-args" content="{_args_esc}">'
        f'<meta name="ootp-args-display" content="{_args_esc}">'
        f'<meta name="ootp-save" content="{save_name}">'
        f'<meta name="ootp-kwargs" content="{_ootp_kwargs_esc}">'
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Draft Targets - {criteria_label}</title>
{_ootp_meta}
<style>{get_report_css("1100px")}</style></head><body>
<div class="container">

<div class="page-header">
  <div class="player-name">Draft Prospect Search</div>
  <div class="player-meta">{criteria_label}</div>
  <div class="import-ts">{len(results)} result{"s" if len(results) != 1 else ""} &bull; Last DB import: {last_import or "unknown"} &bull; Generated: {generated_at}</div>
  <div class="import-ts">Note: greed is a proxy for signing demands (slot value not exported from OOTP)</div>
</div>

<div class="section">
<!-- ANALYSIS:START --><!-- FA_CALLOUT_SUMMARY --><!-- ANALYSIS:END -->
</div>

<div class="section">
  <div class="section-title">Results</div>
  <table>
  <tr>
  <th>#</th><th class="left">Name</th><th>Pos</th><th>Age</th><th>OA/POT</th>
  <th>Rating</th><th>B/T</th><th>Type</th><th>Orig</th>
  <th>Tools</th><th>Dev</th><th>Greed</th><th>Flags</th>
  </tr>
  {table_rows}
  </table>
</div>

{spotlight}

<div class="section" style="font-size:11px;color:#888">
  <b>Flags:</b> 🌟 Elite Ceiling (POT≥65) &nbsp; ⬆ High Ceiling (POT≥55) &nbsp;
  ⚡ Elite Work Ethic &nbsp; 🧠 High IQ &nbsp; 💰 Demanding (above-slot risk)<br>
  <b>Rating components:</b> Ceiling 35% &bull; Tools/Stuff 30% &bull; Development 20% &bull; Defense/Command 10% &bull; Proximity 5%
</div>

</div>
</body></html>"""

    report_path = get_reports_dir(save_name, "draft") / report_filename("draft", args_key)
    write_report_html(report_path, html)

    return str(report_path), results
