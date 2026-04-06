#!/usr/bin/env python3
"""Generate HTML player reports from OOTP database."""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from report_write import write_report_html
from shared_css import db_name_from_save, get_engine, get_report_css, get_reports_dir
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAST_IMPORT_PATH = PROJECT_ROOT / ".last_import"

WOBA_WEIGHTS = dict(bb=0.69, hbp=0.72, s=0.87, d=1.27, t=1.62, hr=2.10)

POS_MAP = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
BATS_MAP = {1: "R", 2: "L", 3: "S"}
THROWS_MAP = {1: "R", 2: "L"}



def get_last_import_time():
    if LAST_IMPORT_PATH.exists():
        return LAST_IMPORT_PATH.read_text().strip()
    return None


def calc_rates(ab, h, d, t, hr, bb, k, hp, sf, pa, lg=None):
    if ab == 0 or pa == 0:
        return {}
    singles = h - d - t - hr
    ba = h / ab
    obp = (h + bb + hp) / (ab + bb + hp + sf)
    slg = (singles + 2 * d + 3 * t + 4 * hr) / ab
    ops = obp + slg
    iso = slg - ba
    k_pct = k / pa * 100
    bb_pct = bb / pa * 100
    babip_denom = ab - k - hr + sf
    babip = (h - hr) / babip_denom if babip_denom > 0 else 0.0

    woba_num = (WOBA_WEIGHTS["bb"] * bb + WOBA_WEIGHTS["hbp"] * hp +
                WOBA_WEIGHTS["s"] * singles + WOBA_WEIGHTS["d"] * d +
                WOBA_WEIGHTS["t"] * t + WOBA_WEIGHTS["hr"] * hr)
    woba_den = ab + bb + hp + sf
    woba = woba_num / woba_den if woba_den > 0 else 0.0

    wrc_plus = None
    ops_plus = None
    if lg:
        lg_ab, lg_h, lg_d, lg_t, lg_hr, lg_bb, lg_hp, lg_sf, lg_pa, lg_r = lg
        lg_singles = lg_h - lg_d - lg_t - lg_hr
        lg_obp = (lg_h + lg_bb + lg_hp) / (lg_ab + lg_bb + lg_hp + lg_sf)
        lg_slg = (lg_singles + 2 * lg_d + 3 * lg_t + 4 * lg_hr) / lg_ab
        lg_woba_num = (WOBA_WEIGHTS["bb"] * lg_bb + WOBA_WEIGHTS["hbp"] * lg_hp +
                       WOBA_WEIGHTS["s"] * lg_singles + WOBA_WEIGHTS["d"] * lg_d +
                       WOBA_WEIGHTS["t"] * lg_t + WOBA_WEIGHTS["hr"] * lg_hr)
        lg_woba = lg_woba_num / (lg_ab + lg_bb + lg_hp + lg_sf)
        lg_rpa = lg_r / lg_pa
        wrc_plus = ((woba - lg_woba) / 1.15 + lg_rpa) / lg_rpa * 100
        ops_plus = 100 * (obp / lg_obp + slg / lg_slg - 1)

    return dict(ba=ba, obp=obp, slg=slg, ops=ops, iso=iso, k_pct=k_pct,
                bb_pct=bb_pct, babip=babip, woba=woba, wrc_plus=wrc_plus, ops_plus=ops_plus)


def calc_pitching_rates(ip, ha, hra, bb, k, er, bf, hp, gb, fb, lg_pitch=None):
    """Compute ERA, FIP, xFIP, WHIP, K%, BB%, etc. for a pitcher season."""
    if ip == 0 or bf == 0:
        return {}
    era = er / ip * 9
    whip = (bb + ha) / ip
    k_pct = k / bf * 100
    bb_pct = bb / bf * 100
    k_bb_pct = k_pct - bb_pct
    hr_9 = hra / ip * 9
    k_9 = k / ip * 9
    bb_9 = bb / ip * 9
    babip_denom = bf - k - hra - bb - hp  # approximate AB - K - HR
    babip = (ha - hra) / babip_denom if babip_denom > 0 else 0.0
    total_balls = gb + fb
    gb_pct = gb / total_balls * 100 if total_balls > 0 else 0.0

    # FIP: (13*HR + 3*(BB+HBP) - 2*K) / IP + cFIP
    # cFIP = lgERA - (13*lgHR + 3*(lgBB+lgHBP) - 2*lgK) / lgIP
    fip = None
    xfip = None
    if lg_pitch:
        lg_ip, lg_hra, lg_bb, lg_hp, lg_k, lg_er = lg_pitch
        if lg_ip > 0:
            lg_era = lg_er / lg_ip * 9
            cfip = lg_era - (13 * lg_hra + 3 * (lg_bb + lg_hp) - 2 * lg_k) / lg_ip
            fip = (13 * hra + 3 * (bb + hp) - 2 * k) / ip + cfip
            # xFIP: replace HR with league-average HR/FB rate
            lg_fb_rate = lg_hra / (lg_hra + (lg_ip * 3))  # rough approximation
            if fb > 0:
                expected_hr = fb * (lg_hra / (lg_ip * 3)) * 3  # rough lg HR/FB
                xfip = (13 * expected_hr + 3 * (bb + hp) - 2 * k) / ip + cfip

    return dict(era=era, whip=whip, k_pct=k_pct, bb_pct=bb_pct, k_bb_pct=k_bb_pct,
                hr_9=hr_9, k_9=k_9, bb_9=bb_9, babip=babip, gb_pct=gb_pct,
                fip=fip, xfip=xfip)


def oa_pot_badges(val):
    """Return OA/POT badge HTML. Shows N/A with tooltip for free agents (no players_value entry)."""
    if val:
        return (f'<span class="badge oa">OA {val[2]}</span>'
                f'<span class="badge pot">POT {val[3]}</span>')
    return ('<span class="badge oa" title="Not available for free agents">OA N/A</span>'
            '<span class="badge pot" title="Not available for free agents">POT N/A</span>')


def rating_color(val):
    if val >= 70:
        return "#1a7a1a"
    if val >= 60:
        return "#4a9a2a"
    if val >= 50:
        return "#888"
    if val >= 40:
        return "#cc7700"
    return "#cc2222"


def rating_td(val):
    c = rating_color(val)
    return f'<td style="color:{c};font-weight:bold;text-align:center">{val}</td>'


def fmt_rate(val, places=3):
    if val is None:
        return "\u2014"
    return f"{val:.{places}f}"


def fmt_pct(val):
    if val is None:
        return "\u2014"
    return f"{val:.1f}%"


def fmt_int(val):
    if val is None:
        return "\u2014"
    return str(int(round(val)))


