#!/usr/bin/env python3
"""Waiver wire claim evaluator report generator for OOTP Baseball."""

import html
from datetime import datetime
from pathlib import Path

from config import (
    INJURY_IRON_MAN_MAX, INJURY_DURABLE_MAX, INJURY_NORMAL_MAX, INJURY_FRAGILE_MAX,
    TRAIT_POOR_MAX, TRAIT_BELOW_AVG_MAX, TRAIT_AVERAGE_MAX, TRAIT_GOOD_MAX,
)
from ootp_db_constants import (
    MLB_LEAGUE_ID, POS_MAP, BATS_MAP, THROWS_MAP, ROLE_MAP,
    SPLIT_CAREER_OVERALL,
)
from report_write import write_report_html, report_filename
from shared_css import (
    db_name_from_save,
    get_engine,
    get_last_import_iso_for_save,
    get_report_css,
    get_reports_dir,
    load_saves_registry,
)
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Positions considered "pitcher" for group comparison
PITCHER_POS = {1}
# OF positions that are compared together
OF_POS = {7, 8, 9}
# Corner IF that share comparison
CORNER_IF_POS = {3, 5}
# Middle IF that share comparison
MIDDLE_IF_POS = {4, 6}


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


def find_existing_waiver_report(player_id, save_name, raw_args=""):
    reports_dir = get_reports_dir(save_name, "waiver_claims")
    path = reports_dir / report_filename(f"waiver_{player_id}", dict(raw_args=raw_args.strip().lower()))
    if not path.exists():
        return None
    last_import = get_last_import_iso_for_save(save_name)
    if not last_import:
        return None
    if path.stat().st_mtime > datetime.fromisoformat(last_import).timestamp():
        return str(path)
    return None


def get_comparison_positions(position, player_type):
    """Return positions to compare against on the user's roster."""
    pos = int(position)
    if player_type == "pitcher" or pos == 1:
        return PITCHER_POS
    if pos in OF_POS:
        return OF_POS
    if pos in CORNER_IF_POS:
        return CORNER_IF_POS
    if pos in MIDDLE_IF_POS:
        return MIDDLE_IF_POS
    return {pos}


def _lookup_player(conn, first_name, last_name):
    row = conn.execute(text("""
        SELECT
            p.player_id, p.first_name, p.last_name, p.position, p.age,
            p.bats, p.throws, p.team_id, p.role,
            p.local_pop, p.national_pop,
            p.prone_overall, p.injury_is_injured, p.injury_dl_left,
            p.personality_play_for_winner,
            pr.rating_overall, pr.rating_offense, pr.rating_defense,
            pr.rating_potential, pr.rating_durability, pr.rating_development,
            pr.rating_clubhouse, pr.rating_baserunning,
            pr.rating_contact_quality, pr.rating_discipline,
            pr.flag_injury_risk, pr.flag_leader, pr.flag_high_ceiling,
            pr.oa, pr.pot, pr.war, pr.wrc_plus,
            pr.rating_now, pr.rating_ceiling, pr.confidence,
            pr.prone_overall as pr_prone,
            pr.player_type, pr.team_abbr,
            pr.work_ethic, pr.intelligence, pr.greed, pr.loyalty,
            prs.is_on_waivers, prs.designated_for_assignment,
            prs.days_on_waivers, prs.days_on_waivers_left, prs.days_on_dfa_left,
            prs.mlb_service_years, prs.options_used,
            prs.is_active, prs.is_on_secondary, prs.is_on_dl, prs.is_on_dl60,
            prs.claimed_team_id,
            pc.years, pc.current_year, pc.no_trade,
            pc.salary0, pc.salary1, pc.salary2, pc.salary3, pc.salary4,
            pc.salary5, pc.salary6, pc.salary7, pc.salary8, pc.salary9,
            t.nickname as team_name
        FROM players p
        LEFT JOIN player_ratings pr ON pr.player_id = p.player_id
        JOIN players_roster_status prs ON prs.player_id = p.player_id
        LEFT JOIN players_contract pc ON pc.player_id = p.player_id
        LEFT JOIN teams t ON t.team_id = p.team_id
        WHERE LOWER(p.first_name) = LOWER(:fn)
          AND LOWER(p.last_name) = LOWER(:ln)
          AND p.retired = 0
        LIMIT 1
    """), dict(fn=first_name, ln=last_name)).mappings().fetchone()
    if not row:
        return None
    return dict(row)


def _get_incumbents(conn, my_team_id, comparison_positions, player_type, player_role):
    pos_tuple = tuple(int(p) for p in comparison_positions)
    # Build position filter
    if player_type == "pitcher":
        # Compare same role: SP vs SP, RP/CL vs RP/CL
        role_filter = "AND p.role = :role" if player_role in (11, 12, 13) else ""
        pos_filter = "AND pr.position = 1"
    else:
        pos_filter = f"AND pr.position IN ({','.join(str(p) for p in pos_tuple)})"
        role_filter = ""

    sql = f"""
        SELECT
            pr.player_id, pr.first_name, pr.last_name, pr.position, pr.age,
            pr.oa, pr.pot, pr.rating_now, pr.rating_ceiling, pr.confidence,
            pr.rating_overall, pr.rating_offense, pr.rating_defense,
            pr.rating_durability, pr.rating_development, pr.war, pr.wrc_plus,
            pr.flag_injury_risk, pr.flag_leader, pr.player_type,
            prs.is_active, prs.is_on_dl, prs.is_on_dl60, prs.mlb_service_years,
            prs.options_used, prs.designated_for_assignment, prs.is_on_waivers,
            pc.years, pc.current_year,
            pc.salary0, pc.salary1, pc.salary2, pc.salary3, pc.salary4,
            pc.salary5, pc.salary6, pc.salary7, pc.salary8, pc.salary9,
            p.role, p.prone_overall
        FROM player_ratings pr
        JOIN players p ON p.player_id = pr.player_id
        JOIN team_roster tr ON tr.player_id = pr.player_id AND tr.team_id = :tid AND tr.list_id = 1
        JOIN players_roster_status prs ON prs.player_id = pr.player_id
        LEFT JOIN players_contract pc ON pc.player_id = pr.player_id
        WHERE p.retired = 0
          {pos_filter}
          {role_filter}
        ORDER BY pr.rating_overall DESC
    """
    params = dict(tid=my_team_id)
    if player_role in (11, 12, 13) and player_type == "pitcher":
        # Group SP and non-SP separately
        if player_role == 11:
            sql = sql.replace("AND p.role = :role", "AND p.role = 11")
        else:
            sql = sql.replace("AND p.role = :role", "AND p.role IN (12, 13)")

    rows = conn.execute(text(sql), params).mappings().fetchall()
    return [dict(r) for r in rows]


def _get_advanced_stats_batter(conn, player_id):
    row = conn.execute(text("""
        SELECT g, pa, ab, h, r, rbi, hr, sb, bb, k, ba, obp, slg, ops, iso,
               k_pct, bb_pct, babip, woba, wrc_plus, ops_plus, war, wpa,
               batted_balls, avg_ev, max_ev, avg_la,
               hard_hit_pct, barrel_pct, sweet_spot_pct,
               gb_pct, ld_pct, fb_pct,
               xba, xslg, xwoba, xbacon,
               pa_vs_lhp, ba_vs_lhp, obp_vs_lhp, slg_vs_lhp, iso_vs_lhp,
               k_pct_vs_lhp, bb_pct_vs_lhp, woba_vs_lhp, wrc_plus_vs_lhp,
               avg_ev_vs_lhp, hard_hit_pct_vs_lhp, barrel_pct_vs_lhp, xwoba_vs_lhp,
               pa_vs_rhp, ba_vs_rhp, obp_vs_rhp, slg_vs_rhp, iso_vs_rhp,
               k_pct_vs_rhp, bb_pct_vs_rhp, woba_vs_rhp, wrc_plus_vs_rhp,
               avg_ev_vs_rhp, hard_hit_pct_vs_rhp, barrel_pct_vs_rhp, xwoba_vs_rhp
        FROM batter_advanced_stats WHERE player_id = :pid
    """), dict(pid=player_id)).mappings().fetchone()
    return dict(row) if row else None


