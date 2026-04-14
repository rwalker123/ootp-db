#!/usr/bin/env python3
"""Free agent search report generator for OOTP Baseball."""

import json
import re
from datetime import datetime
from pathlib import Path

from ootp_db_constants import MLB_LEAGUE_ID, POS_MAP, BATS_MAP, THROWS_MAP
from report_formatting import (
    grade_badge,
    greed_color,
    greed_label,
    injury_color,
    injury_label,
    letter_grade,
    row_bg,
)
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


def query_free_agents(save_name, criteria_label, where_clause, join_clause="",
                       order_by="pr.rating_overall DESC", limit=25, highlight=None):
    """Query free agents matching the given criteria.

    criteria_label is accepted for API consistency but not used in the query itself.
    Returns a list of result dicts.
    """
    engine = get_engine(save_name)
    where_clause = where_clause or "1=1"

    sql = f"""
        SELECT pr.player_id, pr.first_name, pr.last_name, pr.position,
               pr.age, pr.oa, pr.pot, pr.player_type,
               pr.rating_overall, pr.wrc_plus, pr.war,
               pr.rating_offense, pr.rating_contact_quality, pr.rating_discipline,
               pr.rating_defense, pr.rating_potential,
               pr.rating_durability, pr.rating_development, pr.rating_clubhouse,
               pr.flag_injury_risk, pr.flag_leader, pr.flag_high_ceiling,
               pr.prone_overall, pr.work_ethic, pr.intelligence, pr.greed, pr.loyalty,
               p.bats, p.throws,
               pr.confidence
        FROM player_ratings pr
        JOIN players p ON p.player_id = pr.player_id
        {join_clause}
        WHERE p.free_agent = 1 AND p.retired = 0
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
            age=r[4], oa=r[5], pot=r[6], player_type=r[7],
            rating_overall=r[8], wrc_plus=r[9], war=r[10],
            rating_offense=r[11], rating_contact_quality=r[12], rating_discipline=r[13],
            rating_defense=r[14], rating_potential=r[15],
            rating_durability=r[16], rating_development=r[17], rating_clubhouse=r[18],
            flag_injury_risk=r[19], flag_leader=r[20], flag_high_ceiling=r[21],
            prone_overall=r[22], work_ethic=r[23], intelligence=r[24],
            greed=r[25], loyalty=r[26], bats=r[27], throws=r[28],
            confidence=r[29],
        ))
    return results


def generate_free_agents_report(save_name, criteria_label, where_clause,
                                 join_clause="", order_by="pr.rating_overall DESC",
                                 limit=25, highlight=None):
    """Generate a free agent search results HTML report.

    Always regenerates — no caching, criteria vary per search.

    highlight: list of (col_key, display_label) tuples for extra stat columns,
               e.g. [("rating_defense", "Defense"), ("rating_potential", "Potential")]

    Returns (path_str, results_list) where results_list is list of dicts.
    """
    last_import = get_last_import_iso_for_save(save_name)
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    results = query_free_agents(save_name, criteria_label, where_clause, join_clause,
                                 order_by, limit, highlight)

    args_key = {"criteria": criteria_label}

    # Build results table rows
    table_rows = ""
    for i, r in enumerate(results, 1):
        pos = r["position"]
        pos_name = POS_MAP.get(pos, str(pos))
        is_pitcher = r["player_type"] == "pitcher"
        key_stat = (f"{r['wrc_plus']:.2f}" if is_pitcher and r["wrc_plus"] is not None
                    else str(int(r["wrc_plus"])) if r["wrc_plus"] is not None else "—")
        key_label = "FIP" if is_pitcher else "wRC+"
        war_disp = f"{float(r['war']):.1f}" if r["war"] is not None else "—"
        conf = float(r["confidence"]) if r.get("confidence") is not None else 0.0
        conf_color = "#1a7a1a" if conf >= 0.9 else "#cc7700" if conf >= 0.5 else "#cc2222"
        prone_v = r["prone_overall"]
        greed_v = r["greed"]
        we_v = r["work_ethic"] or 0
        iq_v = r["intelligence"] or 0
        rating = r["rating_overall"] or 0

        flags = ""
        if r["flag_leader"]:
            flags += '<span title="Leader — positive clubhouse presence">🏆</span> '
        if r["flag_high_ceiling"]:
            flags += '<span title="High Ceiling — significant upside remaining">📈</span> '
        if we_v > 160:
            flags += '<span title="Elite Work Ethic — likely to develop and maintain skills">⚡</span> '
        if iq_v > 160:
            flags += '<span title="High Baseball IQ — reads the game well, adjusts quickly">🧠</span>'

        def _fmt_score(val):
            if val is None:
                return "<td>—</td>"
            v = float(val)
            color = "#1a7a1a" if v >= 70 else "#cc7700" if v >= 40 else "#cc2222"
            return f'<td style="font-weight:bold;color:{color}">{v:.1f}</td>'

        extra_cells = "".join(_fmt_score(r.get(col)) for col, _ in (highlight or []))

        bg = row_bg(rating)
        table_rows += (
            f'<tr style="background:{bg}">'
            f'<td>{i}</td>'
            f'<td class="left"><b>{r["first_name"]} {r["last_name"]}</b></td>'
            f'<td>{pos_name}</td>'
            f'<td>{int(r["age"]) if r["age"] else "?"}</td>'
            f'<td>{grade_badge(rating)}</td>'
            f'<td style="font-weight:bold;color:{conf_color}">{conf:.0%}</td>'
            f'{extra_cells}'
            f'<td>{key_stat}</td>'
            f'<td>{war_disp}</td>'
            f'<td style="color:{injury_color(prone_v)};font-weight:bold">{injury_label(prone_v)}</td>'
            f'<td style="color:{greed_color(greed_v)};font-weight:bold">{greed_label(greed_v)}</td>'
            f'<td>{flags}</td>'
            f'</tr>\n'
        )

    # Personality spotlight section
    spotlight = ""
    elite_we = [r for r in results if (r["work_ethic"] or 0) > 160]
    elite_iq = [r for r in results if (r["intelligence"] or 0) > 160]
    high_greed = [r for r in results if (r["greed"] or 0) > 160]

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
            f'<b>⚠ Demanding Greed:</b> {names} — contract negotiations will be difficult.</div>'
        )

    key_header = "FIP" if (results and results[0]["player_type"] == "pitcher") else "wRC+"
    extra_headers = "".join(f"<th>{label}</th>" for _, label in (highlight or []))

    _ootp_kwargs_esc = json.dumps(dict(
        where_clause=where_clause, join_clause=join_clause,
        order_by=order_by, limit=limit, highlight=highlight
    )).replace('"', '&quot;')
    _args_esc = criteria_label.replace('&', '&amp;').replace('"', '&quot;')
    _ootp_meta = (
        '<meta name="ootp-skill" content="free-agents">'
        f'<meta name="ootp-args" content="{_args_esc}">'
        f'<meta name="ootp-args-display" content="{_args_esc}">'
        f'<meta name="ootp-save" content="{save_name}">'
        f'<meta name="ootp-kwargs" content="{_ootp_kwargs_esc}">'
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Free Agent Search - {criteria_label}</title>
{_ootp_meta}
<style>{get_report_css("1100px")}</style></head><body>
<div class="container">

<div class="page-header">
  <div class="player-name">Free Agent Search</div>
  <div class="player-meta">{criteria_label}</div>
  <div class="import-ts">{len(results)} result{"s" if len(results) != 1 else ""} &bull; Last DB import: {last_import or "unknown"} &bull; Generated: {generated_at}</div>
</div>

<div class="section">
<!-- ANALYSIS:START --><!-- FA_CALLOUT_SUMMARY --><!-- ANALYSIS:END -->
</div>

<div class="section">
  <div class="section-title">Results</div>
  <table>
  <tr>
  <th>#</th><th class="left">Name</th><th>Pos</th><th>Age</th>
  <th>Rating</th><th>Conf</th>{extra_headers}<th>{key_header}</th><th>WAR</th><th>Injury</th><th>Greed</th><th>Flags</th>
  </tr>
  {table_rows}
  </table>
</div>

{spotlight}

<div style="font-size:12px;color:#888;margin:8px 16px 16px;line-height:1.8">
  <b>Flag legend:</b>&nbsp;
  🏆 Leader &nbsp;&bull;&nbsp;
  📈 High Ceiling &nbsp;&bull;&nbsp;
  ⚡ Elite Work Ethic &nbsp;&bull;&nbsp;
  🧠 High Baseball IQ
</div>

</div>
</body></html>"""

    report_path = get_reports_dir(save_name, "free_agents") / report_filename("free_agents", args_key)
    write_report_html(report_path, html)

    return str(report_path), results