def fetch_common_data(conn, player_id):
    """Fetch player info, team, value, fielding — shared by batter and pitcher reports."""
    data = {}

    row = conn.execute(text(
        "SELECT player_id, first_name, last_name, team_id, position, age, bats, throws "
        "FROM players WHERE player_id = :pid"), dict(pid=player_id)).fetchone()
    data["player"] = row

    tid = row[3]
    if tid and tid > 0:
        data["team"] = conn.execute(text(
            "SELECT name, nickname, abbr FROM teams WHERE team_id = :tid"),
            dict(tid=tid)).fetchone()
    else:
        data["team"] = ("Free Agent", "", "FA")

    data["value"] = conn.execute(text(
        "SELECT oa, pot, oa_rating, pot_rating FROM players_value WHERE player_id = :pid"),
        dict(pid=player_id)).fetchone()

    data["fielding"] = conn.execute(text(
        "SELECT fielding_ratings_infield_range, fielding_ratings_infield_arm, "
        "fielding_ratings_turn_doubleplay, fielding_ratings_infield_error, "
        "fielding_ratings_outfield_range, fielding_ratings_outfield_arm, "
        "fielding_ratings_outfield_error, fielding_ratings_catcher_arm, "
        "fielding_ratings_catcher_ability, fielding_ratings_catcher_framing, "
        "fielding_rating_pos1, fielding_rating_pos2, fielding_rating_pos3, "
        "fielding_rating_pos4, fielding_rating_pos5, fielding_rating_pos6, "
        "fielding_rating_pos7, fielding_rating_pos8, fielding_rating_pos9, "
        "fielding_rating_pos1_pot, fielding_rating_pos2_pot, fielding_rating_pos3_pot, "
        "fielding_rating_pos4_pot, fielding_rating_pos5_pot, fielding_rating_pos6_pot, "
        "fielding_rating_pos7_pot, fielding_rating_pos8_pot, fielding_rating_pos9_pot "
        "FROM players_fielding WHERE player_id = :pid"), dict(pid=player_id)).fetchone()

    # Team abbrs (for career tables)
    rows = conn.execute(text("SELECT team_id, abbr FROM teams")).fetchall()
    data["team_abbrs"] = dict(rows)

    # League averages (batting, for wRC+/OPS+ and also for pitching cFIP)
    lg = {}
    rows = conn.execute(text(
        "SELECT thbs.year, SUM(thbs.ab), SUM(thbs.h), SUM(thbs.d), SUM(thbs.t), "
        "SUM(thbs.hr), SUM(thbs.bb), SUM(thbs.hp), SUM(thbs.sf), SUM(thbs.pa), SUM(thbs.r) "
        "FROM team_history_batting_stats thbs "
        "JOIN team_history th ON th.team_id = thbs.team_id AND th.year = thbs.year AND th.league_id = 203 "
        "WHERE thbs.level_id = 1 AND thbs.split_id = 1 "
        "GROUP BY thbs.year")).fetchall()
    for r in rows:
        lg[int(r[0])] = tuple(int(x) for x in r[1:])

    cur = conn.execute(text(
        "SELECT SUM(tbs.ab), SUM(tbs.h), SUM(tbs.d), SUM(tbs.t), SUM(tbs.hr), "
        "SUM(tbs.bb), SUM(tbs.hp), SUM(tbs.sf), SUM(tbs.pa), SUM(tbs.r) "
        "FROM team_batting_stats tbs "
        "JOIN team_relations tr ON tr.team_id = tbs.team_id AND tr.league_id = 203 "
        "WHERE tbs.level_id = 1 AND tbs.split_id = 0")).fetchone()
    if cur and cur[0]:
        # Use current year from league_history or pitching history
        yr_row = conn.execute(text(
            "SELECT MAX(year) FROM team_history WHERE league_id = 203")).fetchone()
        # Current season is one after the latest history year, or derive from career data
        cur_year_candidates = []
        if yr_row and yr_row[0]:
            cur_year_candidates.append(int(yr_row[0]) + 1)
        lg_cur_year = max(cur_year_candidates) if cur_year_candidates else 2028
        lg[lg_cur_year] = tuple(int(x) for x in cur)

    data["lg_avgs"] = lg

    # League pitching averages for cFIP calculation
    lg_pitch = {}
    rows = conn.execute(text(
        "SELECT thps.year, SUM(thps.ip), SUM(thps.hra), SUM(thps.bb), SUM(thps.hp), "
        "SUM(thps.k), SUM(thps.er) "
        "FROM team_history_pitching_stats thps "
        "JOIN team_history th ON th.team_id = thps.team_id AND th.year = thps.year AND th.league_id = 203 "
        "WHERE thps.level_id = 1 AND thps.split_id = 1 "
        "GROUP BY thps.year")).fetchall()
    for r in rows:
        lg_pitch[int(r[0])] = tuple(float(x) for x in r[1:])

    cur_p = conn.execute(text(
        "SELECT SUM(tps.ip), SUM(tps.hra), SUM(tps.bb), SUM(tps.hp), SUM(tps.k), SUM(tps.er) "
        "FROM team_pitching_stats tps "
        "JOIN team_relations tr ON tr.team_id = tps.team_id AND tr.league_id = 203 "
        "WHERE tps.level_id = 1 AND tps.split_id = 1")).fetchone()
    if cur_p and cur_p[0]:
        lg_pitch[lg_cur_year] = tuple(float(x) for x in cur_p)

    data["lg_pitch"] = lg_pitch

    return data