def _get_advanced_stats_pitcher(conn, player_id):
    row = conn.execute(text("""
        SELECT g, gs, w, l, s, hld, ip, bf, era, fip, xfip,
               k_pct, bb_pct, k_bb_pct, whip, k_9, bb_9, hr_9, babip,
               gb_pct, war, wpa,
               avg_ev_against, hard_hit_pct_against, barrel_pct_against,
               xba_against, xwoba_against,
               bf_vs_lhb, era_vs_lhb, fip_vs_lhb,
               k_pct_vs_lhb, bb_pct_vs_lhb, k_bb_pct_vs_lhb,
               whip_vs_lhb, babip_vs_lhb,
               bf_vs_rhb, era_vs_rhb, fip_vs_rhb,
               k_pct_vs_rhb, bb_pct_vs_rhb, k_bb_pct_vs_rhb,
               whip_vs_rhb, babip_vs_rhb
        FROM pitcher_advanced_stats WHERE player_id = :pid
    """), dict(pid=player_id)).mappings().fetchone()
    return dict(row) if row else None


def _get_fielding_positions(conn, player_id):
    """Return dict of {pos_int: rating} for positions the player can play (rating >= 20)."""
    row = conn.execute(text("""
        SELECT fielding_rating_pos1, fielding_rating_pos2, fielding_rating_pos3,
               fielding_rating_pos4, fielding_rating_pos5, fielding_rating_pos6,
               fielding_rating_pos7, fielding_rating_pos8, fielding_rating_pos9
        FROM players_fielding WHERE player_id = :pid LIMIT 1
    """), dict(pid=player_id)).mappings().fetchone()
    if not row:
        return {}
    positions = {}
    for i in range(1, 10):
        val = row[f"fielding_rating_pos{i}"]
        if val and int(val) >= 20:
            positions[i] = int(val)
    return positions


def _get_fielding_details(conn, player_id):
    """Return full fielding component ratings for the player."""
    row = conn.execute(text("""
        SELECT fielding_ratings_infield_range, fielding_ratings_infield_arm,
               fielding_ratings_turn_doubleplay, fielding_ratings_infield_error,
               fielding_ratings_outfield_range, fielding_ratings_outfield_arm,
               fielding_ratings_outfield_error,
               fielding_ratings_catcher_arm, fielding_ratings_catcher_ability,
               fielding_ratings_catcher_framing,
               fielding_experience1, fielding_experience2, fielding_experience3,
               fielding_experience4, fielding_experience5, fielding_experience6,
               fielding_experience7, fielding_experience8, fielding_experience9,
               fielding_rating_pos2, fielding_rating_pos4, fielding_rating_pos5,
               fielding_rating_pos6, fielding_rating_pos7, fielding_rating_pos8,
               fielding_rating_pos9
        FROM players_fielding WHERE player_id = :pid LIMIT 1
    """), dict(pid=player_id)).mappings().fetchone()
    return dict(row) if row else None


def _get_40man_count(conn, my_team_id):
    result = conn.execute(text(f"""
        SELECT COUNT(*) FROM players p
        JOIN players_roster_status prs ON prs.player_id = p.player_id
        WHERE p.team_id = :tid AND prs.league_id = {MLB_LEAGUE_ID}
          AND p.retired = 0
    """), dict(tid=my_team_id)).fetchone()
    return int(result[0]) if result else 0


def _get_team_name(conn, team_id):
    if not team_id:
        return "Free Agent"
    row = conn.execute(text(
        "SELECT name, nickname FROM teams WHERE team_id = :tid LIMIT 1"
    ), dict(tid=team_id)).mappings().fetchone()
    if row:
        return f"{row['name']} {row['nickname']}"
    return f"Team {team_id}"


# ─── HTML builders ────────────────────────────────────────────────────────────

def _build_candidate_header(p, adv, last_import, generated_at):
    pos_label = POS_MAP.get(int(p.get("position") or 0), "?")
    bats = BATS_MAP.get(int(p.get("bats") or 0), "?")
    throws = THROWS_MAP.get(int(p.get("throws") or 0), "?")
    role_label = ROLE_MAP.get(int(p.get("role") or 0), "—")
    player_type = p.get("player_type", "batter")

    rating_now = p.get("rating_now")
    rating_ceiling = p.get("rating_ceiling")
    has_ratings = rating_now is not None
    rating_now = float(rating_now) if has_ratings else None
    rating_ceiling = float(rating_ceiling) if rating_ceiling is not None else None
    rating = float(p.get("rating_overall")) if has_ratings else None
    grade = letter_grade(rating) if rating is not None else "N/A"
    team_disp = p.get("team_abbr") or "FA"

    grade_color = (
        "#1a7a1a" if rating is not None and rating >= 70
        else "#cc7700" if rating is not None and rating >= 40
        else "#cc2222"
    )

    flags_html = ""
    flags = []
    if p.get("flag_injury_risk"):
        flags.append('<span class="flag flag-red">Injury Risk</span>')
    if p.get("flag_leader"):
        flags.append('<span class="flag flag-green">Leader</span>')
    if p.get("flag_high_ceiling"):
        flags.append('<span class="flag flag-blue">High Ceiling</span>')
    if p.get("no_trade"):
        flags.append('<span class="flag flag-yellow">No-Trade Clause</span>')
    if p.get("injury_is_injured") and int(p.get("injury_is_injured") or 0) > 0:
        dl_left = p.get("injury_dl_left") or 0
        flags.append(f'<span class="flag flag-red">Currently Injured ({dl_left}d left)</span>')
    if flags:
        flags_html = f'<div class="flags" style="margin-top:8px">{"".join(flags)}</div>'

    # Waiver status pill
    status_html = ""
    if p.get("is_on_waivers") and int(p.get("is_on_waivers") or 0) == 1:
        days_left = p.get("days_on_waivers_left") or 0
        days_on = p.get("days_on_waivers") or 0
        status_html = (
            f'<span style="background:#cc2222;color:white;font-weight:bold;'
            f'border-radius:4px;padding:3px 10px;font-size:12px">'
            f'ON WAIVERS — {days_left}d left ({days_on}d elapsed)</span>'
        )
    elif p.get("designated_for_assignment") and int(p.get("designated_for_assignment") or 0) == 1:
        dfa_left = p.get("days_on_dfa_left") or 0
        status_html = (
            f'<span style="background:#cc7700;color:white;font-weight:bold;'
            f'border-radius:4px;padding:3px 10px;font-size:12px">'
            f'DFA — {dfa_left}d remaining</span>'
        )
    else:
        status_html = (
            '<span style="background:#888;color:white;font-weight:bold;'
            'border-radius:4px;padding:3px 10px;font-size:12px">'
            'NOT ON WAIVERS</span>'
        )

    current_salary = get_current_salary(p)
    years_rem = get_years_remaining(p)
    arb = arb_status_label(p.get("mlb_service_years"))

    war_val = p.get("war")
    war_disp = f"{float(war_val):.1f}" if war_val is not None else "—"

    key_stat = ""
    if player_type == "batter":
        wrc = p.get("wrc_plus")
        key_stat = f"wRC+: <b>{int(wrc) if wrc is not None else '—'}</b>"
        if adv:
            ba = adv.get("ba")
            key_stat += f" | AVG: <b>{float(ba):.3f}</b>" if ba is not None else ""
    else:
        if adv:
            era = adv.get("era")
            fip = adv.get("fip")
            key_stat = f"ERA: <b>{float(era):.2f}</b> | FIP: <b>{float(fip):.2f}</b>" if era is not None and fip is not None else ""

    prone = p.get("prone_overall") or p.get("pr_prone")
    inj_label = injury_label(prone)
    inj_color = injury_color(prone)

    svc_yrs = p.get("mlb_service_years") or 0

    first_name_esc = html.escape(str(p.get("first_name", "")))
    last_name_esc = html.escape(str(p.get("last_name", "")))
    team_disp_esc = html.escape(str(team_disp))

    return f"""
<div class="page-header">
  <div class="header-top">
    <div>
      <div class="player-name">{first_name_esc} {last_name_esc}</div>
      <div class="player-meta">
        {pos_label}{f" ({role_label})" if pos_label == "P" else ""} &bull;
        {team_disp_esc} &bull; Age {p.get("age", "?")} &bull;
        {bats}/{throws} &bull;
        <span class="badge badge-oa">NOW {f"{rating_now:.1f}" if rating_now is not None else "N/A"}</span>&nbsp;
        <span class="badge badge-pot">CEIL {f"{rating_ceiling:.1f}" if rating_ceiling is not None else "N/A"}</span>&nbsp;
        <span class="badge" style="background:#333;color:{'#1a7a1a' if (p.get('confidence') or 0) >= 0.9 else '#cc7700' if (p.get('confidence') or 0) >= 0.5 else '#cc2222'}">CONF {"N/A" if not has_ratings else f"{p.get('confidence') or 0:.0%}"}</span>
      </div>
      <div style="margin-top:8px">{status_html}</div>
      {flags_html}
    </div>
    <div style="text-align:right">
      <div class="grade-badge" style="color:{grade_color}">{grade}</div>
      <div style="font-size:20px;font-weight:700;color:#f0c040;margin-top:4px">{f"{rating:.1f}" if rating is not None else "N/A"}</div>
      <div style="font-size:12px;color:#aaa">Composite Rating</div>
    </div>
  </div>
  <div style="margin-top:12px;display:flex;gap:24px;font-size:12px;color:#ccc;flex-wrap:wrap">
    <span>WAR: <b style="color:#f0c040">{war_disp}</b></span>
    <span>{key_stat}</span>
    <span>Salary: <b style="color:#f0c040">{fmt_salary(current_salary)}</b>
          {f"({years_rem}yr remaining)" if years_rem > 0 else "(Arb/Pre-arb)"}</span>
    <span>Service: <b>{svc_yrs:.1f}yr</b> ({arb})</span>
    <span>Injury Risk: <b style="color:{inj_color}">{inj_label}</b></span>
  </div>
  <div class="import-ts">Waiver Claim Evaluator &bull; Last DB import: {html.escape(last_import or "unknown")} &bull; Generated: {html.escape(generated_at)}</div>
</div>"""


