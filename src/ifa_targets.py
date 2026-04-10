#!/usr/bin/env python3
"""IFA prospect search report generator for OOTP Baseball."""

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


def generate_ifa_targets_report(save_name, criteria_label, where_clause,
                                 order_by="ir.rating_overall DESC", limit=25):
    """Generate an IFA prospect search HTML report.

    Always regenerates — no caching, criteria vary per search.

    Returns (path_str, results_list) where results_list is list of dicts.
    """
    engine = get_engine(save_name)
    last_import = get_last_import_iso_for_save(save_name)
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    sql = f"""
        SELECT ir.player_id, ir.first_name, ir.last_name, ir.position, ir.age,
               ir.player_type, ir.bats, ir.throws, ir.nation_id, ir.nation,
               ir.oa, ir.pot, ir.rating_overall,
               ir.rating_ceiling, ir.rating_tools, ir.rating_development,
               ir.rating_defense, ir.rating_age,
               ir.flag_elite_ceiling, ir.flag_high_ceiling,
               ir.flag_elite_we, ir.flag_elite_iq, ir.flag_demanding,
               ir.flag_prime_age,
               ir.work_ethic, ir.intelligence, ir.greed
        FROM ifa_ratings ir
        WHERE {where_clause}
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
            nation_id=r[8], nation=r[9], oa=r[10], pot=r[11],
            rating_overall=r[12], rating_ceiling=r[13], rating_tools=r[14],
            rating_development=r[15], rating_defense=r[16], rating_age=r[17],
            flag_elite_ceiling=r[18], flag_high_ceiling=r[19],
            flag_elite_we=r[20], flag_elite_iq=r[21], flag_demanding=r[22],
            flag_prime_age=r[23],
            work_ethic=r[24], intelligence=r[25], greed=r[26],
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
        greed_v = r["greed"]
        t_val = r["rating_tools"] or 0
        d_val = r["rating_development"] or 0
        age_v = int(r["age"]) if r["age"] else "?"

        nation_str = r["nation"] or "Unknown"

        flags = ""
        if r["flag_elite_ceiling"]:
            flags += "🌟 "
        elif r["flag_high_ceiling"]:
            flags += "⬆ "
        if r["flag_prime_age"]:
            flags += "👶 "
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
            f'<td>{age_v}</td>'
            f'<td>{oa_v}/{pot_v}</td>'
            f'<td>{grade_badge(rating)}</td>'
            f'<td>{bats_str}/{throws_str}</td>'
            f'<td class="left">{nation_str}</td>'
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
    prime_age = [r for r in results if r["flag_prime_age"]]

    if prime_age:
        names = ", ".join(f"{r['first_name']} {r['last_name']}" for r in prime_age)
        spotlight += (
            f'<div style="background:#f0f8ff;border:1px solid #88aacc;padding:10px 14px;'
            f'border-radius:4px;margin:8px 0;font-size:13px">'
            f'<b>👶 Prime Signing Age (16):</b> {names}</div>'
        )
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
        '<meta name="ootp-skill" content="ifa-targets">'
        f'<meta name="ootp-args" content="{_args_esc}">'
        f'<meta name="ootp-args-display" content="{_args_esc}">'
        f'<meta name="ootp-save" content="{save_name}">'
        f'<meta name="ootp-kwargs" content="{_ootp_kwargs_esc}">'
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>IFA Targets - {criteria_label}</title>
{_ootp_meta}
<style>{get_report_css("1100px")}</style></head><body>
<div class="container">

<div class="page-header">
  <div class="player-name">IFA Prospect Search</div>
  <div class="player-meta">{criteria_label}</div>
  <div class="import-ts">{len(results)} result{"s" if len(results) != 1 else ""} &bull; Last DB import: {last_import or "unknown"} &bull; Generated: {generated_at}</div>
  <div class="import-ts">International Amateur Free Agents — signed in January signing period</div>
</div>

<div class="section">
<!-- ANALYSIS:START --><!-- FA_CALLOUT_SUMMARY --><!-- ANALYSIS:END -->
</div>

<div class="section">
  <div class="section-title">Results</div>
  <table>
  <tr>
  <th>#</th><th class="left">Name</th><th>Pos</th><th>Age</th><th>OA/POT</th>
  <th>Rating</th><th>B/T</th><th class="left">Nation</th>
  <th>Tools</th><th>Dev</th><th>Greed</th><th>Flags</th>
  </tr>
  {table_rows}
  </table>
</div>

{spotlight}

<div class="section" style="font-size:11px;color:#888">
  <b>Flags:</b> 🌟 Elite Ceiling (POT≥65) &nbsp; ⬆ High Ceiling (POT≥55) &nbsp;
  👶 Prime Signing Age (16) &nbsp; ⚡ Elite Work Ethic &nbsp; 🧠 High IQ &nbsp; 💰 Demanding (above-slot risk)<br>
  <b>Rating components:</b> Ceiling 35% &bull; Tools/Stuff 30% &bull; Development 20% &bull; Defense/Command 10% &bull; Age 5%
</div>

</div>
</body></html>"""

    report_path = get_reports_dir(save_name, "ifa") / report_filename("ifa", args_key)
    write_report_html(report_path, html)

    return str(report_path), results
