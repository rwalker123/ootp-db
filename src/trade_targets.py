#!/usr/bin/env python3
"""Trade target search report generator for OOTP Baseball."""

import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from report_write import write_report_html
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


def fmt_salary(val):
    if val is None or val == 0:
        return "—"
    v = int(val)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v}"


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


def row_bg(rating):
    if rating >= 70:
        return "#f0fff0"
    if rating >= 50:
        return "#fffff0"
    return "white"


# Column order must match row_to_dict keys below
_SELECT = """
    SELECT pr.player_id, pr.first_name, pr.last_name, pr.position,
           pr.age, pr.oa, pr.pot, pr.player_type,
           pr.rating_overall, pr.wrc_plus, pr.war,
           pr.rating_offense, pr.rating_contact_quality, pr.rating_discipline,
           pr.rating_defense, pr.rating_potential,
           pr.rating_durability, pr.rating_development, pr.rating_clubhouse,
           pr.flag_injury_risk, pr.flag_leader, pr.flag_high_ceiling,
           pr.prone_overall, pr.work_ethic, pr.intelligence, pr.greed,
           p.bats, p.throws,
           t.abbr AS team_abbr,
           pc.years, pc.current_year, pc.no_trade,
           pc.salary0, pc.salary1, pc.salary2, pc.salary3, pc.salary4,
           pc.salary5, pc.salary6, pc.salary7, pc.salary8, pc.salary9,
           prs.mlb_service_years
"""

_FROM = """
    FROM player_ratings pr
    JOIN players p ON p.player_id = pr.player_id
    LEFT JOIN players_contract pc ON pc.player_id = pr.player_id
    LEFT JOIN teams t ON t.team_id = p.team_id
    LEFT JOIN players_roster_status prs ON prs.player_id = pr.player_id
"""

_KEYS = [
    "player_id", "first_name", "last_name", "position",
    "age", "oa", "pot", "player_type",
    "rating_overall", "wrc_plus", "war",
    "rating_offense", "rating_contact_quality", "rating_discipline",
    "rating_defense", "rating_potential",
    "rating_durability", "rating_development", "rating_clubhouse",
    "flag_injury_risk", "flag_leader", "flag_high_ceiling",
    "prone_overall", "work_ethic", "intelligence", "greed",
    "bats", "throws",
    "team_abbr",
    "years", "current_year", "no_trade",
    "salary0", "salary1", "salary2", "salary3", "salary4",
    "salary5", "salary6", "salary7", "salary8", "salary9",
    "mlb_service_years",
]


def row_to_dict(r):
    return dict(zip(_KEYS, r))


def get_current_salary(d):
    """Return the player's salary in the current contract year."""
    cy = int(d.get("current_year") or 0)
    key = f"salary{min(cy, 9)}"
    return d.get(key)


def get_years_remaining(d):
    years = int(d.get("years") or 0)
    current_year = int(d.get("current_year") or 0)
    return years - current_year


def _fmt_score_cell(val):
    if val is None:
        return "<td>—</td>"
    v = float(val)
    color = "#1a7a1a" if v >= 70 else "#cc7700" if v >= 40 else "#cc2222"
    return f'<td style="font-weight:bold;color:{color}">{v:.1f}</td>'


def build_table_header(show_team, key_header, highlight):
    team_col = "<th>Team</th>" if show_team else ""
    extra = "".join(f"<th>{label}</th>" for _, label in (highlight or []))
    return (
        f"<tr><th>#</th><th class='left'>Name</th><th>Pos</th><th>Age</th>"
        f"{team_col}<th>OA/POT</th><th>Rating</th>{extra}"
        f"<th>{key_header}</th><th>WAR</th><th>Salary</th><th>Yrs Left</th>"
        f"<th>Injury</th><th>Flags</th></tr>"
    )