def fetch_batter_data(conn, player_id, common=None):
    """Fetch batting-specific data. If common is provided, merge into it."""
    data = common if common else fetch_common_data(conn, player_id)

    # Batting talent ratings
    row = conn.execute(text(
        "SELECT batting_ratings_talent_contact, batting_ratings_talent_gap, "
        "batting_ratings_talent_power, batting_ratings_talent_eye, "
        "batting_ratings_talent_strikeouts, batting_ratings_talent_babip, "
        "batting_ratings_misc_bunt, batting_ratings_misc_bunt_for_hit, "
        "running_ratings_speed, running_ratings_stealing, "
        "running_ratings_baserunning, running_ratings_stealing_rate "
        "FROM players_batting WHERE player_id = :pid"), dict(pid=player_id)).fetchone()
    data["batting_ratings"] = row

    # Batter advanced stats (current season)
    row = conn.execute(text(
        "SELECT * FROM batter_advanced_stats WHERE player_id = :pid"),
        dict(pid=player_id)).fetchone()
    data["advanced"] = dict(zip(row._fields, row)) if row else None

    # Current (ground-truth) batting ratings from players_scouted_ratings.
    # Only present when "Additional complete scouted ratings" is enabled in OOTP export.
    try:
        sr = conn.execute(text(
            "SELECT batting_ratings_overall_contact, batting_ratings_overall_gap, "
            "batting_ratings_overall_power, batting_ratings_overall_eye, "
            "batting_ratings_overall_strikeouts, batting_ratings_overall_babip "
            "FROM players_scouted_ratings "
            "WHERE player_id = :pid AND scouting_team_id = 0"),
            dict(pid=player_id)).fetchone()
        data["scouted_bat"] = sr
    except Exception:
        data["scouted_bat"] = None

    # Career batting overall
    data["career_overall"] = conn.execute(text(
        "SELECT year, team_id, g, pa, ab, h, d, t, hr, bb, k, rbi, sb, cs, hp, sf, sh, r, war, wpa "
        "FROM players_career_batting_stats "
        "WHERE player_id = :pid AND split_id = 1 AND league_id = 203 AND level_id = 1 "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Career vs LHP
    data["career_lhp"] = conn.execute(text(
        "SELECT year, team_id, g, pa, ab, h, d, t, hr, bb, k, rbi, sb, cs, hp, sf, sh, r "
        "FROM players_career_batting_stats "
        "WHERE player_id = :pid AND split_id = 2 AND league_id = 203 AND level_id = 1 "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Career vs RHP
    data["career_rhp"] = conn.execute(text(
        "SELECT year, team_id, g, pa, ab, h, d, t, hr, bb, k, rbi, sb, cs, hp, sf, sh, r "
        "FROM players_career_batting_stats "
        "WHERE player_id = :pid AND split_id = 3 AND league_id = 203 AND level_id = 1 "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Advanced stats history (graceful fallback if table doesn't exist yet)
    try:
        data["adv_history"] = conn.execute(text(
            "SELECT year, team_abbr, pa, ba, obp, slg, ops, wrc_plus, woba, iso, "
            "k_pct, bb_pct, war, avg_ev, hard_hit_pct, barrel_pct, xwoba "
            "FROM batter_advanced_stats_history WHERE player_id = :pid AND pa >= 30 "
            "ORDER BY year DESC"), dict(pid=player_id)).fetchall()
    except Exception:
        data["adv_history"] = []

    return data


def fetch_fielding_stats(conn, player_id, primary_position):
    """Fetch fielding stats for a position player (non-pitcher).

    split_id is inconsistent in this table (0 for recent seasons, 1 for older) so
    we aggregate by year+position to avoid duplicates from team changes mid-season.
    """
    max_year_row = conn.execute(text(
        "SELECT MAX(year) FROM players_career_fielding_stats "
        "WHERE player_id = :pid AND level_id = 1 AND league_id = 203"
    ), dict(pid=player_id)).fetchone()
    max_year = int(max_year_row[0]) if max_year_row and max_year_row[0] else None

    if max_year is None:
        return dict(current=[], career=[])

    current = conn.execute(text(
        "SELECT position, SUM(g), SUM(gs), SUM(ip), SUM(tc), SUM(po), SUM(a), SUM(e), "
        "SUM(dp), SUM(pb), SUM(sba), SUM(rto), SUM(framing), SUM(arm), SUM(zr) "
        "FROM players_career_fielding_stats "
        "WHERE player_id = :pid AND year = :yr AND level_id = 1 AND league_id = 203 "
        "GROUP BY position ORDER BY SUM(g) DESC"
    ), dict(pid=player_id, yr=max_year)).fetchall()

    career = conn.execute(text(
        "SELECT year, SUM(g), SUM(gs), SUM(ip), SUM(tc), SUM(po), SUM(a), SUM(e), "
        "SUM(dp), SUM(pb), SUM(sba), SUM(rto), SUM(framing), SUM(arm), SUM(zr) "
        "FROM players_career_fielding_stats "
        "WHERE player_id = :pid AND position = :pos AND level_id = 1 AND league_id = 203 "
        "GROUP BY year ORDER BY year"
    ), dict(pid=player_id, pos=primary_position)).fetchall()

    return dict(current=current, career=career)


def fetch_pitcher_data(conn, player_id, common=None):
    """Fetch pitching-specific data. If common is provided, merge into it."""
    data = common if common else fetch_common_data(conn, player_id)

    # Pitching talent ratings + pitch repertoire + misc
    row = conn.execute(text(
        "SELECT pitching_ratings_talent_stuff, pitching_ratings_talent_movement, "
        "pitching_ratings_talent_control, pitching_ratings_talent_hra, "
        "pitching_ratings_talent_pbabip, "
        "pitching_ratings_misc_velocity, pitching_ratings_misc_stamina, "
        "pitching_ratings_misc_ground_fly, pitching_ratings_misc_hold, "
        "pitching_ratings_pitches_talent_fastball, pitching_ratings_pitches_talent_slider, "
        "pitching_ratings_pitches_talent_curveball, pitching_ratings_pitches_talent_changeup, "
        "pitching_ratings_pitches_talent_sinker, pitching_ratings_pitches_talent_splitter, "
        "pitching_ratings_pitches_talent_cutter, pitching_ratings_pitches_talent_knucklecurve, "
        "pitching_ratings_pitches_talent_screwball, pitching_ratings_pitches_talent_forkball, "
        "pitching_ratings_pitches_talent_knuckleball "
        "FROM players_pitching WHERE player_id = :pid"), dict(pid=player_id)).fetchone()
    data["pitching_ratings"] = row

    # Pitcher advanced stats (current season)
    row = conn.execute(text(
        "SELECT * FROM pitcher_advanced_stats WHERE player_id = :pid"),
        dict(pid=player_id)).fetchone()
    data["pitching_advanced"] = dict(zip(row._fields, row)) if row else None

    # Career pitching overall
    data["career_pitching"] = conn.execute(text(
        "SELECT year, team_id, g, gs, w, l, s, ip, ha, hra, bb, k, er, hld, bf, hp, "
        "qs, cg, sho, gb, fb, war, wpa "
        "FROM players_career_pitching_stats "
        "WHERE player_id = :pid AND split_id = 1 AND league_id = 203 AND level_id = 1 "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Career vs LHB
    data["career_lhb"] = conn.execute(text(
        "SELECT year, team_id, g, gs, w, l, s, ip, ha, hra, bb, k, er, hld, bf, hp, "
        "qs, cg, sho, gb, fb, war, wpa "
        "FROM players_career_pitching_stats "
        "WHERE player_id = :pid AND split_id = 2 AND league_id = 203 AND level_id = 1 "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Career vs RHB
    data["career_rhb"] = conn.execute(text(
        "SELECT year, team_id, g, gs, w, l, s, ip, ha, hra, bb, k, er, hld, bf, hp, "
        "qs, cg, sho, gb, fb, war, wpa "
        "FROM players_career_pitching_stats "
        "WHERE player_id = :pid AND split_id = 3 AND league_id = 203 AND level_id = 1 "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Pitching advanced stats history (graceful fallback if table doesn't exist yet)
    try:
        data["pitch_adv_history"] = conn.execute(text(
            "SELECT year, team_abbr, ip, era, fip, xfip, k_pct, bb_pct, k_bb_pct, "
            "whip, hr_9, gb_pct, war, hard_hit_pct_against, barrel_pct_against, xwoba_against "
            "FROM pitcher_advanced_stats_history WHERE player_id = :pid AND ip >= 5 "
            "ORDER BY year DESC"), dict(pid=player_id)).fetchall()
    except Exception:
        data["pitch_adv_history"] = []

    # Current (ground-truth) pitching ratings from players_scouted_ratings.
    # Only present when "Additional complete scouted ratings" is enabled in OOTP export.
    try:
        sr_p = conn.execute(text(
            "SELECT pitching_ratings_overall_stuff, pitching_ratings_overall_movement, "
            "pitching_ratings_overall_control, pitching_ratings_overall_hra, "
            "pitching_ratings_overall_pbabip "
            "FROM players_scouted_ratings "
            "WHERE player_id = :pid AND scouting_team_id = 0"),
            dict(pid=player_id)).fetchone()
        data["scouted_pit"] = sr_p
    except Exception:
        data["scouted_pit"] = None

    return data


def _fpct_html(tc, e):
    if not tc or tc == 0:
        return "—"
    fpct = (int(tc) - int(e)) / int(tc)
    cls = ' class="good"' if fpct >= 0.985 else ' class="poor"' if fpct <= 0.960 else ''
    return f'<span{cls}>{fpct:.3f}</span>'


def _zr_html(zr):
    if zr is None:
        return "—"
    val = float(zr)
    cls = ' class="good"' if val > 1.0 else ' class="poor"' if val < -1.0 else ''
    sign = "+" if val >= 0 else ""
    return f'<span{cls}>{sign}{val:.1f}</span>'


def generate_fielding_stats_html(fielding_data, primary_position):
    """Build the fielding statistics section (current season + career year-by-year)."""
    current = fielding_data.get("current", [])
    career = fielding_data.get("career", [])
    if not current and not career:
        return ""

    is_catcher = primary_position == 2
    html = '<h2>Fielding Statistics</h2>'

    # Current season: all positions played
    if current:
        html += '<h3>Current Season</h3><table><tr>'
        std_hdrs = ['Pos', 'G', 'GS', 'Inn', 'TC', 'PO', 'A', 'E', 'FPct', 'DP', 'ZR']
        c_hdrs = ['PB', 'SBA', 'CS', 'CS%', 'Framing', 'Arm']
        for h in std_hdrs + (c_hdrs if is_catcher else []):
            html += f'<th>{h}</th>'
        html += '</tr>'
        for row in current:
            pos, g, gs, ip, tc, po, a, e, dp, pb, sba, rto, framing, arm, zr = row
            inn = f"{float(ip):.1f}" if ip else "—"
            html += (f'<tr><td>{POS_MAP.get(pos, str(pos))}</td>'
                     f'<td>{g}</td><td>{gs}</td><td>{inn}</td>'
                     f'<td>{tc}</td><td>{po}</td><td>{a}</td><td>{e}</td>'
                     f'<td>{_fpct_html(tc, e)}</td><td>{dp}</td>'
                     f'<td>{_zr_html(zr)}</td>')
            if is_catcher:
                cs = int(rto) if rto else 0
                total_att = (int(sba) if sba else 0) + cs
                cs_pct = f"{cs / total_att * 100:.1f}%" if total_att > 0 else "—"
                html += (f'<td>{int(pb) if pb else 0}</td>'
                         f'<td>{int(sba) if sba else 0}</td>'
                         f'<td>{cs}</td><td>{cs_pct}</td>'
                         f'<td>{float(framing):.2f}</td>'
                         f'<td>{float(arm):.2f}</td>')
            html += '</tr>'
        html += '</table>'

    # Career by year at primary position
    if career:
        html += f'<h3>Career Fielding — {POS_MAP.get(primary_position, "?")} (MLB)</h3><table><tr>'
        car_hdrs = ['Year', 'G', 'GS', 'Inn', 'TC', 'PO', 'A', 'E', 'FPct', 'DP', 'ZR']
        if is_catcher:
            car_hdrs += ['PB', 'SBA', 'CS', 'CS%', 'Framing', 'Arm']
        for h in car_hdrs:
            html += f'<th>{h}</th>'
        html += '</tr>'
        max_year = max(r[0] for r in career)
        for row in career:
            yr, g, gs, ipf, tc, po, a, e, dp, pb, sba, rto, framing, arm, zr = row
            inn = f"{float(ipf):.1f}" if ipf else "—"
            style = ' style="font-weight:bold;background:#e8f0fe"' if yr == max_year else ''
            html += (f'<tr{style}><td>{yr}</td>'
                     f'<td>{g}</td><td>{gs}</td><td>{inn}</td>'
                     f'<td>{tc}</td><td>{po}</td><td>{a}</td><td>{e}</td>'
                     f'<td>{_fpct_html(tc, e)}</td><td>{dp}</td>'
                     f'<td>{_zr_html(zr)}</td>')
            if is_catcher:
                cs = int(rto) if rto else 0
                total_att = (int(sba) if sba else 0) + cs
                cs_pct = f"{cs / total_att * 100:.1f}%" if total_att > 0 else "—"
                html += (f'<td>{int(pb) if pb else 0}</td>'
                         f'<td>{int(sba) if sba else 0}</td>'
                         f'<td>{cs}</td><td>{cs_pct}</td>'
                         f'<td>{float(framing):.2f}</td>'
                         f'<td>{float(arm):.2f}</td>')
            html += '</tr>'
        html += '</table>'

    return html


def generate_batter_html(data, generated_at, last_import):
    """Build HTML string for a batter report."""
    p = data["player"]
    pid, first, last, tid, pos, age, bats, throws = p
    team_abbr = data["team"][2]
    pos_name = POS_MAP.get(pos, str(pos))
    bats_str = BATS_MAP.get(bats, "?")
    throws_str = THROWS_MAP.get(throws, "?")

    val = data["value"]
    br = data["batting_ratings"]
    bat_labels = [("Contact", 0), ("Gap", 1), ("Power", 2), ("Eye", 3),
                  ("Avoid K", 4), ("BABIP", 5)]
    run_labels = [("Speed", 8), ("Stealing", 9), ("Baserunning", 10), ("Steal Rate", 11)]
    bunt_labels = [("Bunt", 6), ("Bunt for Hit", 7)]

    fl = data["fielding"]
    field_labels = [("IF Range", 0), ("IF Arm", 1), ("Turn DP", 2), ("IF Error", 3),
                    ("OF Range", 4), ("OF Arm", 5), ("OF Error", 6)]

    stale = ""
    if last_import and generated_at:
        stale_banner = ('<div class="stale-banner">'
                        'This report may be outdated &mdash; database was updated after this report was generated. '
                        'Regenerate with <code>/player-stats</code>.</div>')
        # We'll inject JS to compare timestamps
        stale = f"""<div id="stale-banner" style="display:none">{stale_banner}</div>
<script>
var generated = new Date("{generated_at}");
var imported = new Date("{last_import}");
if (imported > generated) document.getElementById("stale-banner").style.display = "block";
</script>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{first} {last} - Player Report</title>
<style>{get_report_css("1400px")}</style></head><body>
<div class="container">
<div class="page-header">
  <div class="header-top">
    <div>
      <div class="player-name">{first} {last}</div>
      <div class="player-meta">{team_abbr} &bull; {pos_name} &bull; Age {age} &bull; B/T: {bats_str}/{throws_str}</div>
      <div style="margin-top:8px">{oa_pot_badges(val)}</div>
    </div>
  </div>
  <div class="import-ts">Generated: {generated_at}</div>
</div>
{stale}
<div style="padding:0 24px">
<h2>Scouting Summary</h2>
<!-- ANALYSIS:START --><!-- SCOUTING_SUMMARY --><!-- ANALYSIS:END -->
"""

    html += generate_batter_section_html(data)

    return html


def generate_batter_section_html(data):
    """Build the batting content block (ratings, stats, career tables).

    No HTML shell — can be appended to any page (e.g. after a pitching section).
    """
    html = ""
    br = data["batting_ratings"]
    fl = data["fielding"]
    lg_avgs = data["lg_avgs"]
    team_abbrs = data["team_abbrs"]

    bat_labels = [("Contact", 0), ("Gap", 1), ("Power", 2), ("Eye", 3),
                  ("Avoid K", 4), ("BABIP", 5)]
    run_labels = [("Speed", 8), ("Stealing", 9), ("Baserunning", 10), ("Steal Rate", 11)]
    field_labels = [("IF Range", 0), ("IF Arm", 1), ("Turn DP", 2), ("IF Error", 3),
                    ("OF Range", 4), ("OF Arm", 5), ("OF Error", 6)]

    # Batting Ratings — show Current (scouted) alongside Potential when available
    sr_b = data.get("scouted_bat")
    ratings_title = "OOTP Current Ratings" if sr_b is not None else "OOTP Potential Ratings"
    html += f'<h2>{ratings_title}</h2><div class="ratings-grid">'
    if sr_b is not None:
        html += '<table><tr><th>Batting</th><th>Cur</th><th>Pot</th></tr>'
        for label, idx in bat_labels:
            html += f'<tr><td class="left">{label}</td>{rating_td(sr_b[idx])}{rating_td(br[idx])}</tr>'
    else:
        html += '<table><tr><th colspan="2">Batting (Potential)</th></tr>'
        for label, idx in bat_labels:
            html += f'<tr><td class="left">{label}</td>{rating_td(br[idx])}</tr>'
    html += '</table>'
    html += '<table><tr><th colspan="2">Running</th></tr>'
    for label, idx in run_labels:
        html += f'<tr><td class="left">{label}</td>{rating_td(br[idx])}</tr>'
    html += '</table>'
    html += '<table><tr><th colspan="2">Fielding</th></tr>'
    for label, idx in field_labels:
        html += f'<tr><td class="left">{label}</td>{rating_td(fl[idx])}</tr>'
    html += '</table>'

    pos_names = ["P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
    html += '<table><tr><th>Pos</th><th>Cur</th><th>Pot</th></tr>'
    for i, pn in enumerate(pos_names):
        cur_val = fl[10 + i]
        pot_val = fl[19 + i]
        if cur_val > 0 or pot_val > 0:
            html += f'<tr><td class="left">{pn}</td>{rating_td(cur_val)}{rating_td(pot_val)}</tr>'
    html += '</table></div>'

    # Current season advanced stats
    adv = data.get("advanced")
    if adv:
        html += '<h2>Current Season (Batting)</h2>'
        html += '<h3>Overall</h3><table><tr>'
        cols = ['G', 'PA', 'AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'BB', 'K', 'SB',
                'BA', 'OBP', 'SLG', 'OPS', 'ISO', 'K%', 'BB%', 'BABIP', 'wOBA', 'wRC+', 'OPS+', 'WAR', 'WPA']
        for c in cols:
            html += f'<th>{c}</th>'
        html += '</tr><tr>'

        cur_year_row = None
        career = data.get("career_overall", [])
        if career:
            cur_year_row = max(career, key=lambda r: r[0])
        doubles = cur_year_row[6] if cur_year_row else 0
        triples = cur_year_row[7] if cur_year_row else 0

        vals = [
            fmt_int(adv['g']), fmt_int(adv['pa']), fmt_int(adv['ab']),
            fmt_int(adv['r']), fmt_int(adv['h']), str(doubles), str(triples),
            fmt_int(adv['hr']), fmt_int(adv['rbi']), fmt_int(adv['bb']),
            fmt_int(adv['k']), fmt_int(adv['sb']),
            fmt_rate(adv['ba']), fmt_rate(adv['obp']), fmt_rate(adv['slg']),
            fmt_rate(adv['ops']), fmt_rate(adv['iso']),
            fmt_pct(adv['k_pct']), fmt_pct(adv['bb_pct']),
            fmt_rate(adv['babip']), fmt_rate(adv['woba']),
            fmt_int(adv['wrc_plus']), fmt_int(adv['ops_plus']),
            fmt_rate(adv['war'], 1), fmt_rate(adv['wpa'], 1),
        ]
        for v in vals:
            html += f'<td>{v}</td>'
        html += '</tr></table>'

        html += '<h3>Contact Quality</h3><table><tr>'
        cq_cols = ['Batted Balls', 'Avg EV', 'Max EV', 'Avg LA', 'Hard Hit%', 'Barrel%',
                   'Sweet Spot%', 'GB%', 'LD%', 'FB%', 'xBA', 'xSLG', 'xwOBA', 'xBACON']
        for c in cq_cols:
            html += f'<th>{c}</th>'
        html += '</tr><tr>'
        def _pct_or_dash(v):
            return fmt_pct(v * 100) if v is not None else '—'
        cq_vals = [
            fmt_int(adv['batted_balls']), fmt_rate(adv['avg_ev'], 1), fmt_rate(adv['max_ev'], 1),
            fmt_rate(adv.get('avg_la', 0), 1),
            _pct_or_dash(adv['hard_hit_pct']), _pct_or_dash(adv['barrel_pct']),
            _pct_or_dash(adv['sweet_spot_pct']),
            _pct_or_dash(adv['gb_pct']), _pct_or_dash(adv['ld_pct']), _pct_or_dash(adv['fb_pct']),
            fmt_rate(adv['xba']), fmt_rate(adv['xslg']), fmt_rate(adv['xwoba']), fmt_rate(adv['xbacon']),
        ]
        for v in cq_vals:
            html += f'<td>{v}</td>'
        html += '</tr></table>'

        html += '<h3>Platoon Splits</h3><table><tr>'
        sp_cols = ['Split', 'PA', 'BA', 'OBP', 'SLG', 'ISO', 'K%', 'BB%', 'wOBA', 'wRC+',
                   'Avg EV', 'Hard%', 'Barrel%', 'xBA', 'xSLG', 'xwOBA']
        for c in sp_cols:
            html += f'<th>{c}</th>'
        html += '</tr>'
        for label, sfx in [('vs LHP', '_vs_lhp'), ('vs RHP', '_vs_rhp')]:
            html += f'<tr><td><b>{label}</b></td>'
            vals = [
                fmt_int(adv.get(f'pa{sfx}')),
                fmt_rate(adv.get(f'ba{sfx}')), fmt_rate(adv.get(f'obp{sfx}')),
                fmt_rate(adv.get(f'slg{sfx}')), fmt_rate(adv.get(f'iso{sfx}')),
                _pct_or_dash(adv.get(f'k_pct{sfx}')),
                _pct_or_dash(adv.get(f'bb_pct{sfx}')),
                fmt_rate(adv.get(f'woba{sfx}')),
                fmt_int(adv.get(f'wrc_plus{sfx}')),
                fmt_rate(adv.get(f'avg_ev{sfx}'), 1),
                _pct_or_dash(adv.get(f'hard_hit_pct{sfx}')),
                _pct_or_dash(adv.get(f'barrel_pct{sfx}')),
                fmt_rate(adv.get(f'xba{sfx}')), fmt_rate(adv.get(f'xslg{sfx}')),
                fmt_rate(adv.get(f'xwoba{sfx}')),
            ]
            for v in vals:
                html += f'<td>{v}</td>'
            html += '</tr>'
        html += '</table>'

    # Season History from batter_advanced_stats_history
    adv_hist = data.get("adv_history", [])
    if adv_hist:
        max_year = adv_hist[0][0]
        html += '<h2>Season History</h2><table><tr>'
        for c in ['Year', 'Team', 'PA', 'BA', 'OBP', 'SLG', 'OPS', 'wRC+', 'wOBA', 'ISO',
                  'K%', 'BB%', 'WAR', 'Avg EV', 'Hard Hit%', 'Barrel%', 'xwOBA']:
            html += f'<th>{c}</th>'
        html += '</tr>'
        for row in adv_hist:
            yr, tm, pa, ba, obp, slg, ops, wrc_plus, woba, iso, k_pct, bb_pct, war, \
                avg_ev, hard_hit_pct, barrel_pct, xwoba = row
            style = ' style="font-weight:bold;background:#e8f0fe"' if yr == max_year else ''
            html += (f'<tr{style}>'
                     f'<td>{yr}</td><td>{tm or "—"}</td><td>{fmt_int(pa)}</td>'
                     f'<td>{fmt_rate(ba)}</td><td>{fmt_rate(obp)}</td><td>{fmt_rate(slg)}</td>'
                     f'<td>{fmt_rate(ops)}</td><td>{fmt_int(wrc_plus)}</td>'
                     f'<td>{fmt_rate(woba)}</td><td>{fmt_rate(iso)}</td>'
                     f'<td>{fmt_pct(k_pct * 100 if k_pct is not None else None)}</td>'
                     f'<td>{fmt_pct(bb_pct * 100 if bb_pct is not None else None)}</td>'
                     f'<td>{fmt_rate(war, 1)}</td>'
                     f'<td>{fmt_rate(avg_ev, 1)}</td>'
                     f'<td>{fmt_pct(hard_hit_pct * 100 if hard_hit_pct is not None else None)}</td>'
                     f'<td>{fmt_pct(barrel_pct * 100 if barrel_pct is not None else None)}</td>'
                     f'<td>{fmt_rate(xwoba)}</td>'
                     f'</tr>')
        html += '</table>'

    # Career year-by-year
    html += '<h2>Career Batting Stats (MLB)</h2><table><tr>'
    career_cols = ['Year', 'Tm', 'G', 'PA', 'AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'BB', 'K', 'SB',
                   'BA', 'OBP', 'SLG', 'OPS', 'ISO', 'K%', 'BB%', 'BABIP', 'wOBA', 'wRC+', 'OPS+', 'WAR', 'WPA']
    for c in career_cols:
        html += f'<th>{c}</th>'
    html += '</tr>'
    for row in data.get("career_overall", []):
        yr, tid, g, pa, ab, h, d, t, hr, bb, k, rbi, sb, cs, hp, sf, sh, r, war, wpa = row
        lg = lg_avgs.get(int(yr))
        rates = calc_rates(int(ab), int(h), int(d), int(t), int(hr), int(bb), int(k),
                           int(hp), int(sf), int(pa), lg)
        tm = team_abbrs.get(tid, "?")
        html += (f'<tr><td>{yr}</td><td>{tm}</td><td>{g}</td><td>{pa}</td><td>{ab}</td>'
                 f'<td>{r}</td><td>{h}</td><td>{d}</td><td>{t}</td><td>{hr}</td>'
                 f'<td>{rbi}</td><td>{bb}</td><td>{k}</td><td>{sb}</td>'
                 f'<td>{fmt_rate(rates.get("ba"))}</td><td>{fmt_rate(rates.get("obp"))}</td>'
                 f'<td>{fmt_rate(rates.get("slg"))}</td><td>{fmt_rate(rates.get("ops"))}</td>'
                 f'<td>{fmt_rate(rates.get("iso"))}</td><td>{fmt_pct(rates.get("k_pct"))}</td>'
                 f'<td>{fmt_pct(rates.get("bb_pct"))}</td><td>{fmt_rate(rates.get("babip"))}</td>'
                 f'<td>{fmt_rate(rates.get("woba"))}</td><td>{fmt_int(rates.get("wrc_plus"))}</td>'
                 f'<td>{fmt_int(rates.get("ops_plus"))}</td>'
                 f'<td>{float(war):.1f}</td><td>{float(wpa):.1f}</td></tr>')
    html += '</table>'

    def split_table(title, rows):
        h = f'<h3>{title}</h3><table><tr>'
        for c in ['Year', 'Tm', 'G', 'PA', 'AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'BB', 'K', 'SB',
                  'BA', 'OBP', 'SLG', 'OPS', 'ISO', 'K%', 'BB%', 'BABIP', 'wOBA', 'wRC+', 'OPS+']:
            h += f'<th>{c}</th>'
        h += '</tr>'
        for row in rows:
            yr, tid, g, pa, ab, h_val, d, t, hr, bb, k, rbi, sb, cs, hp, sf, sh, r = row
            lg = lg_avgs.get(int(yr))
            rates = calc_rates(int(ab), int(h_val), int(d), int(t), int(hr), int(bb), int(k),
                               int(hp), int(sf), int(pa), lg)
            tm = team_abbrs.get(tid, "?")
            h += (f'<tr><td>{yr}</td><td>{tm}</td><td>{g}</td><td>{pa}</td><td>{ab}</td>'
                  f'<td>{r}</td><td>{h_val}</td><td>{d}</td><td>{t}</td><td>{hr}</td>'
                  f'<td>{rbi}</td><td>{bb}</td><td>{k}</td><td>{sb}</td>'
                  f'<td>{fmt_rate(rates.get("ba"))}</td><td>{fmt_rate(rates.get("obp"))}</td>'
                  f'<td>{fmt_rate(rates.get("slg"))}</td><td>{fmt_rate(rates.get("ops"))}</td>'
                  f'<td>{fmt_rate(rates.get("iso"))}</td><td>{fmt_pct(rates.get("k_pct"))}</td>'
                  f'<td>{fmt_pct(rates.get("bb_pct"))}</td><td>{fmt_rate(rates.get("babip"))}</td>'
                  f'<td>{fmt_rate(rates.get("woba"))}</td><td>{fmt_int(rates.get("wrc_plus"))}</td>'
                  f'<td>{fmt_int(rates.get("ops_plus"))}</td></tr>')
        h += '</table>'
        return h

    html += '<div class="splits-container">'
    html += '<div>' + split_table('Career vs LHP', data.get("career_lhp", [])) + '</div>'
    html += '<div>' + split_table('Career vs RHP', data.get("career_rhp", [])) + '</div>'
    html += '</div>'

    # Fielding statistics (position players only) — rendered last
    if data.get("fielding_stats"):
        p = data["player"]
        primary_pos = p[4]
        html += generate_fielding_stats_html(data["fielding_stats"], primary_pos)

    return html


def generate_pitcher_section_html(data):
    """Build HTML for the pitching section (used standalone or as part of two-way report)."""
    html = ""
    pr = data["pitching_ratings"]
    lg_pitch = data.get("lg_pitch", {})
    team_abbrs = data["team_abbrs"]

    # Pitching ratings — show Current (scouted) alongside Potential when available
    sr_p = data.get("scouted_pit")
    pitch_labels = [("Stuff", 0), ("Movement", 1), ("Control", 2),
                    ("HR Avoidance", 3), ("BABIP Against", 4)]
    ratings_title = "OOTP Current Ratings" if sr_p is not None else "OOTP Potential Ratings"
    html += f'<h2>{ratings_title}</h2><div class="ratings-grid">'
    if sr_p is not None:
        html += '<table><tr><th>Pitching</th><th>Cur</th><th>Pot</th></tr>'
        for label, idx in pitch_labels:
            html += f'<tr><td class="left">{label}</td>{rating_td(sr_p[idx])}{rating_td(pr[idx])}</tr>'
    else:
        html += '<table><tr><th colspan="2">Pitching (Potential)</th></tr>'
        for label, idx in pitch_labels:
            html += f'<tr><td class="left">{label}</td>{rating_td(pr[idx])}</tr>'
    html += '</table>'

    html += '<table><tr><th colspan="2">Misc</th></tr>'
    misc_labels = [("Velocity", 5), ("Stamina", 6), ("GB Tendency", 7), ("Hold Runners", 8)]
    for label, idx in misc_labels:
        html += f'<tr><td class="left">{label}</td>{rating_td(pr[idx])}</tr>'
    html += '</table>'

    # Pitch repertoire
    pitch_names = ["Fastball", "Slider", "Curveball", "Changeup", "Sinker",
                   "Splitter", "Cutter", "Knuckle Curve", "Screwball", "Forkball",
                   "Knuckleball"]
    pitch_indices = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    has_pitches = [(name, pr[idx]) for name, idx in zip(pitch_names, pitch_indices) if pr[idx] > 0]
    if has_pitches:
        html += '<table><tr><th colspan="2">Pitch Arsenal</th></tr>'
        for name, val in sorted(has_pitches, key=lambda x: -x[1]):
            html += f'<tr><td class="left">{name}</td>{rating_td(val)}</tr>'
        html += '</table>'

    # Fielding position ratings (inline with pitching ratings)
    fl = data.get("fielding")
    if fl:
        pos_names_list = ["P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
        pos_rows = [(pn, fl[10 + i], fl[19 + i]) for i, pn in enumerate(pos_names_list)
                    if fl[10 + i] > 0 or fl[19 + i] > 0]
        if pos_rows:
            html += '<table><tr><th>Pos</th><th>Cur</th><th>Pot</th></tr>'
            for pn, cur_val, pot_val in pos_rows:
                html += f'<tr><td class="left">{pn}</td>{rating_td(cur_val)}{rating_td(pot_val)}</tr>'
            html += '</table>'

    html += '</div>'

    # Current season pitching advanced stats
    padv = data.get("pitching_advanced")
    if padv:
        html += '<h2>Current Season (Pitching)</h2>'
        html += '<h3>Overall</h3><table><tr>'
        cols = ['G', 'GS', 'W', 'L', 'SV', 'HLD', 'IP', 'ERA', 'FIP', 'xFIP',
                'K%', 'BB%', 'K-BB%', 'WHIP', 'K/9', 'BB/9', 'HR/9', 'BABIP', 'GB%', 'WAR', 'WPA']
        for c in cols:
            html += f'<th>{c}</th>'
        html += '</tr><tr>'
        vals = [
            fmt_int(padv['g']), fmt_int(padv['gs']),
            fmt_int(padv['w']), fmt_int(padv['l']),
            fmt_int(padv['s']), fmt_int(padv['hld']),
            fmt_rate(padv['ip'], 1),
            fmt_rate(padv['era'], 2), fmt_rate(padv['fip'], 2), fmt_rate(padv['xfip'], 2),
            fmt_pct(padv['k_pct'] * 100), fmt_pct(padv['bb_pct'] * 100),
            fmt_pct(padv['k_bb_pct'] * 100),
            fmt_rate(padv['whip'], 2),
            fmt_rate(padv['k_9'], 1), fmt_rate(padv['bb_9'], 1), fmt_rate(padv['hr_9'], 1),
            fmt_rate(padv['babip']), fmt_pct(padv['gb_pct'] * 100),
            fmt_rate(padv['war'], 1), fmt_rate(padv['wpa'], 1),
        ]
        for v in vals:
            html += f'<td>{v}</td>'
        html += '</tr></table>'

        # Contact quality against
        html += '<h3>Contact Quality Against</h3><table><tr>'
        for c in ['Batted Balls', 'Avg EV Against', 'Hard Hit%', 'Barrel%', 'xBA Against', 'xwOBA Against']:
            html += f'<th>{c}</th>'
        html += '</tr><tr>'
        cq_vals = [
            fmt_int(padv.get('bb_against')),
            fmt_rate(padv.get('avg_ev_against'), 1),
            fmt_pct(padv.get('hard_hit_pct_against', 0) * 100),
            fmt_pct(padv.get('barrel_pct_against', 0) * 100),
            fmt_rate(padv.get('xba_against')),
            fmt_rate(padv.get('xwoba_against')),
        ]
        for v in cq_vals:
            html += f'<td>{v}</td>'
        html += '</tr></table>'

        # Platoon splits
        html += '<h3>Platoon Splits</h3><table><tr>'
        for c in ['Split', 'BF', 'ERA', 'FIP', 'K%', 'BB%', 'K-BB%', 'WHIP', 'BABIP']:
            html += f'<th>{c}</th>'
        html += '</tr>'
        for label, sfx in [('vs LHB', '_vs_lhb'), ('vs RHB', '_vs_rhb')]:
            html += f'<tr><td><b>{label}</b></td>'
            vals = [
                fmt_int(padv.get(f'bf{sfx}')),
                fmt_rate(padv.get(f'era{sfx}'), 2),
                fmt_rate(padv.get(f'fip{sfx}'), 2),
                fmt_pct(padv.get(f'k_pct{sfx}', 0) * 100),
                fmt_pct(padv.get(f'bb_pct{sfx}', 0) * 100),
                fmt_pct(padv.get(f'k_bb_pct{sfx}', 0) * 100),
                fmt_rate(padv.get(f'whip{sfx}'), 2),
                fmt_rate(padv.get(f'babip{sfx}')),
            ]
            for v in vals:
                html += f'<td>{v}</td>'
            html += '</tr>'
        html += '</table>'

    # Pitcher Season History from pitcher_advanced_stats_history
    pitch_hist = data.get("pitch_adv_history", [])
    if pitch_hist:
        max_year = pitch_hist[0][0]
        html += '<h2>Season History</h2><table><tr>'
        for c in ['Year', 'Team', 'IP', 'ERA', 'FIP', 'xFIP', 'K%', 'BB%', 'K-BB%',
                  'WHIP', 'HR/9', 'GB%', 'WAR', 'Hard Hit% Against', 'Barrel% Against',
                  'xwOBA Against']:
            html += f'<th>{c}</th>'
        html += '</tr>'
        for row in pitch_hist:
            yr, tm, ip, era, fip, xfip, k_pct, bb_pct, k_bb_pct, whip, hr_9, gb_pct, war, \
                hard_hit_pct_against, barrel_pct_against, xwoba_against = row
            style = ' style="font-weight:bold;background:#e8f0fe"' if yr == max_year else ''
            html += (f'<tr{style}>'
                     f'<td>{yr}</td><td>{tm or "—"}</td><td>{fmt_rate(ip, 1)}</td>'
                     f'<td>{fmt_rate(era, 2)}</td><td>{fmt_rate(fip, 2)}</td>'
                     f'<td>{fmt_rate(xfip, 2)}</td>'
                     f'<td>{fmt_pct(k_pct * 100 if k_pct is not None else None)}</td>'
                     f'<td>{fmt_pct(bb_pct * 100 if bb_pct is not None else None)}</td>'
                     f'<td>{fmt_pct(k_bb_pct * 100 if k_bb_pct is not None else None)}</td>'
                     f'<td>{fmt_rate(whip, 2)}</td><td>{fmt_rate(hr_9, 1)}</td>'
                     f'<td>{fmt_pct(gb_pct * 100 if gb_pct is not None else None)}</td>'
                     f'<td>{fmt_rate(war, 1)}</td>'
                     f'<td>{fmt_pct(hard_hit_pct_against * 100 if hard_hit_pct_against is not None else None)}</td>'
                     f'<td>{fmt_pct(barrel_pct_against * 100 if barrel_pct_against is not None else None)}</td>'
                     f'<td>{fmt_rate(xwoba_against)}</td>'
                     f'</tr>')
        html += '</table>'

    # Career pitching year-by-year
    career_p = data.get("career_pitching", [])
    if career_p:
        html += '<h2>Career Pitching Stats (MLB)</h2><table><tr>'
        cols = ['Year', 'Tm', 'G', 'GS', 'W', 'L', 'SV', 'HLD', 'IP', 'H', 'HR', 'BB', 'K',
                'ERA', 'FIP', 'K%', 'BB%', 'K-BB%', 'WHIP', 'HR/9', 'BABIP', 'GB%', 'WAR', 'WPA']
        for c in cols:
            html += f'<th>{c}</th>'
        html += '</tr>'

        for row in career_p:
            yr, tid, g, gs, w, l, s, ip, ha, hra, bb, k, er, hld, bf, hp, \
                qs, cg, sho, gb, fb, war, wpa = row
            lg_p = lg_pitch.get(int(yr))
            rates = calc_pitching_rates(float(ip), int(ha), int(hra), int(bb), int(k),
                                        int(er), int(bf), int(hp), int(gb), int(fb), lg_p)
            tm = team_abbrs.get(tid, "?")
            html += (f'<tr><td>{yr}</td><td>{tm}</td><td>{g}</td><td>{gs}</td>'
                     f'<td>{w}</td><td>{l}</td><td>{s}</td><td>{hld}</td>'
                     f'<td>{float(ip):.1f}</td><td>{ha}</td><td>{hra}</td>'
                     f'<td>{bb}</td><td>{k}</td>'
                     f'<td>{fmt_rate(rates.get("era"), 2)}</td>'
                     f'<td>{fmt_rate(rates.get("fip"), 2)}</td>'
                     f'<td>{fmt_pct(rates.get("k_pct"))}</td>'
                     f'<td>{fmt_pct(rates.get("bb_pct"))}</td>'
                     f'<td>{fmt_pct(rates.get("k_bb_pct"))}</td>'
                     f'<td>{fmt_rate(rates.get("whip"), 2)}</td>'
                     f'<td>{fmt_rate(rates.get("hr_9"), 1)}</td>'
                     f'<td>{fmt_rate(rates.get("babip"))}</td>'
                     f'<td>{fmt_pct(rates.get("gb_pct"))}</td>'
                     f'<td>{float(war):.1f}</td><td>{float(wpa):.1f}</td></tr>')
        html += '</table>'

        # Career pitching splits
        def pitch_split_table(title, rows):
            h = f'<h3>{title}</h3><table><tr>'
            for c in ['Year', 'Tm', 'G', 'IP', 'H', 'HR', 'BB', 'K',
                      'ERA', 'FIP', 'K%', 'BB%', 'WHIP', 'BABIP', 'WAR']:
                h += f'<th>{c}</th>'
            h += '</tr>'
            for row in rows:
                yr, tid, g, gs, w, l, s, ip, ha, hra, bb, k, er, hld, bf, hp, \
                    qs, cg, sho, gb, fb, war, wpa = row
                lg_p = lg_pitch.get(int(yr))
                rates = calc_pitching_rates(float(ip), int(ha), int(hra), int(bb), int(k),
                                            int(er), int(bf), int(hp), int(gb), int(fb), lg_p)
                tm = team_abbrs.get(tid, "?")
                h += (f'<tr><td>{yr}</td><td>{tm}</td><td>{g}</td>'
                      f'<td>{float(ip):.1f}</td><td>{ha}</td><td>{hra}</td>'
                      f'<td>{bb}</td><td>{k}</td>'
                      f'<td>{fmt_rate(rates.get("era"), 2)}</td>'
                      f'<td>{fmt_rate(rates.get("fip"), 2)}</td>'
                      f'<td>{fmt_pct(rates.get("k_pct"))}</td>'
                      f'<td>{fmt_pct(rates.get("bb_pct"))}</td>'
                      f'<td>{fmt_rate(rates.get("whip"), 2)}</td>'
                      f'<td>{fmt_rate(rates.get("babip"))}</td>'
                      f'<td>{float(war):.1f}</td></tr>')
            h += '</table>'
            return h

        html += '<div class="splits-container">'
        if data.get("career_lhb"):
            html += '<div>' + pitch_split_table('Career vs LHB', data["career_lhb"]) + '</div>'
        if data.get("career_rhb"):
            html += '<div>' + pitch_split_table('Career vs RHB', data["career_rhb"]) + '</div>'
        html += '</div>'

    return html



def find_existing_report(save_name, first_name, last_name):
    """Check if a fresh report already exists for this player.

    Returns the report path if it exists and was generated after the last import,
    or None if the report needs to be (re)generated.
    """
    engine = get_engine(save_name)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT player_id FROM players "
            "WHERE first_name = :first AND last_name = :last"),
            dict(first=first_name, last=last_name)).fetchone()
        if not row:
            return None
        player_id = row[0]

    slug = f"{first_name}_{last_name}_{player_id}".lower()
    report_path = PROJECT_ROOT / "reports" / save_name / "players" / f"{slug}.html"

    if not report_path.exists():
        return None

    last_import = get_last_import_time()
    if not last_import:
        return str(report_path)

    # Check if report was generated after last import
    report_mtime = datetime.fromtimestamp(report_path.stat().st_mtime)
    import_time = datetime.fromisoformat(last_import)

    if report_mtime >= import_time:
        return str(report_path)

    return None


def generate_player_report(save_name, first_name, last_name):
    """Main entry: generate a report for one player.

    Detects two-way players by checking for both batting and pitching career data.
    Returns (path, data_dict) where data_dict is None on a cache hit.
    """
    existing = find_existing_report(save_name, first_name, last_name)
    if existing:
        return existing, None

    engine = get_engine(save_name)
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    last_import = get_last_import_time()

    with engine.connect() as conn:
        # Look up player — prefer the one with the most MLB career activity (PA + IP)
        row = conn.execute(text(
            "SELECT p.player_id, p.position FROM players p "
            "LEFT JOIN ("
            "  SELECT player_id, SUM(pa) AS total_pa FROM players_career_batting_stats "
            "  WHERE league_id = 203 AND level_id = 1 AND split_id = 1 GROUP BY player_id"
            ") bs ON bs.player_id = p.player_id "
            "LEFT JOIN ("
            "  SELECT player_id, SUM(ip) AS total_ip FROM players_career_pitching_stats "
            "  WHERE league_id = 203 AND level_id = 1 AND split_id = 1 GROUP BY player_id"
            ") ps ON ps.player_id = p.player_id "
            "WHERE p.first_name = :first AND p.last_name = :last "
            "ORDER BY COALESCE(bs.total_pa, 0) + COALESCE(ps.total_ip, 0) DESC"),
            dict(first=first_name, last=last_name)).fetchone()

        if not row:
            print(f"Player not found: {first_name} {last_name}")
            sys.exit(1)

        player_id = row[0]
        position = row[1]

        # Fetch common data once
        common = fetch_common_data(conn, player_id)

        # Detect pitching and batting career data at MLB level.
        # For pitchers (position == 1), require >= 100 career PA to show batting section —
        # otherwise incidental plate appearances pollute the report with empty batting tables.
        has_pitching = conn.execute(text(
            "SELECT 1 FROM players_career_pitching_stats "
            "WHERE player_id = :pid AND league_id = 203 AND level_id = 1 AND split_id = 1 LIMIT 1"),
            dict(pid=player_id)).fetchone() is not None

        batting_pa_row = conn.execute(text(
            "SELECT SUM(pa) FROM players_career_batting_stats "
            "WHERE player_id = :pid AND league_id = 203 AND level_id = 1 AND split_id = 1"),
            dict(pid=player_id)).fetchone()
        career_pa = int(batting_pa_row[0] or 0)
        pa_threshold = 100 if position == 1 else 1
        has_batting = career_pa >= pa_threshold

        is_two_way = has_batting and has_pitching

        if has_batting:
            data = fetch_batter_data(conn, player_id, common)
        else:
            data = common

        if has_pitching:
            data = fetch_pitcher_data(conn, player_id, data)

        # Fielding stats for position players (not pitchers)
        if position != 1 and has_batting:
            data["fielding_stats"] = fetch_fielding_stats(conn, player_id, position)

        # Generate HTML — for position=1 players, pitching section always comes first
        if position == 1:
            html = generate_pitcher_only_html(data, generated_at, last_import)
            if has_batting:
                html += generate_batter_section_html(data)
        else:
            if has_batting:
                html = generate_batter_html(data, generated_at, last_import)
            else:
                html = generate_pitcher_only_html(data, generated_at, last_import)
            if has_pitching:
                html += generate_pitcher_section_html(data)

    html += '</div></div></body></html>'

    _kwargs_esc = json.dumps(dict(first=first_name, last=last_name)).replace('"', '&quot;')
    _ootp_meta = (
        '<meta name="ootp-skill" content="player-stats">'
        f'<meta name="ootp-args" content="{first_name} {last_name}">'
        f'<meta name="ootp-save" content="{save_name}">'
        f'<meta name="ootp-kwargs" content="{_kwargs_esc}">'
    )
    html = html.replace('</title>', '</title>\n' + _ootp_meta, 1)

    # Write report
    slug = f"{first_name}_{last_name}_{player_id}".lower()
    report_path = get_reports_dir(save_name, "players") / f"{slug}.html"
    write_report_html(report_path, html)

    return report_path, data


def generate_pitcher_only_html(data, generated_at, last_import):
    """Build full HTML page for a pitcher-only player (no batting stats)."""
    p = data["player"]
    pid, first, last, tid, pos, age, bats, throws = p
    team_abbr = data["team"][2]
    pos_name = POS_MAP.get(pos, str(pos))
    bats_str = BATS_MAP.get(bats, "?")
    throws_str = THROWS_MAP.get(throws, "?")

    val = data["value"]

    stale = ""
    if last_import and generated_at:
        stale_banner = ('<div class="stale-banner">'
                        'This report may be outdated &mdash; database was updated after this report was generated. '
                        'Regenerate with <code>/player-stats</code>.</div>')
        stale = f"""<div id="stale-banner" style="display:none">{stale_banner}</div>
<script>
var generated = new Date("{generated_at}");
var imported = new Date("{last_import}");
if (imported > generated) document.getElementById("stale-banner").style.display = "block";
</script>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{first} {last} - Player Report</title>
<style>{get_report_css("1400px")}</style></head><body>
<div class="container">
<div class="page-header">
  <div class="header-top">
    <div>
      <div class="player-name">{first} {last}</div>
      <div class="player-meta">{team_abbr} &bull; {pos_name} &bull; Age {age} &bull; B/T: {bats_str}/{throws_str}</div>
      <div style="margin-top:8px">{oa_pot_badges(val)}</div>
    </div>
  </div>
  <div class="import-ts">Generated: {generated_at}</div>
</div>
{stale}
<div style="padding:0 24px">
<h2>Scouting Summary</h2>
<!-- ANALYSIS:START --><!-- SCOUTING_SUMMARY --><!-- ANALYSIS:END -->
"""

    # Pitching section
    html += generate_pitcher_section_html(data)

    return html


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python src/report.py <save_name> <First> <Last>")
        sys.exit(1)
    save_name = sys.argv[1]
    first = sys.argv[2]
    last = sys.argv[3]
    path, _ = generate_player_report(save_name, first, last)
    print(f"Report: {path}")
