#!/usr/bin/env python3
"""Trade target search report generator for OOTP Baseball."""

import html
import json
import re
from datetime import datetime
from pathlib import Path

from config import (
    GRADE_A_PLUS, GRADE_A, GRADE_B_PLUS, GRADE_B, GRADE_C_PLUS, GRADE_C, GRADE_D,
    INJURY_IRON_MAN_MAX, INJURY_DURABLE_MAX, INJURY_NORMAL_MAX, INJURY_FRAGILE_MAX,
    TRADE_POSITION_ADJUSTMENTS, TRADE_TIER2_OA_ABOVE,
)
from ootp_db_constants import MLB_LEAGUE_ID, POS_MAP, BATS_MAP, THROWS_MAP
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


def injury_label(val):
    if val is None:
        return "Unknown"
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


def get_position_adjustment(position_code, role_code=None):
    """Return OA trade value adjustment for a position/role from config.

    Pitchers (position=1) are keyed by role: "sp" (11), "closer" (13), "rp" (all others).
    Position players are keyed by their integer position code.
    """
    if int(position_code or 0) == 1:
        if role_code == 11:
            key = "sp"
        elif role_code == 13:
            key = "closer"
        else:
            key = "rp"
    else:
        key = int(position_code) if position_code is not None else 0
    return TRADE_POSITION_ADJUSTMENTS.get(key, 0)


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
           p.bats, p.throws, p.role,
           t.abbr AS team_abbr,
           pc.years, pc.current_year, pc.no_trade,
           pc.salary0, pc.salary1, pc.salary2, pc.salary3, pc.salary4,
           pc.salary5, pc.salary6, pc.salary7, pc.salary8, pc.salary9,
           prs.mlb_service_years,
           pr.confidence
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
    "bats", "throws", "role",
    "team_abbr",
    "years", "current_year", "no_trade",
    "salary0", "salary1", "salary2", "salary3", "salary4",
    "salary5", "salary6", "salary7", "salary8", "salary9",
    "mlb_service_years",
    "confidence",
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