def _build_ratings_section(p):
    tip = (
        '<span style="cursor:help;color:#7f8c8d;font-size:10px;margin-left:3px;vertical-align:super" '
        'title="Trade only">†</span>'
    )
    scores = [
        ("offense", "Offense", p.get("rating_offense")),
        ("contact", "Contact", p.get("rating_contact_quality")),
        ("discipline", "Discipline", p.get("rating_discipline")),
        ("defense", "Defense", p.get("rating_defense")),
        ("baserunning", "Baserunning", p.get("rating_baserunning")),
        ("durability", "Durability", p.get("rating_durability")),
        ("potential", f"Potential{tip}", p.get("rating_potential")),
        ("clubhouse", f"Clubhouse{tip}", p.get("rating_clubhouse")),
    ]
    rows = ""
    for _key, label_html, val in scores:
        if val is None:
            continue
        v = float(val)
        bar_class = "bar-green" if v >= 70 else "bar-yellow" if v >= 40 else "bar-red"
        c = score_color(v)
        rows += (
            f"<tr><td class='left'>{label_html}</td>"
            f"<td><div class='bar-bg'><div class='bar-fill {bar_class}' "
            f"style='width:{v}%'></div></div></td>"
            f"<td style='font-weight:bold;color:{c}'>{v:.0f}</td></tr>\n"
        )
    return f"""
<div class="section">
  <div class="section-title">Rating Breakdown</div>
  <table style="width:auto;min-width:280px">
    <thead><tr><th class="left">Dimension</th><th style="width:190px">Score</th><th>Value</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="font-size:10px;color:#888;margin:6px 0 0 0">† Trade only</p>
</div>"""


def _build_contract_section(p):
    years = int(p.get("years") or 0)
    cy = int(p.get("current_year") or 0)
    salaries = []
    for i in range(years):
        sal = p.get(f"salary{i}")
        if sal is None:
            break
        salaries.append((i, sal))

    salary_cells = ""
    total = 0
    for i, sal in salaries:
        is_current = (i == cy)
        style = " style='font-weight:bold;background:#fff3cd'" if is_current else ""
        salary_cells += f"<td{style}>{fmt_salary(sal)}</td>"
        total += int(sal or 0)

    years_rem = get_years_remaining(p)
    no_trade = p.get("no_trade") or 0
    arb = arb_status_label(p.get("mlb_service_years"))
    options = p.get("options_used") or 0

    header_cells = "".join(
        f"<th>Yr {i + 1}{' (Now)' if i == cy else ''}</th>" for i, _ in salaries
    )

    obligation_note = ""
    if years_rem > 0 and total > 0:
        future = sum(int(p.get(f"salary{i}") or 0) for i in range(cy, years))
        obligation_note = (
            f'<p style="margin-top:6px;font-size:12px;color:#555">'
            f'Claiming this player obligates your team to <b>{fmt_salary(future)}</b> '
            f'over the remaining {years_rem} contract year(s).</p>'
        )

    return f"""
<div class="section">
  <div class="section-title">Contract Obligation (If Claimed)</div>
  <table style="width:auto">
    <thead><tr>{header_cells}<th>Total</th></tr></thead>
    <tbody><tr>{salary_cells}<td style="font-weight:bold">{fmt_salary(total)}</td></tr></tbody>
  </table>
  {obligation_note}
  <div style="margin-top:6px;font-size:12px;color:#555;display:flex;gap:16px">
    <span>Status: <b>{arb}</b></span>
    <span>Options used: <b>{options}</b></span>
    {'<span class="tag tag-warn">No-Trade Clause</span>' if no_trade else ""}
  </div>
</div>"""


