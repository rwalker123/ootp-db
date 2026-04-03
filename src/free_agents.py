#!/usr/bin/env python3
"""Free agent search report generator for OOTP Baseball."""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from shared_css import db_name_from_save, get_report_css, get_reports_dir
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAST_IMPORT_PATH = PROJECT_ROOT / ".last_import"


def get_engine(save_name):
    env_path = PROJECT_ROOT / ".env"
    load_dotenv(env_path)
    postgres_host = os.getenv("POSTGRES_URL")
    if not postgres_host:
        print("Error: POSTGRES_URL not set in .env")
        sys.exit(1)
    db_name = db_name_from_save(save_name)
    return create_engine(f"{postgres_host.rstrip('/')}/{db_name}")


def get_last_import_time():
    if LAST_IMPORT_PATH.exists():
        return LAST_IMPORT_PATH.read_text().strip()
    return None


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


POS_MAP = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
BATS_MAP = {1: "R", 2: "L", 3: "S"}
THROWS_MAP = {1: "R", 2: "L"}


def injury_label(val):
    if val is None:
        return "Unknown"
    v = int(val)
    if v <= 25:
        return "Iron Man"
    if v <= 75:
        return "Durable"
    if v <= 125:
        return "Normal"
    if v <= 174:
        return "Fragile"
    return "Wrecked"


def injury_color(val):
    if val is None:
        return "#888"
    v = int(val)
    if v <= 75:
        return "#1a7a1a"
    if v <= 125:
        return "#cc7700"
    return "#cc2222"


def greed_label(val):
    if val is None:
        return "Unknown"
    v = int(val)
    if v < 80:
        return "Low"
    if v <= 130:
        return "Average"
    if v <= 160:
        return "High"
    return "Demanding"


def greed_color(val):
    if val is None:
        return "#888"
    v = int(val)
    if v < 80:
        return "#1a7a1a"
    if v <= 130:
        return "#cc7700"
    if v <= 160:
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


def generate_free_agents_report(save_name, criteria_label, where_clause,
                                 join_clause="", order_by="pr.rating_overall DESC",
                                 limit=25, highlight=None):
    """Generate a free agent search results HTML report.

    Always regenerates — no caching, criteria vary per search.

    highlight: list of (col_key, display_label) tuples for extra stat columns,
               e.g. [("rating_defense", "Defense"), ("rating_potential", "Potential")]

    Returns (path_str, results_list) where results_list is list of dicts.
    """
    engine = get_engine(save_name)
    last_import = get_last_import_time()
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    sql = f"""
        SELECT pr.player_id, pr.first_name, pr.last_name, pr.position,
               pr.age, pr.oa, pr.pot, pr.player_type,
               pr.rating_overall, pr.wrc_plus, pr.war,
               pr.rating_offense, pr.rating_contact_quality, pr.rating_discipline,
               pr.rating_defense, pr.rating_potential,
               pr.rating_durability, pr.rating_development, pr.rating_clubhouse,
               pr.flag_injury_risk, pr.flag_leader, pr.flag_high_ceiling,
               pr.prone_overall, pr.work_ethic, pr.intelligence, pr.greed, pr.loyalty,
               p.bats, p.throws
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
        ))

    # Build slug from criteria
    slug = re.sub(r"[^a-z0-9_]", "", criteria_label.lower().replace(" ", "_"))[:50]

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
        oa_v = int(r["oa"]) if r["oa"] is not None else 0
        pot_v = int(r["pot"]) if r["pot"] is not None else 0
        prone_v = r["prone_overall"]
        greed_v = r["greed"]
        we_v = r["work_ethic"] or 0
        iq_v = r["intelligence"] or 0
        rating = r["rating_overall"] or 0

        flags = ""
        if r["flag_leader"]:
            flags += "🏆 "
        if r["flag_high_ceiling"]:
            flags += "📈 "
        if we_v > 160:
            flags += "⚡ "
        if iq_v > 160:
            flags += "🧠"

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
            f'<td>{oa_v}/{pot_v}</td>'
            f'<td>{grade_badge(rating)}</td>'
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
  <th>#</th><th class="left">Name</th><th>Pos</th><th>Age</th><th>OA/POT</th>
  <th>Rating</th>{extra_headers}<th>{key_header}</th><th>WAR</th><th>Injury</th><th>Greed</th><th>Flags</th>
  </tr>
  {table_rows}
  </table>
</div>

{spotlight}

</div>
</body></html>"""

    report_path = get_reports_dir(save_name, "free_agents") / f"{slug}.html"
    report_path.write_text(html)

    return str(report_path), results