def lookup_trade_context(save_name, player_name=None, mode="offering"):
    """Pre-flight lookup for trade target search.

    Loads team identity, optionally matches a player by name, and fetches
    positional needs for the managed team (offering mode only).

    Prints to stdout for the agent to parse:
      MY_TEAM_ID=<id>
      MY_TEAM_ABBR=<abbr>
      MY_TEAM_NAME=<name>
      PLAYER=<player_id>|<first>|<last>|<pos>|<age>|<oa>|<pot>|<rating_overall>|
             <player_type>|<wrc_fip>|<war>|<yrs_remaining>|<salary>|<svc_years>|<team_abbr>
      NEED=<position>|<cnt>|<avg_rating>|<best_rating>  (offering mode, sorted by avg_rating)
    """
    from shared_css import load_saves_registry

    registry = load_saves_registry()
    save_data = registry.get("saves", {}).get(save_name, {})
    my_team_id = int(save_data.get("my_team_id") or 10)
    my_team_abbr = save_data.get("my_team_abbr") or "???"

    engine = get_engine(save_name)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT name, nickname FROM teams WHERE team_id = :tid LIMIT 1"),
            dict(tid=my_team_id),
        ).mappings().fetchone()
        my_team_name = f"{row['name']} {row['nickname']}" if row else my_team_abbr

        print(f"MY_TEAM_ID={my_team_id}")
        print(f"MY_TEAM_ABBR={my_team_abbr}")
        print(f"MY_TEAM_NAME={my_team_name}")
        adj_export = {str(k): v for k, v in TRADE_POSITION_ADJUSTMENTS.items()}
        print(f"TRADE_POS_ADJUSTMENTS={json.dumps(adj_export)}")
        print(f"TRADE_TIER2_OA_ABOVE={TRADE_TIER2_OA_ABOVE}")

        if player_name:
            parts = player_name.strip().split(None, 1)
            if len(parts) == 2:
                first, last = parts[0], parts[1]
                if mode == "acquiring":
                    team_filter = "p.team_id != :tid AND p.league_id = :league_id"
                    query_params = dict(tid=my_team_id, league_id=MLB_LEAGUE_ID, first=first, last=last)
                else:
                    team_filter = "p.team_id = :tid"
                    query_params = dict(tid=my_team_id, first=first, last=last)

                players = conn.execute(text(
                    _SELECT + _FROM
                    + f"WHERE {team_filter} AND p.free_agent = 0 AND p.retired = 0 "
                    "AND p.first_name = :first AND p.last_name = :last "
                    "ORDER BY pr.rating_overall DESC LIMIT 5"
                ), query_params).fetchall()

                for r in players:
                    d = row_to_dict(r)
                    yrs_rem = get_years_remaining(d)
                    sal = get_current_salary(d) or 0
                    print(
                        f"PLAYER={d['player_id']}|{d['first_name']}|{d['last_name']}|"
                        f"{d['position']}|{d['age']}|{d['oa']}|{d['pot']}|"
                        f"{round(float(d['rating_overall'] or 0), 1)}|{d['player_type']}|"
                        f"{d['wrc_plus']}|{d['war']}|{yrs_rem}|{sal}|"
                        f"{d['mlb_service_years']}|{d['team_abbr']}"
                    )
                    pos_adj = get_position_adjustment(d["position"], d.get("role"))
                    print(f"POSITION_DISCOUNT={pos_adj}")

        if mode == "offering":
            needs = conn.execute(text(
                "SELECT pr.position, COUNT(*) AS cnt, "
                "ROUND(AVG(pr.rating_overall), 1) AS avg_rating, "
                "MAX(pr.rating_overall) AS best_rating "
                "FROM team_roster tr "
                "JOIN player_ratings pr ON pr.player_id = tr.player_id "
                "WHERE tr.team_id = :tid AND tr.list_id IN (1, 2) "
                "GROUP BY pr.position "
                "ORDER BY avg_rating ASC"
            ), dict(tid=my_team_id)).fetchall()
            for r in needs:
                pos, cnt, avg_r, best_r = r
                print(f"NEED={pos}|{cnt}|{avg_r}|{best_r}")


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
        f"{team_col}<th>Rating</th><th>Conf</th>{extra}"
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
        rating = float(r["rating_overall"] or 0)

        sal_str = fmt_salary(get_current_salary(r))
        yrs_left = get_years_remaining(r)
        no_trade = r.get("no_trade") or 0
        we_v = r.get("work_ethic") or 0
        iq_v = r.get("intelligence") or 0

        flags = ""
        if r.get("flag_leader"):
            flags += '<span title="Leader — positive clubhouse presence">🏆</span> '
        if r.get("flag_high_ceiling"):
            flags += '<span title="High Ceiling — significant upside remaining">📈</span> '
        if no_trade:
            flags += '<span title="No-Trade Clause — requires player consent">🔒</span> '
        if we_v > 160:
            flags += '<span title="Elite Work Ethic — likely to develop and maintain skills">⚡</span> '
        if iq_v > 160:
            flags += '<span title="High Baseball IQ — reads the game well, adjusts quickly">🧠</span>'

        extra_cells = "".join(_fmt_score_cell(r.get(col)) for col, _ in (highlight or []))
        team_cell = f"<td>{r.get('team_abbr', '')}</td>" if show_team else ""
        conf = float(r.get("confidence") or 0.0)
        conf_color = "#1a7a1a" if conf >= 0.9 else "#cc7700" if conf >= 0.5 else "#cc2222"
        bg = row_bg(rating)

        html += (
            f'<tr style="background:{bg}">'
            f"<td>{i}</td>"
            f'<td class="left"><b>{r["first_name"]} {r["last_name"]}</b></td>'
            f"<td>{pos_name}</td>"
            f"<td>{int(r['age']) if r['age'] else '?'}</td>"
            f"{team_cell}"
            f"<td>{grade_badge(rating)}</td>"
            f'<td style="font-weight:bold;color:{conf_color}">{conf:.0%}</td>'
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


def query_trade_targets(save_name, offer_label, offered_where, target_base_where,
                        oa_floor, oa_ceil, my_team_id,
                        mode="offering", target_join="", order_by="pr.rating_overall DESC",
                        limit=25, highlight=None):
    """Query offered and tiered target players for a trade evaluation.

    target_base_where: SQL WHERE fragment with position/type filters only — no OA filter.
    oa_floor / oa_ceil: main value band; Python builds tier ranges from these.

    Returns dict(offered=list, tier1=list, tier2=list).
    """
    oa_floor = int(oa_floor)
    oa_ceil = int(oa_ceil)
    limit = int(limit)
    _ALLOWED_ORDER_BY = {
        "pr.rating_overall DESC",
        "pr.rating_overall ASC",
        "pr.oa DESC",
        "pr.oa ASC",
    }
    if order_by not in _ALLOWED_ORDER_BY:
        order_by = "pr.rating_overall DESC"
    engine = get_engine(save_name)
    tier2_ceil = oa_ceil + TRADE_TIER2_OA_ABOVE

    if mode == "acquiring":
        offered_team_filter = f"p.team_id != {my_team_id} AND p.league_id = {MLB_LEAGUE_ID}"
        target_team_filter = f"p.team_id = {my_team_id}"
    else:
        offered_team_filter = f"p.team_id = {my_team_id}"
        target_team_filter = f"p.team_id != {my_team_id} AND p.league_id = {MLB_LEAGUE_ID}"

    offered_sql = (
        _SELECT + _FROM
        + f"""
        WHERE p.free_agent = 0 AND p.retired = 0
          AND {offered_team_filter}
          AND ({offered_where})
        ORDER BY pr.rating_overall DESC
        LIMIT 10
        """
    )

    def _tier_sql(oa_lo, oa_hi):
        return (
            _SELECT + _FROM
            + (f"\n{target_join}" if target_join else "")
            + f"""
            WHERE p.free_agent = 0 AND p.retired = 0
              AND {target_team_filter}
              AND ({target_base_where})
              AND pr.oa BETWEEN {oa_lo} AND {oa_hi}
            ORDER BY {order_by}
            LIMIT {limit}
            """
        )

    with engine.connect() as conn:
        offered = [row_to_dict(r) for r in conn.execute(text(offered_sql)).fetchall()]
        tier1 = [row_to_dict(r) for r in conn.execute(text(_tier_sql(oa_floor, oa_ceil))).fetchall()]
        tier2 = [row_to_dict(r) for r in conn.execute(text(_tier_sql(oa_ceil + 1, tier2_ceil))).fetchall()]

    return dict(offered=offered, tier1=tier1, tier2=tier2)


def generate_trade_targets_report(
    save_name,
    offer_label,
    offered_where,
    target_base_where,
    oa_floor,
    oa_ceil,
    my_team_id,
    mode="offering",
    target_join="",
    highlight=None,
):
    """Generate a trade targets HTML report with value-tiered results.

    offer_label:       Human-readable label, e.g. "Johnny Bench".
    offered_where:     SQL WHERE fragment for the player(s) on the offer side.
    target_base_where: SQL WHERE fragment for position/type filters only — no OA filter.
    oa_floor / oa_ceil: Main value band (already position-adjusted by the agent).
                       Python extends upward for the add-on tier internally.
    my_team_id:        The managed team's team_id (read from saves.json).
    mode:              "offering" — you're trading away your player, seeking returns.
                       "acquiring" — you want someone else's player; show what you'd give up.
    target_join:       Optional JOIN clause for advanced stats tables.
    highlight:         List of (col_key, display_label) tuples for extra columns, or None.

    Returns (path_str, dict(offered=list, tier1=list, tier2=list)).
    """
    last_import = get_last_import_iso_for_save(save_name)
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    tier2_ceil = oa_ceil + TRADE_TIER2_OA_ABOVE

    result = query_trade_targets(save_name, offer_label, offered_where, target_base_where,
                                  oa_floor, oa_ceil, my_team_id, mode, target_join,
                                  "pr.rating_overall DESC", 25, highlight)
    offered = result["offered"]
    tier1 = result["tier1"]
    tier2 = result["tier2"]

    if offered:
        p = offered[0]
        _trade_base = f"trade_{p['player_id']}"
    else:
        _trade_base = "trade_offer"
    args_key = {
        "label": offer_label,
        "mode": mode,
        "offered_where": offered_where,
        "target_base_where": target_base_where,
        "oa_floor": oa_floor,
        "oa_ceil": oa_ceil,
        "target_join": target_join,
        "highlight": highlight,
    }

    offer_label_esc = html.escape(offer_label, quote=True)
    if mode == "acquiring":
        offered_show_team = True
        target_show_team = False
        offered_section_title = "Player You're Targeting"
        tier1_section_title = f"What You'd Need to Give Up — Direct Match ({len(tier1)})"
        tier2_section_title = f"What You'd Need to Give Up — Add-On Required ({len(tier2)})"
        page_meta = f"Acquiring: {offer_label_esc}"
    else:
        offered_show_team = False
        target_show_team = True
        offered_section_title = "What You're Offering"
        tier1_section_title = f"Straight Swap Candidates ({len(tier1)})"
        tier2_section_title = f"Add-On Required ({len(tier2)})"
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

    all_targets = tier1 + tier2

    key_header_t1 = _key_header_for_rows(tier1)
    tier1_header = build_table_header(show_team=target_show_team, key_header=key_header_t1, highlight=highlight)
    tier1_rows_html = build_table_rows(tier1, show_team=target_show_team, highlight=highlight)

    key_header_t2 = _key_header_for_rows(tier2)
    tier2_header = build_table_header(show_team=target_show_team, key_header=key_header_t2, highlight=highlight)
    tier2_rows_html = build_table_rows(tier2, show_team=target_show_team, highlight=highlight)

    # Tier 1 block
    if tier1:
        tier1_block = f"<table>\n{tier1_header}\n{tier1_rows_html}\n</table>"
    else:
        tier1_block = (
            '<div style="background:#fff3cd;border:1px solid #ffc107;padding:12px 16px;'
            'border-radius:4px;font-size:13px;margin:4px 0">'
            "<b>No straight-swap candidates found</b> at this value level. "
            'See "Add-On Required" below for players reachable with an extra piece.</div>'
        )

    # Tier 2 block
    if tier2:
        tier2_block = f"<table>\n{tier2_header}\n{tier2_rows_html}\n</table>"
    else:
        tier2_block = '<p style="color:#888;font-size:13px;margin:4px 0">No candidates in this range.</p>'

    # Spotlights
    spotlight = ""
    spotlight_list = offered if mode == "acquiring" else all_targets
    no_trade_list = [r for r in spotlight_list if r.get("no_trade")]
    injury_list = [r for r in all_targets if (r.get("prone_overall") or 0) > 150]
    elite_tier2 = [r for r in tier2 if (r.get("rating_overall") or 0) >= 75]

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
    if elite_tier2 and mode != "acquiring":
        names = ", ".join(f"{r['first_name']} {r['last_name']}" for r in elite_tier2)
        spotlight += (
            f'<div style="background:#f0fff0;border:1px solid #88cc88;padding:10px 14px;'
            f'border-radius:4px;margin:8px 0;font-size:13px">'
            f"<b>⭐ Premium Add-On Targets (Rating ≥75):</b> {names} — "
            f"would require a meaningful package, not just a prospect.</div>"
        )

    total = len(tier1) + len(tier2)
    _ootp_kwargs_esc = json.dumps(dict(
        offered_where=offered_where, target_base_where=target_base_where,
        oa_floor=oa_floor, oa_ceil=oa_ceil,
        my_team_id=my_team_id, mode=mode,
        target_join=target_join, highlight=highlight
    )).replace('"', '&quot;')
    _args_esc = offer_label.replace("&", "&amp;").replace('"', "&quot;")
    _ootp_meta = (
        '<meta name="ootp-skill" content="trade-targets">'
        f'<meta name="ootp-args" content="{_args_esc}">'
        f'<meta name="ootp-args-display" content="{_args_esc}">'
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
  <div class="import-ts">{len(tier1)} direct match{"es" if len(tier1) != 1 else ""},
    {len(tier2)} with add-on &bull; OA band {oa_floor}–{oa_ceil} (direct) /
    {oa_ceil + 1}–{tier2_ceil} (add-on)
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
  <div class="section-title">{tier1_section_title}</div>
  <div style="font-size:13px;color:#555;margin:-4px 0 10px">
    OA {oa_floor}–{oa_ceil} — direct value match; realistic straight trades.
  </div>
  {tier1_block}
</div>

<div class="section">
  <div class="section-title">{tier2_section_title}</div>
  <div style="font-size:13px;color:#555;margin:-4px 0 10px">
    OA {oa_ceil + 1}–{tier2_ceil} — value gap requires a prospect, secondary player, or cash to close.
  </div>
  {tier2_block}
</div>

{spotlight}

<div style="font-size:12px;color:#888;margin:8px 16px 16px;line-height:1.8">
  <b>Flag legend:</b>&nbsp;
  🏆 Leader &nbsp;&bull;&nbsp;
  📈 High Ceiling &nbsp;&bull;&nbsp;
  🔒 No-Trade Clause &nbsp;&bull;&nbsp;
  ⚡ Elite Work Ethic &nbsp;&bull;&nbsp;
  🧠 High Baseball IQ
</div>

</div>
</body></html>"""

    report_path = get_reports_dir(save_name, "trade_targets") / report_filename(_trade_base, args_key)
    write_report_html(report_path, html_doc)

    return str(report_path), dict(offered=offered, tier1=tier1, tier2=tier2)