def build_table_rows(results, show_team, highlight):
    html = ""
    for i, r in enumerate(results, 1):
        pos_name = POS_MAP.get(r["position"], str(r["position"]))
        is_pitcher = r["player_type"] == "pitcher"

        wrc_fip = r.get("wrc_plus")
        if is_pitcher:
            key_stat = f"{float(wrc_fip):.2f}" if wrc_fip is not None else "—"
        else:
            key_stat = str(int(wrc_fip)) if wrc_fip is not None else "—"

        war_disp = f"{float(r['war']):.1f}" if r["war"] is not None else "—"
        oa_v = int(r["oa"]) if r["oa"] is not None else 0
        pot_v = int(r["pot"]) if r["pot"] is not None else 0
        rating = float(r["rating_overall"] or 0)

        sal_str = fmt_salary(get_current_salary(r))
        yrs_left = get_years_remaining(r)
        no_trade = r.get("no_trade") or 0
        we_v = r.get("work_ethic") or 0
        iq_v = r.get("intelligence") or 0

        flags = ""
        if r.get("flag_leader"):
            flags += "🏆 "
        if r.get("flag_high_ceiling"):
            flags += "📈 "
        if no_trade:
            flags += "🔒 "
        if we_v > 160:
            flags += "⚡ "
        if iq_v > 160:
            flags += "🧠"

        extra_cells = "".join(_fmt_score_cell(r.get(col)) for col, _ in (highlight or []))
        team_cell = f"<td>{r.get('team_abbr', '')}</td>" if show_team else ""
        bg = row_bg(rating)

        html += (
            f'<tr style="background:{bg}">'
            f"<td>{i}</td>"
            f'<td class="left"><b>{r["first_name"]} {r["last_name"]}</b></td>'
            f"<td>{pos_name}</td>"
            f"<td>{int(r['age']) if r['age'] else '?'}</td>"
            f"{team_cell}"
            f"<td>{oa_v}/{pot_v}</td>"
            f"<td>{grade_badge(rating)}</td>"
            f"{extra_cells}"
            f"<td>{key_stat}</td>"
            f"<td>{war_disp}</td>"
            f"<td>{sal_str}</td>"
            f"<td>{yrs_left}y</td>"
            f'<td style="color:{injury_color(r["prone_overall"])};font-weight:bold">'
            f"{injury_label(r['prone_overall'])}</td>"
            f"<td>{flags}</td>"
            f"</tr>\n"
        )
    return html