def _build_adv_stats_batter(adv):
    if not adv:
        return ""

    def f3(v):
        return f"{float(v):.3f}" if v is not None else "—"

    def f2(v):
        return f"{float(v):.2f}" if v is not None else "—"

    def fp(v):
        return f"{float(v) * 100:.1f}%" if v is not None else "—"

    def c_wrc(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if int(v) >= 115 else "#cc7700" if int(v) >= 85 else "#cc2222"

    def c_ev(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 92 else "#cc7700" if float(v) >= 86 else "#cc2222"

    def c_barrel(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 0.10 else "#cc7700" if float(v) >= 0.04 else "#cc2222"

    def c_hard(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 0.45 else "#cc7700" if float(v) >= 0.32 else "#cc2222"

    def c_xwoba(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 0.360 else "#cc7700" if float(v) >= 0.300 else "#cc2222"

    def c_war(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 3 else "#cc7700" if float(v) >= 1 else "#cc2222"

    wrc = adv.get("wrc_plus")

    # L/R splits row
    pa_l = adv.get("pa_vs_lhp") or 0
    pa_r = adv.get("pa_vs_rhp") or 0
    splits_html = ""
    if pa_l or pa_r:
        splits_html = f"""
  <h3 style="margin:12px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#777">Platoon Splits</h3>
  <table>
    <thead>
      <tr><th>Split</th><th>PA</th><th>AVG</th><th>OBP</th><th>SLG</th><th>ISO</th>
          <th>K%</th><th>BB%</th><th>wOBA</th><th>wRC+</th>
          <th>Avg EV</th><th>Hard Hit%</th><th>Barrel%</th><th>xwOBA</th></tr>
    </thead>
    <tbody>
      <tr>
        <td class="left"><b>vs LHP</b></td>
        <td>{pa_l or "—"}</td>
        <td>{f3(adv.get("ba_vs_lhp"))}</td>
        <td>{f3(adv.get("obp_vs_lhp"))}</td>
        <td>{f3(adv.get("slg_vs_lhp"))}</td>
        <td>{f3(adv.get("iso_vs_lhp"))}</td>
        <td>{fp(adv.get("k_pct_vs_lhp"))}</td>
        <td>{fp(adv.get("bb_pct_vs_lhp"))}</td>
        <td>{f3(adv.get("woba_vs_lhp"))}</td>
        <td style="font-weight:bold;color:{c_wrc(adv.get("wrc_plus_vs_lhp"))}">{int(adv.get("wrc_plus_vs_lhp")) if adv.get("wrc_plus_vs_lhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_ev(adv.get("avg_ev_vs_lhp")) if adv.get("avg_ev_vs_lhp") else "#888"}">{f2(adv.get("avg_ev_vs_lhp")) if adv.get("avg_ev_vs_lhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_hard(adv.get("hard_hit_pct_vs_lhp")) if adv.get("hard_hit_pct_vs_lhp") else "#888"}">{fp(adv.get("hard_hit_pct_vs_lhp")) if adv.get("hard_hit_pct_vs_lhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_barrel(adv.get("barrel_pct_vs_lhp")) if adv.get("barrel_pct_vs_lhp") else "#888"}">{fp(adv.get("barrel_pct_vs_lhp")) if adv.get("barrel_pct_vs_lhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_xwoba(adv.get("xwoba_vs_lhp")) if adv.get("xwoba_vs_lhp") else "#888"}">{f3(adv.get("xwoba_vs_lhp")) if adv.get("xwoba_vs_lhp") else "—"}</td>
      </tr>
      <tr>
        <td class="left"><b>vs RHP</b></td>
        <td>{pa_r or "—"}</td>
        <td>{f3(adv.get("ba_vs_rhp"))}</td>
        <td>{f3(adv.get("obp_vs_rhp"))}</td>
        <td>{f3(adv.get("slg_vs_rhp"))}</td>
        <td>{f3(adv.get("iso_vs_rhp"))}</td>
        <td>{fp(adv.get("k_pct_vs_rhp"))}</td>
        <td>{fp(adv.get("bb_pct_vs_rhp"))}</td>
        <td>{f3(adv.get("woba_vs_rhp"))}</td>
        <td style="font-weight:bold;color:{c_wrc(adv.get("wrc_plus_vs_rhp"))}">{int(adv.get("wrc_plus_vs_rhp")) if adv.get("wrc_plus_vs_rhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_ev(adv.get("avg_ev_vs_rhp")) if adv.get("avg_ev_vs_rhp") else "#888"}">{f2(adv.get("avg_ev_vs_rhp")) if adv.get("avg_ev_vs_rhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_hard(adv.get("hard_hit_pct_vs_rhp")) if adv.get("hard_hit_pct_vs_rhp") else "#888"}">{fp(adv.get("hard_hit_pct_vs_rhp")) if adv.get("hard_hit_pct_vs_rhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_barrel(adv.get("barrel_pct_vs_rhp")) if adv.get("barrel_pct_vs_rhp") else "#888"}">{fp(adv.get("barrel_pct_vs_rhp")) if adv.get("barrel_pct_vs_rhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_xwoba(adv.get("xwoba_vs_rhp")) if adv.get("xwoba_vs_rhp") else "#888"}">{f3(adv.get("xwoba_vs_rhp")) if adv.get("xwoba_vs_rhp") else "—"}</td>
      </tr>
    </tbody>
  </table>"""

    return f"""
<div class="section">
  <div class="section-title">Current Season Stats</div>
  <table>
    <thead>
      <tr><th>G</th><th>PA</th><th>HR</th><th>SB</th><th>AVG</th><th>OBP</th><th>SLG</th><th>OPS</th>
          <th>ISO</th><th>BABIP</th><th>K%</th><th>BB%</th><th>wOBA</th><th>wRC+</th><th>OPS+</th><th>WAR</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>{adv.get("g") or "—"}</td>
        <td>{adv.get("pa") or "—"}</td>
        <td>{adv.get("hr") or "—"}</td>
        <td>{adv.get("sb") or "—"}</td>
        <td>{f3(adv.get("ba"))}</td>
        <td>{f3(adv.get("obp"))}</td>
        <td>{f3(adv.get("slg"))}</td>
        <td>{f3(adv.get("ops"))}</td>
        <td>{f3(adv.get("iso"))}</td>
        <td>{f3(adv.get("babip"))}</td>
        <td>{fp(adv.get("k_pct"))}</td>
        <td>{fp(adv.get("bb_pct"))}</td>
        <td>{f3(adv.get("woba"))}</td>
        <td style="font-weight:bold;color:{c_wrc(wrc)}">{int(wrc) if wrc else "—"}</td>
        <td>{int(adv.get("ops_plus")) if adv.get("ops_plus") else "—"}</td>
        <td style="font-weight:bold;color:{c_war(adv.get("war"))}">{f2(adv.get("war"))}</td>
      </tr>
    </tbody>
  </table>
  <h3 style="margin:12px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#777">Contact Quality</h3>
  <table>
    <thead>
      <tr><th>Batted Balls</th><th>Avg EV</th><th>Max EV</th><th>Avg LA</th>
          <th>Hard Hit%</th><th>Barrel%</th><th>Sweet Spot%</th>
          <th>GB%</th><th>LD%</th><th>FB%</th>
          <th>xBA</th><th>xSLG</th><th>xwOBA</th><th>xBACON</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>{adv.get("batted_balls") if adv.get("batted_balls") is not None else "—"}</td>
        <td style="font-weight:bold;color:{c_ev(adv.get("avg_ev")) if adv.get("avg_ev") is not None else "#888"}">{f2(adv.get("avg_ev")) if adv.get("avg_ev") is not None else "—"}</td>
        <td>{f2(adv.get("max_ev")) if adv.get("max_ev") is not None else "—"}</td>
        <td>{f2(adv.get("avg_la")) if adv.get("avg_la") is not None else "—"}°</td>
        <td style="font-weight:bold;color:{c_hard(adv.get("hard_hit_pct")) if adv.get("hard_hit_pct") is not None else "#888"}">{fp(adv.get("hard_hit_pct")) if adv.get("hard_hit_pct") is not None else "—"}</td>
        <td style="font-weight:bold;color:{c_barrel(adv.get("barrel_pct")) if adv.get("barrel_pct") is not None else "#888"}">{fp(adv.get("barrel_pct")) if adv.get("barrel_pct") is not None else "—"}</td>
        <td>{fp(adv.get("sweet_spot_pct")) if adv.get("sweet_spot_pct") is not None else "—"}</td>
        <td>{fp(adv.get("gb_pct")) if adv.get("gb_pct") is not None else "—"}</td>
        <td>{fp(adv.get("ld_pct")) if adv.get("ld_pct") is not None else "—"}</td>
        <td>{fp(adv.get("fb_pct")) if adv.get("fb_pct") is not None else "—"}</td>
        <td>{f3(adv.get("xba")) if adv.get("xba") is not None else "—"}</td>
        <td>{f3(adv.get("xslg")) if adv.get("xslg") is not None else "—"}</td>
        <td style="font-weight:bold;color:{c_xwoba(adv.get("xwoba")) if adv.get("xwoba") is not None else "#888"}">{f3(adv.get("xwoba")) if adv.get("xwoba") is not None else "—"}</td>
        <td>{f3(adv.get("xbacon")) if adv.get("xbacon") is not None else "—"}</td>
      </tr>
    </tbody>
  </table>
  {splits_html}
</div>"""


def _build_adv_stats_pitcher(adv):
    if not adv:
        return ""

    def f2(v):
        return f"{float(v):.2f}" if v is not None else "—"

    def f1(v):
        return f"{float(v):.1f}" if v is not None else "—"

    def fp(v):
        return f"{float(v) * 100:.1f}%" if v is not None else "—"

    def c_era(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) < 3.5 else "#cc7700" if float(v) < 4.5 else "#cc2222"

    def c_kbb(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 0.18 else "#cc7700" if float(v) >= 0.08 else "#cc2222"

    def c_hard(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) < 0.34 else "#cc7700" if float(v) < 0.42 else "#cc2222"

    def c_barrel(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) < 0.06 else "#cc7700" if float(v) < 0.10 else "#cc2222"

    def c_xwoba(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) < 0.290 else "#cc7700" if float(v) < 0.340 else "#cc2222"

    def c_war(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 3 else "#cc7700" if float(v) >= 1 else "#cc2222"

    era = adv.get("era")
    fip = adv.get("fip")
    kbb = adv.get("k_bb_pct")

    # L/R splits
    bf_l = adv.get("bf_vs_lhb") or 0
    bf_r = adv.get("bf_vs_rhb") or 0
    splits_html = ""
    if bf_l or bf_r:
        splits_html = f"""
  <h3 style="margin:12px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#777">Splits vs LHB / RHB</h3>
  <table>
    <thead>
      <tr><th>Split</th><th>BF</th><th>ERA</th><th>FIP</th>
          <th>K%</th><th>BB%</th><th>K-BB%</th><th>WHIP</th><th>BABIP</th></tr>
    </thead>
    <tbody>
      <tr>
        <td class="left"><b>vs LHB</b></td>
        <td>{bf_l or "—"}</td>
        <td style="font-weight:bold;color:{c_era(adv.get("era_vs_lhb"))}">{f2(adv.get("era_vs_lhb"))}</td>
        <td style="font-weight:bold;color:{c_era(adv.get("fip_vs_lhb"))}">{f2(adv.get("fip_vs_lhb"))}</td>
        <td>{fp(adv.get("k_pct_vs_lhb"))}</td>
        <td>{fp(adv.get("bb_pct_vs_lhb"))}</td>
        <td style="font-weight:bold;color:{c_kbb(adv.get("k_bb_pct_vs_lhb"))}">{fp(adv.get("k_bb_pct_vs_lhb"))}</td>
        <td>{f2(adv.get("whip_vs_lhb"))}</td>
        <td>{f2(adv.get("babip_vs_lhb"))}</td>
      </tr>
      <tr>
        <td class="left"><b>vs RHB</b></td>
        <td>{bf_r or "—"}</td>
        <td style="font-weight:bold;color:{c_era(adv.get("era_vs_rhb"))}">{f2(adv.get("era_vs_rhb"))}</td>
        <td style="font-weight:bold;color:{c_era(adv.get("fip_vs_rhb"))}">{f2(adv.get("fip_vs_rhb"))}</td>
        <td>{fp(adv.get("k_pct_vs_rhb"))}</td>
        <td>{fp(adv.get("bb_pct_vs_rhb"))}</td>
        <td style="font-weight:bold;color:{c_kbb(adv.get("k_bb_pct_vs_rhb"))}">{fp(adv.get("k_bb_pct_vs_rhb"))}</td>
        <td>{f2(adv.get("whip_vs_rhb"))}</td>
        <td>{f2(adv.get("babip_vs_rhb"))}</td>
      </tr>
    </tbody>
  </table>"""

    return f"""
<div class="section">
  <div class="section-title">Current Season Stats</div>
  <table>
    <thead>
      <tr><th>G</th><th>GS</th><th>IP</th><th>ERA</th><th>FIP</th><th>xFIP</th>
          <th>WHIP</th><th>K%</th><th>BB%</th><th>K-BB%</th>
          <th>K/9</th><th>BB/9</th><th>HR/9</th><th>BABIP</th><th>GB%</th><th>WAR</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>{adv.get("g") or "—"}</td>
        <td>{adv.get("gs") or "—"}</td>
        <td>{f1(adv.get("ip"))}</td>
        <td style="font-weight:bold;color:{c_era(era)}">{f2(era)}</td>
        <td style="font-weight:bold;color:{c_era(fip)}">{f2(fip)}</td>
        <td>{f2(adv.get("xfip"))}</td>
        <td>{f2(adv.get("whip"))}</td>
        <td>{fp(adv.get("k_pct"))}</td>
        <td>{fp(adv.get("bb_pct"))}</td>
        <td style="font-weight:bold;color:{c_kbb(kbb)}">{fp(kbb)}</td>
        <td>{f1(adv.get("k_9"))}</td>
        <td>{f1(adv.get("bb_9"))}</td>
        <td>{f2(adv.get("hr_9"))}</td>
        <td>{f2(adv.get("babip"))}</td>
        <td>{fp(adv.get("gb_pct")) if adv.get("gb_pct") else "—"}</td>
        <td style="font-weight:bold;color:{c_war(adv.get("war"))}">{f2(adv.get("war"))}</td>
      </tr>
    </tbody>
  </table>
  <h3 style="margin:12px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#777">Contact Allowed</h3>
  <table>
    <thead>
      <tr><th>Avg EV Against</th><th>Hard Hit%</th><th>Barrel%</th><th>xBA Against</th><th>xwOBA Against</th></tr>
    </thead>
    <tbody>
      <tr>
        <td style="font-weight:bold;color:{c_hard(adv.get("avg_ev_against")) if adv.get("avg_ev_against") else "#888"}">{f2(adv.get("avg_ev_against")) if adv.get("avg_ev_against") else "—"}</td>
        <td style="font-weight:bold;color:{c_hard(adv.get("hard_hit_pct_against")) if adv.get("hard_hit_pct_against") else "#888"}">{fp(adv.get("hard_hit_pct_against")) if adv.get("hard_hit_pct_against") else "—"}</td>
        <td style="font-weight:bold;color:{c_barrel(adv.get("barrel_pct_against")) if adv.get("barrel_pct_against") else "#888"}">{fp(adv.get("barrel_pct_against")) if adv.get("barrel_pct_against") else "—"}</td>
        <td>{f2(adv.get("xba_against")) if adv.get("xba_against") else "—"}</td>
        <td style="font-weight:bold;color:{c_xwoba(adv.get("xwoba_against")) if adv.get("xwoba_against") else "#888"}">{f2(adv.get("xwoba_against")) if adv.get("xwoba_against") else "—"}</td>
      </tr>
    </tbody>
  </table>
  {splits_html}
</div>"""


def _build_incumbents_section(incumbents, candidate, comparison_positions, my_team_abbr="Your Team"):
    if not incumbents:
        pos_labels = "/".join(POS_MAP.get(p, "?") for p in sorted(comparison_positions))
        return f"""
<div class="section">
  <div class="section-title">{my_team_abbr} Roster at {pos_labels}</div>
  <p style="color:#888;font-style:italic">No {my_team_abbr} players found at this position.</p>
</div>"""

    player_type = candidate.get("player_type", "batter")
    pos_labels = "/".join(POS_MAP.get(p, "?") for p in sorted(comparison_positions))

    cand_rating = float(candidate.get("rating_overall") or 0)
    cand_war = float(candidate.get("war") or 0)
    cand_salary = get_current_salary(candidate) or 0

    header = """
<tr>
  <th class="left">Player</th><th>Pos</th><th>Age</th>
  <th>Now</th><th>Ceiling</th><th>Rating</th>
  <th>WAR</th><th>wRC+/ERA</th>
  <th>Salary</th><th>Yrs Left</th><th>Service</th>
  <th>Options</th><th>Status</th>
</tr>"""

    # Merge candidate into the sorted-by-rating list so it appears in the right position
    cand_salary_disp = get_current_salary(candidate)
    cand_yrs = get_years_remaining(candidate)
    cand_arb = arb_status_label(candidate.get("mlb_service_years"))
    cand_pos_label = POS_MAP.get(int(candidate.get("position") or 0), "?")
    cand_wrc = candidate.get("wrc_plus")
    if player_type == "batter":
        cand_key_td = f'<td><b>{int(cand_wrc) if cand_wrc else "—"}</b></td>'
    else:
        cand_role = ROLE_MAP.get(int(candidate.get("role") or 0), "—")
        cand_key_td = f"<td><b>{cand_role}</b></td>"

    cand_row = f"""<tr style="background:#fff3cd">
      <td class="left"><b>{candidate.get("first_name", "")} {candidate.get("last_name", "")} <span style="font-weight:normal;color:#856404">(Waiver Candidate)</span></b></td>
      <td>{cand_pos_label}</td>
      <td>{candidate.get("age", "?")}</td>
      {_score_td(candidate.get("rating_now"))}
      {_score_td(candidate.get("rating_ceiling"))}
      {_score_td(candidate.get("rating_overall"))}
      {_war_td(candidate.get("war"))}
      {cand_key_td}
      <td>{fmt_salary(cand_salary_disp)}</td>
      <td>{cand_yrs}</td>
      <td>{cand_arb}</td>
      <td>{candidate.get("options_used") or 0}</td>
      <td><span class="tag tag-warn">Waiver/DFA</span></td>
    </tr>"""

    rows_html = ""
    cand_inserted = False
    for inc in incumbents:
        inc_rating = float(inc.get("rating_overall") or 0)

        # Insert candidate row at the correct sorted position
        if not cand_inserted and cand_rating >= inc_rating:
            rows_html += cand_row
            cand_inserted = True

        pos_label = POS_MAP.get(int(inc.get("position") or 0), "?")
        inc_salary = get_current_salary(inc) or 0
        inc_yrs = get_years_remaining(inc)
        arb = arb_status_label(inc.get("mlb_service_years"))
        options = inc.get("options_used") or 0

        status_parts = []
        if inc.get("is_on_dl") or inc.get("is_on_dl60"):
            status_parts.append('<span class="tag tag-bad">IL</span>')
        elif inc.get("designated_for_assignment"):
            status_parts.append('<span class="tag tag-warn">DFA</span>')
        else:
            status_parts.append('<span class="tag tag-good">Active</span>')
        if inc.get("flag_injury_risk"):
            status_parts.append('<span class="tag tag-bad">⚠</span>')

        if player_type == "batter":
            wrc = inc.get("wrc_plus")
            key_stat_td = f'<td>{int(wrc) if wrc else "—"}</td>'
        else:
            role = ROLE_MAP.get(int(inc.get("role") or 0), "—")
            key_stat_td = f"<td>{role}</td>"

        rows_html += f"""<tr>
          <td class="left"><b>{inc.get("first_name", "")} {inc.get("last_name", "")}</b></td>
          <td>{pos_label}</td>
          <td>{inc.get("age", "?")}</td>
          {_score_td(inc.get("rating_now"))}
          {_score_td(inc.get("rating_ceiling"))}
          {_score_td(inc.get("rating_overall"))}
          {_war_td(inc.get("war"))}
          {key_stat_td}
          <td>{fmt_salary(inc_salary)}</td>
          <td>{inc_yrs}</td>
          <td>{arb}</td>
          <td>{options}</td>
          <td>{"".join(status_parts)}</td>
        </tr>"""

    # Append at the bottom if candidate is lower-rated than all incumbents
    if not cand_inserted:
        rows_html += cand_row

    return f"""
<div class="section">
  <div class="section-title">{my_team_abbr} Roster Comparison — {pos_labels}</div>
  <p style="font-size:12px;color:#666;margin-bottom:8px">
    Candidate row highlighted in yellow, sorted by composite rating.
  </p>
  <table>
    <thead>{header}</thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""


def _build_fielding_section(fld, position):
    """Deep fielding component section for defensively important positions: C, 2B, SS, CF."""
    if not fld:
        return ""
    pos = int(position or 0)
    # Only show for premium defensive positions
    if pos not in (2, 4, 6, 8):
        return ""

    def _r(val, invert=False):
        """Color a 20-80 rating. invert=True means lower is better (error rate)."""
        if val is None:
            return "#888"
        v = int(val)
        if invert:
            return "#1a7a1a" if v <= 40 else "#cc7700" if v <= 55 else "#cc2222"
        return "#1a7a1a" if v >= 60 else "#cc7700" if v >= 40 else "#cc2222"

    def _cell(label, val, invert=False):
        if val is None or int(val) == 0:
            return f"<tr><td class='left'>{label}</td><td>—</td></tr>"
        v = int(val)
        c = _r(v, invert)
        grade = "Elite" if v >= 70 else "Above Avg" if v >= 55 else "Average" if v >= 40 else "Below Avg"
        return f"<tr><td class='left'>{label}</td><td style='font-weight:bold;color:{c}'>{v} <span style='font-size:11px;font-weight:normal;color:#888'>({grade})</span></td></tr>"

    if pos == 2:  # Catcher
        title = "Catching Grades"
        pos_rating = fld.get("fielding_rating_pos2")
        rows = (
            _cell("Overall C Rating", pos_rating)
            + _cell("Receiving / Blocking", fld.get("fielding_ratings_catcher_ability"))
            + _cell("Framing", fld.get("fielding_ratings_catcher_framing"))
            + _cell("Arm Strength", fld.get("fielding_ratings_catcher_arm"))
        )
        note = "Framing and receiving are the primary value drivers for a catching claim."

    elif pos in (4, 6):  # 2B / SS
        pos_label = "2B" if pos == 4 else "SS"
        title = f"Middle Infield Grades ({pos_label})"
        pos_rating = fld.get(f"fielding_rating_pos{pos}")
        rows = (
            _cell(f"Overall {pos_label} Rating", pos_rating)
            + _cell("Range", fld.get("fielding_ratings_infield_range"))
            + _cell("Arm", fld.get("fielding_ratings_infield_arm"))
            + _cell("Turn DP", fld.get("fielding_ratings_turn_doubleplay"))
            + _cell("Error Rate (lower = better)", fld.get("fielding_ratings_infield_error"), invert=True)
        )
        note = "Range is the most important component for SS; DP turn and range both matter at 2B."

    else:  # CF (pos == 8)
        title = "Center Field Grades"
        pos_rating = fld.get("fielding_rating_pos8")
        rows = (
            _cell("Overall CF Rating", pos_rating)
            + _cell("Range", fld.get("fielding_ratings_outfield_range"))
            + _cell("Arm", fld.get("fielding_ratings_outfield_arm"))
            + _cell("Error Rate (lower = better)", fld.get("fielding_ratings_outfield_error"), invert=True)
        )
        note = "Range is the primary value driver in CF; arm matters for suppressing baserunner aggression."

    return f"""
<div class="section">
  <div class="section-title">{title}</div>
  <table style="width:auto;min-width:320px">
    <thead><tr><th class="left">Component</th><th class="left">Grade (20–80)</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="font-size:12px;color:#666;margin-top:6px">{note}</p>
</div>"""


def _build_positional_flexibility(field_positions, primary_pos, player_type):
    if player_type == "pitcher":
        return ""
    playable = {k: v for k, v in field_positions.items() if v >= 40 and k != 1}
    if not playable:
        return ""

    pos_tags = ""
    for pos_int, rating in sorted(playable.items(), key=lambda x: -x[1]):
        pos_label = POS_MAP.get(pos_int, "?")
        is_primary = (pos_int == int(primary_pos or 0))
        c = "tag-good" if rating >= 55 else "tag-warn"
        primary_marker = " (Primary)" if is_primary else ""
        pos_tags += f'<span class="tag {c}" style="margin:2px">{pos_label}: {rating}{primary_marker}</span> '

    return f"""
<div class="section">
  <div class="section-title">Positional Flexibility</div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">{pos_tags}</div>
  <p style="font-size:12px;color:#666;margin-top:6px">
    Ratings ≥ 55 = solid defender; 40–54 = passable; shown on 20–80 scale.
    Multiple positions increase roster flexibility value of this claim.
  </p>
</div>"""


def _build_40man_section(roster_count, candidate):
    max_roster = 40
    spots_left = max(0, max_roster - roster_count)
    needs_dfa = (spots_left == 0)

    status_class = "tag-bad" if needs_dfa else "tag-good"
    status_text = (
        f"FULL — Must DFA a player to make room ({roster_count}/{max_roster})"
        if needs_dfa
        else f"{spots_left} open spot(s) ({roster_count}/{max_roster})"
    )

    active_note = ""
    if needs_dfa:
        active_note = (
            '<p style="font-size:12px;color:#cc2222;margin-top:6px">'
            '<b>Warning:</b> 40-man roster is at capacity. Claiming this player requires DFA\'ing '
            'a current roster member. Consider the least-valuable player at the same position.</p>'
        )

    days_left = candidate.get("days_on_waivers_left") or 0
    claim_window = ""
    if int(candidate.get("is_on_waivers") or 0) == 1 and days_left > 0:
        urgency_color = "#cc2222" if days_left <= 1 else "#cc7700" if days_left <= 2 else "#1a7a1a"
        claim_window = (
            f'<p style="font-size:12px;margin-top:6px">'
            f'Waiver claim window: <b style="color:{urgency_color}">{days_left} day(s) remaining</b> '
            f'— act before the window closes.</p>'
        )
    elif int(candidate.get("designated_for_assignment") or 0) == 1:
        dfa_left = candidate.get("days_on_dfa_left") or 0
        claim_window = (
            f'<p style="font-size:12px;margin-top:6px">'
            f'DFA window: <b style="color:#cc7700">{dfa_left} day(s) remaining</b> '
            f'to claim or release.</p>'
        )

    return f"""
<div class="section">
  <div class="section-title">40-Man Roster Status</div>
  <span class="tag {status_class}">{status_text}</span>
  {active_note}
  {claim_window}
</div>"""


def _build_personality_section(p):
    greed = p.get("greed")
    loyalty = p.get("loyalty")
    work_ethic = p.get("work_ethic")
    intelligence = p.get("intelligence")
    play_for_winner = p.get("personality_play_for_winner")
    local_pop = p.get("local_pop")

    rows = ""
    for label, val, invert in [
        ("Greed", greed, True),
        ("Loyalty", loyalty, False),
        ("Work Ethic", work_ethic, False),
        ("Intelligence", intelligence, False),
    ]:
        if val is None:
            continue
        v = int(val)
        c = (
            "#cc2222" if (invert and v > 150) or (not invert and v < 50)
            else "#1a7a1a" if (invert and v < 80) or (not invert and v > 150)
            else "#cc7700"
        )
        rows += f"<tr><td class='left'>{label}</td><td style='color:{c};font-weight:bold'>{trait_label(v)} ({v})</td></tr>\n"

    if play_for_winner is not None:
        v = int(play_for_winner)
        c = "#cc7700" if v > 150 else "#888"
        rows += f"<tr><td class='left'>Play for Winner</td><td style='color:{c};font-weight:bold'>{trait_label(v)} ({v})</td></tr>\n"

    if local_pop is not None:
        rows += f"<tr><td class='left'>Local Popularity</td><td>{int(local_pop)}/6</td></tr>\n"

    if not rows:
        return ""

    return f"""
<div class="section">
  <div class="section-title">Player Profile</div>
  <table style="width:auto;min-width:260px">
    <thead><tr><th class="left">Trait</th><th class="left">Value</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


def _build_recommendation_placeholder():
    return """
<div class="section">
  <div class="section-title">Claim Recommendation</div>
  <!-- WAIVER_RECOMMENDATION -->
</div>"""


# ─── Main entry point ─────────────────────────────────────────────────────────

def query_waiver_claim(save_name, first_name, last_name):
    """Query all data needed for a waiver claim evaluation.

    Returns the complete data dict, or None if the player is not found.
    Does NOT perform a cache check.
    """
    saves = load_saves_registry()
    save_data = saves.get("saves", {}).get(save_name, {})
    my_team_id = int(save_data.get("my_team_id") or 10)
    my_team_abbr = save_data.get("my_team_abbr") or "your team"

    engine = get_engine(save_name)

    with engine.connect() as conn:
        _row = conn.execute(text(
            "SELECT name, nickname FROM teams WHERE team_id = :tid LIMIT 1"
        ), dict(tid=my_team_id)).mappings().fetchone()
        my_team_name = f"{_row['name']} {_row['nickname']}" if _row else my_team_abbr

        candidate = _lookup_player(conn, first_name, last_name)
        if not candidate:
            return None

        player_id = candidate["player_id"]
        player_type = candidate.get("player_type", "batter")
        position = int(candidate.get("position") or 0)
        player_role = int(candidate.get("role") or 0)
        comparison_positions = get_comparison_positions(position, player_type)

        # Gather all data
        incumbents = _get_incumbents(conn, my_team_id, comparison_positions, player_type, player_role)
        adv = (
            _get_advanced_stats_batter(conn, player_id)
            if player_type == "batter"
            else _get_advanced_stats_pitcher(conn, player_id)
        )
        field_positions = _get_fielding_positions(conn, player_id)
        fielding_details = _get_fielding_details(conn, player_id)
        roster_count = _get_40man_count(conn, my_team_id)

    # Build data dict for agent
    best_incumbent = incumbents[0] if incumbents else None
    worst_incumbent = incumbents[-1] if incumbents else None
    cand_rating = float(candidate.get("rating_overall") or 0)

    def _pct_fmt(v):
        return round(float(v) * 100, 1) if v is not None else None

    data = dict(
        player_name=f"{first_name} {last_name}",
        first_name=first_name,
        last_name=last_name,
        position=POS_MAP.get(position, "?"),
        player_type=player_type,
        role=ROLE_MAP.get(player_role, "—"),
        team_abbr=candidate.get("team_abbr") or "FA",
        age=candidate.get("age"),
        oa=candidate.get("oa"),
        pot=candidate.get("pot"),
        rating_overall=cand_rating,
        war=candidate.get("war"),
        wrc_plus=int(candidate.get("wrc_plus")) if candidate.get("wrc_plus") else None,
        current_salary=fmt_salary(get_current_salary(candidate)),
        years_remaining=get_years_remaining(candidate),
        arb_status=arb_status_label(candidate.get("mlb_service_years")),
        is_on_waivers=int(candidate.get("is_on_waivers") or 0),
        days_waivers_left=candidate.get("days_on_waivers_left") or 0,
        is_dfa=int(candidate.get("designated_for_assignment") or 0),
        dfa_days_left=candidate.get("days_on_dfa_left") or 0,
        flag_injury_risk=bool(candidate.get("flag_injury_risk")),
        prone_label=injury_label(candidate.get("prone_overall") or candidate.get("pr_prone")),
        roster_count=roster_count,
        needs_dfa_to_claim=(roster_count >= 40),
        best_incumbent_name=f"{best_incumbent.get('first_name', '')} {best_incumbent.get('last_name', '')}" if best_incumbent else "None",
        best_incumbent_rating=float(best_incumbent.get("rating_overall") or 0) if best_incumbent else None,
        worst_incumbent_name=f"{worst_incumbent.get('first_name', '')} {worst_incumbent.get('last_name', '')}" if worst_incumbent else "None",
        worst_incumbent_rating=float(worst_incumbent.get("rating_overall") or 0) if worst_incumbent else None,
        rating_vs_best=round(cand_rating - float(best_incumbent.get("rating_overall") or 0), 1) if best_incumbent else None,
        rating_vs_worst=round(cand_rating - float(worst_incumbent.get("rating_overall") or 0), 1) if worst_incumbent else None,
        num_incumbents=len(incumbents),
        positional_flexibility=[POS_MAP.get(k, "?") for k in field_positions if field_positions[k] >= 40 and k != 1],
        no_trade=bool(candidate.get("no_trade")),
        greed=candidate.get("greed"),
        loyalty=candidate.get("loyalty"),
        greed_label=trait_label(candidate.get("greed")),
        loyalty_label=trait_label(candidate.get("loyalty")),
        my_team_abbr=my_team_abbr,
        my_team_name=my_team_name,
        # Advanced stats — batters
        adv_avg_ev=round(float(adv["avg_ev"]), 1) if adv and adv.get("avg_ev") is not None else None,
        adv_hard_hit_pct=_pct_fmt(adv.get("hard_hit_pct")) if adv and adv.get("hard_hit_pct") is not None else None,
        adv_barrel_pct=_pct_fmt(adv.get("barrel_pct")) if adv and adv.get("barrel_pct") is not None else None,
        adv_xwoba=round(float(adv["xwoba"]), 3) if adv and adv.get("xwoba") is not None else None,
        adv_k_pct=_pct_fmt(adv.get("k_pct")) if adv and adv.get("k_pct") is not None else None,
        adv_bb_pct=_pct_fmt(adv.get("bb_pct")) if adv and adv.get("bb_pct") is not None else None,
        adv_wrc_plus_vs_lhp=int(adv["wrc_plus_vs_lhp"]) if adv and adv.get("wrc_plus_vs_lhp") is not None else None,
        adv_wrc_plus_vs_rhp=int(adv["wrc_plus_vs_rhp"]) if adv and adv.get("wrc_plus_vs_rhp") is not None else None,
        adv_pa_vs_lhp=adv.get("pa_vs_lhp") if adv else None,
        adv_pa_vs_rhp=adv.get("pa_vs_rhp") if adv else None,
        # Advanced stats — pitchers
        adv_era=round(float(adv["era"]), 2) if adv and adv.get("era") is not None else None,
        adv_fip=round(float(adv["fip"]), 2) if adv and adv.get("fip") is not None else None,
        adv_xfip=round(float(adv["xfip"]), 2) if adv and adv.get("xfip") is not None else None,
        adv_k_bb_pct=_pct_fmt(adv.get("k_bb_pct")) if adv and adv.get("k_bb_pct") is not None else None,
        adv_gb_pct=_pct_fmt(adv.get("gb_pct")) if adv and adv.get("gb_pct") is not None else None,
        adv_hard_hit_pct_against=_pct_fmt(adv.get("hard_hit_pct_against")) if adv and adv.get("hard_hit_pct_against") is not None else None,
        adv_barrel_pct_against=_pct_fmt(adv.get("barrel_pct_against")) if adv and adv.get("barrel_pct_against") is not None else None,
        adv_xwoba_against=round(float(adv["xwoba_against"]), 3) if adv and adv.get("xwoba_against") is not None else None,
        adv_era_vs_lhb=round(float(adv["era_vs_lhb"]), 2) if adv and adv.get("era_vs_lhb") is not None else None,
        adv_era_vs_rhb=round(float(adv["era_vs_rhb"]), 2) if adv and adv.get("era_vs_rhb") is not None else None,
        adv_fip_vs_lhb=round(float(adv["fip_vs_lhb"]), 2) if adv and adv.get("fip_vs_lhb") is not None else None,
        adv_fip_vs_rhb=round(float(adv["fip_vs_rhb"]), 2) if adv and adv.get("fip_vs_rhb") is not None else None,
        adv_bf_vs_lhb=adv.get("bf_vs_lhb") if adv else None,
        adv_bf_vs_rhb=adv.get("bf_vs_rhb") if adv else None,
        # Private keys for HTML generation in generate_waiver_claim_report
        _candidate=candidate,
        _adv=adv,
        _incumbents=incumbents,
        _field_positions=field_positions,
        _fielding_details=fielding_details,
        _roster_count=roster_count,
        _player_id=player_id,
        _player_type=player_type,
        _position=position,
        _player_role=player_role,
        _comparison_positions=comparison_positions,
        _my_team_name=my_team_name,
    )

    return data


def generate_waiver_claim_report(save_name, first_name, last_name, raw_args=""):
    """Generate a waiver claim evaluation report.

    Returns:
        (None, None)   — player not found
        (path, None)   — cache hit, path is existing report
        (path, dict)   — newly generated report + data dict for agent summary
    """
    engine = get_engine(save_name)

    with engine.connect() as conn:
        candidate = _lookup_player(conn, first_name, last_name)
        if not candidate:
            return None, None

        player_id = candidate["player_id"]

        # Cache check
        existing = find_existing_waiver_report(player_id, save_name, raw_args)
        if existing:
            return existing, None

    # Cache miss — query all data
    data = query_waiver_claim(save_name, first_name, last_name)
    if data is None:
        return None, None

    # Extract private keys for HTML construction
    candidate = data.pop("_candidate")
    adv = data.pop("_adv")
    incumbents = data.pop("_incumbents")
    field_positions = data.pop("_field_positions")
    fielding_details = data.pop("_fielding_details")
    roster_count = data.pop("_roster_count")
    player_id = data.pop("_player_id")
    player_type = data.pop("_player_type")
    position = data.pop("_position")
    player_role = data.pop("_player_role")
    comparison_positions = data.pop("_comparison_positions")
    my_team_name = data.pop("_my_team_name")

    # Build HTML
    last_import = get_last_import_iso_for_save(save_name)
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    css = get_report_css("1200px")
    header_html = _build_candidate_header(candidate, adv, last_import, generated_at)
    ratings_html = _build_ratings_section(candidate)
    contract_html = _build_contract_section(candidate)
    adv_html = (
        _build_adv_stats_batter(adv)
        if player_type == "batter"
        else _build_adv_stats_pitcher(adv)
    )
    incumbents_html = _build_incumbents_section(incumbents, candidate, comparison_positions, my_team_name)
    fielding_html = _build_fielding_section(fielding_details, position)
    flex_html = _build_positional_flexibility(field_positions, position, player_type)
    roster_html = _build_40man_section(roster_count, candidate)
    personality_html = _build_personality_section(candidate)
    recommendation_html = _build_recommendation_placeholder()

    full_name = f"{first_name}_{last_name}".lower().replace(" ", "_")
    title = html.escape(f"Waiver Claim: {first_name} {last_name}")
    esc_first = html.escape(first_name)
    esc_last = html.escape(last_name)
    esc_save = html.escape(save_name)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="ootp-skill" content="waiver-claim">
  <meta name="ootp-args" content="{esc_first} {esc_last}">
  <meta name="ootp-args-display" content="">
  <meta name="ootp-save" content="{esc_save}">
  <meta name="ootp-generated" content="{html.escape(generated_at)}">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>
<div class="container">
  {header_html}
  {recommendation_html}
  {incumbents_html}
  {adv_html}
  {fielding_html}
  {ratings_html}
  {contract_html}
  {flex_html}
  {roster_html}
  {personality_html}
</div>
</body>
</html>"""

    reports_dir = get_reports_dir(save_name, "waiver_claims")
    report_path = reports_dir / report_filename(f"waiver_{player_id}", dict(raw_args=raw_args.strip().lower()))
    write_report_html(report_path, html_doc)

    data["report_path"] = str(report_path)
    return str(report_path), data


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print("Usage: waiver_wire.py <save_name> <first_name> <last_name> [last_name...]")
        sys.exit(1)

    save = sys.argv[1]
    fn = sys.argv[2]
    ln = " ".join(sys.argv[3:])
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    path, data = generate_waiver_claim_report(save, fn, ln)
    if path is None:
        print("PLAYER_NOT_FOUND")
    elif data is None:
        print(f"CACHED:{path}")
    else:
        print(f"GENERATED:{path}")
        if data:
            for k, v in data.items():
                print(f"{k}={v}")