def generate_trade_targets_report(
    save_name,
    offer_label,
    offered_where,
    target_where,
    my_team_id,
    mode="offering",
    target_join="",
    order_by="pr.rating_overall DESC",
    limit=25,
    highlight=None,
):
    """Generate a trade targets HTML report.

    offer_label:   Human-readable label, e.g. "Johnny Bench".
    offered_where: SQL WHERE fragment for the player(s) on the offer side.
    target_where:  SQL WHERE fragment for the return side.
    my_team_id:    The managed team's team_id (read from saves.json).
    mode:          "offering" — you're trading away your player, seeking returns.
                   "acquiring" — you want someone else's player; show what you'd give up.
    target_join:   Optional JOIN clause for advanced stats tables.
    highlight:     List of (col_key, display_label) tuples for extra columns, or None.

    Returns (path_str, dict(offered=list, targets=list)).
    """
    engine = get_engine(save_name)
    last_import = get_last_import_time()
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    if mode == "acquiring":
        offered_team_filter = f"p.team_id != {my_team_id} AND p.league_id = 203"
        target_team_filter = f"p.team_id = {my_team_id}"
    else:
        offered_team_filter = f"p.team_id = {my_team_id}"
        target_team_filter = f"p.team_id != {my_team_id} AND p.league_id = 203"

    offered_sql = (
        _SELECT
        + _FROM
        + f"""
        WHERE p.free_agent = 0 AND p.retired = 0
          AND {offered_team_filter}
          AND ({offered_where})
        ORDER BY pr.rating_overall DESC
        LIMIT 10
        """
    )

    target_sql = (
        _SELECT
        + _FROM
        + (f"\n{target_join}" if target_join else "")
        + f"""
        WHERE p.free_agent = 0 AND p.retired = 0
          AND {target_team_filter}
          AND ({target_where})
        ORDER BY {order_by}
        LIMIT {limit}
        """
    )

    with engine.connect() as conn:
        offered = [row_to_dict(r) for r in conn.execute(text(offered_sql)).fetchall()]
        targets = [row_to_dict(r) for r in conn.execute(text(target_sql)).fetchall()]

    if offered:
        p = offered[0]
        base = re.sub(r"[^a-z0-9_]", "", f"{p['first_name']}_{p['last_name']}".lower())[:40]
        slug = f"{base}_{p['player_id']}"
    else:
        slug = re.sub(r"[^a-z0-9_]", "", offer_label.lower().replace(" ", "_"))[:50]

    offer_label_esc = html.escape(offer_label, quote=True)
    if mode == "acquiring":
        offered_show_team = True   # show where the target player plays
        target_show_team = False   # targets are your own players
        offered_section_title = "Player You're Targeting"
        targets_section_title = f"What You'd Need to Give Up ({len(targets)} players)"
        page_meta = f"Acquiring: {offer_label_esc}"
    else:
        offered_show_team = False  # your players — team is implied
        target_show_team = True
        offered_section_title = "What You're Offering"
        targets_section_title = f"Return Targets ({len(targets)} players)"
        page_meta = f"Offering: {offer_label_esc}"

    def _key_header_for_rows(rows):
        player_types = {r.get("player_type") for r in rows if r.get("player_type")}
        if "pitcher" in player_types and len(player_types) > 1:
            return "wRC+/FIP"
        if player_types == {"pitcher"}:
            return "FIP"
        return "wRC+"

    key_header_off = _key_header_for_rows(offered)
    offered_header = build_table_header(show_team=offered_show_team, key_header=key_header_off, highlight=None)
    offered_rows_html = build_table_rows(offered, show_team=offered_show_team, highlight=None)

    key_header_tgt = _key_header_for_rows(targets)
    targets_header = build_table_header(show_team=target_show_team, key_header=key_header_tgt, highlight=highlight)
    targets_rows_html = build_table_rows(targets, show_team=target_show_team, highlight=highlight)

    # Spotlights — check offered side for no-trade in acquiring mode; targets side otherwise
    spotlight = ""
    spotlight_list = offered if mode == "acquiring" else targets
    no_trade_list = [r for r in spotlight_list if r.get("no_trade")]
    injury_list = [r for r in targets if (r.get("prone_overall") or 0) > 150]
    elite_list = [r for r in (offered if mode == "acquiring" else targets)
                  if (r.get("rating_overall") or 0) >= 75]

    if no_trade_list:
        names = ", ".join(f"{r['first_name']} {r['last_name']}" for r in no_trade_list)
        label = "Target has a no-trade clause" if mode == "acquiring" else "No-Trade Clause"
        spotlight += (
            f'<div style="background:#fff8e6;border:1px solid #cc9900;padding:10px 14px;'
            f'border-radius:4px;margin:8px 0;font-size:13px">'
            f"<b>🔒 {label}:</b> {names} — their team must consent to the deal.</div>"
        )
    if injury_list:
        names = ", ".join(f"{r['first_name']} {r['last_name']}" for r in injury_list)
        label = "Injury-prone pieces you'd move" if mode == "acquiring" else "Injury Risk"
        spotlight += (
            f'<div style="background:#fff0f0;border:1px solid #cc8888;padding:10px 14px;'
            f'border-radius:4px;margin:8px 0;font-size:13px">'
            f"<b>⚠ {label}:</b> {names} — Fragile or Wrecked injury rating; "
            f"factor into trade value assessment.</div>"
        )
    if elite_list and mode != "acquiring":
        names = ", ".join(f"{r['first_name']} {r['last_name']}" for r in elite_list)
        spotlight += (
            f'<div style="background:#f0fff0;border:1px solid #88cc88;padding:10px 14px;'
            f'border-radius:4px;margin:8px 0;font-size:13px">'
            f"<b>⭐ Premium Targets (Rating ≥75):</b> {names} — "
            f"likely require a strong return package.</div>"
        )

    _ootp_kwargs_esc = json.dumps(dict(
        offered_where=offered_where, target_where=target_where,
        my_team_id=my_team_id, mode=mode,
        target_join=target_join, order_by=order_by, limit=limit, highlight=highlight
    )).replace('"', '&quot;')
    _args_esc = offer_label.replace("&", "&amp;").replace('"', "&quot;")
    _ootp_meta = (
        '<meta name="ootp-skill" content="trade-targets">'
        f'<meta name="ootp-args" content="{_args_esc}">'
        f'<meta name="ootp-save" content="{save_name}">'
        f'<meta name="ootp-kwargs" content="{_ootp_kwargs_esc}">'
    )

    html_doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Trade Targets — {offer_label_esc}</title>
{_ootp_meta}
<style>{get_report_css("1200px")}</style></head><body>
<div class="container">

<div class="page-header">
  <div class="player-name">Trade Targets</div>
  <div class="player-meta">{page_meta}</div>
  <div class="import-ts">{len(targets)} player{"s" if len(targets) != 1 else ""} found
    &bull; Last DB import: {last_import or "unknown"} &bull; Generated: {generated_at}</div>
</div>

<div class="section">
  <div class="section-title">{offered_section_title}</div>
  <table>
  {offered_header}
  {offered_rows_html}
  </table>
</div>

<div class="section">
<!-- ANALYSIS:START --><!-- TRADE_CALLOUT_SUMMARY --><!-- ANALYSIS:END -->
</div>

<div class="section">
  <div class="section-title">{targets_section_title}</div>
  <table>
  {targets_header}
  {targets_rows_html}
  </table>
</div>

{spotlight}

</div>
</body></html>"""

    report_path = get_reports_dir(save_name, "trade_targets") / f"{slug}.html"
    write_report_html(report_path, html_doc)

    return str(report_path), dict(offered=offered, targets=targets)
