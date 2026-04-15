"""Database fetch functions for player-stats reports."""

from sqlalchemy import text

from ootp_db_constants import (
    MLB_LEAGUE_ID, MLB_LEVEL_ID,
    SPLIT_CAREER_OVERALL, SPLIT_CAREER_VS_LHP, SPLIT_CAREER_VS_RHP,
    SPLIT_TEAM_BATTING_OVERALL, SPLIT_TEAM_PITCHING_OVERALL,
)


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
        f"JOIN team_history th ON th.team_id = thbs.team_id AND th.year = thbs.year AND th.league_id = {MLB_LEAGUE_ID} "
        "GROUP BY thbs.year")).fetchall()
    for r in rows:
        lg[int(r[0])] = tuple(int(x) for x in r[1:])

    cur = conn.execute(text(
        "SELECT SUM(tbs.ab), SUM(tbs.h), SUM(tbs.d), SUM(tbs.t), SUM(tbs.hr), "
        "SUM(tbs.bb), SUM(tbs.hp), SUM(tbs.sf), SUM(tbs.pa), SUM(tbs.r) "
        "FROM team_batting_stats tbs "
        f"JOIN team_relations tr ON tr.team_id = tbs.team_id AND tr.league_id = {MLB_LEAGUE_ID} "
        f"WHERE tbs.level_id = {MLB_LEVEL_ID} AND tbs.split_id = {SPLIT_TEAM_BATTING_OVERALL}")).fetchone()
    yr_row = conn.execute(text(
        f"SELECT MAX(year) FROM team_history WHERE league_id = {MLB_LEAGUE_ID}")).fetchone()
    lg_cur_year = (int(yr_row[0]) + 1) if (yr_row and yr_row[0]) else 2028

    if cur and cur[0]:
        lg[lg_cur_year] = tuple(int(x) for x in cur)

    data["lg_avgs"] = lg

    # League pitching averages for cFIP calculation
    lg_pitch = {}
    rows = conn.execute(text(
        "SELECT thps.year, SUM(thps.ip), SUM(thps.hra), SUM(thps.bb), SUM(thps.hp), "
        "SUM(thps.k), SUM(thps.er) "
        "FROM team_history_pitching_stats thps "
        f"JOIN team_history th ON th.team_id = thps.team_id AND th.year = thps.year AND th.league_id = {MLB_LEAGUE_ID} "
        "GROUP BY thps.year")).fetchall()
    for r in rows:
        lg_pitch[int(r[0])] = tuple(float(x) for x in r[1:])

    cur_p = conn.execute(text(
        "SELECT SUM(tps.ip), SUM(tps.hra), SUM(tps.bb), SUM(tps.hp), SUM(tps.k), SUM(tps.er) "
        "FROM team_pitching_stats tps "
        f"JOIN team_relations tr ON tr.team_id = tps.team_id AND tr.league_id = {MLB_LEAGUE_ID} "
        f"WHERE tps.level_id = {MLB_LEVEL_ID} AND tps.split_id = {SPLIT_TEAM_PITCHING_OVERALL}")).fetchone()
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
        f"WHERE player_id = :pid AND split_id = {SPLIT_CAREER_OVERALL} AND league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Career vs LHP
    data["career_lhp"] = conn.execute(text(
        "SELECT year, team_id, g, pa, ab, h, d, t, hr, bb, k, rbi, sb, cs, hp, sf, sh, r "
        "FROM players_career_batting_stats "
        f"WHERE player_id = :pid AND split_id = {SPLIT_CAREER_VS_LHP} AND league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Career vs RHP
    data["career_rhp"] = conn.execute(text(
        "SELECT year, team_id, g, pa, ab, h, d, t, hr, bb, k, rbi, sb, cs, hp, sf, sh, r "
        "FROM players_career_batting_stats "
        f"WHERE player_id = :pid AND split_id = {SPLIT_CAREER_VS_RHP} AND league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} "
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


def fetch_fielding_stats(conn, player_id):
    """Fetch fielding stats for a position player (non-pitcher).

    split_id is inconsistent in this table (0 for recent seasons, 1 for older) so
    we aggregate by year+position to avoid duplicates from team changes mid-season.
    """
    max_year_row = conn.execute(text(
        "SELECT MAX(year) FROM players_career_fielding_stats "
        f"WHERE player_id = :pid AND level_id = {MLB_LEVEL_ID} AND league_id = {MLB_LEAGUE_ID}"
    ), dict(pid=player_id)).fetchone()
    max_year = int(max_year_row[0]) if max_year_row and max_year_row[0] else None

    if max_year is None:
        return dict(current=[], career=[])

    current = conn.execute(text(
        "SELECT position, SUM(g), SUM(gs), SUM(ip), SUM(tc), SUM(po), SUM(a), SUM(e), "
        "SUM(dp), SUM(pb), SUM(sba), SUM(rto), SUM(framing), SUM(arm), SUM(zr) "
        "FROM players_career_fielding_stats "
        f"WHERE player_id = :pid AND year = :yr AND level_id = {MLB_LEVEL_ID} AND league_id = {MLB_LEAGUE_ID} "
        "GROUP BY position ORDER BY SUM(g) DESC"
    ), dict(pid=player_id, yr=max_year)).fetchall()

    # Query all positions per year; pick the one with most games played (primary_position
    # is their *current* position, which may differ from earlier in their career).
    career_all = conn.execute(text(
        "SELECT year, position, SUM(g), SUM(gs), SUM(ip), SUM(tc), SUM(po), SUM(a), SUM(e), "
        "SUM(dp), SUM(pb), SUM(sba), SUM(rto), SUM(framing), SUM(arm), SUM(zr) "
        "FROM players_career_fielding_stats "
        f"WHERE player_id = :pid AND level_id = {MLB_LEVEL_ID} AND league_id = {MLB_LEAGUE_ID} "
        "GROUP BY year, position ORDER BY year, SUM(g) DESC"
    ), dict(pid=player_id)).fetchall()
    career = career_all

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
        f"WHERE player_id = :pid AND split_id = {SPLIT_CAREER_OVERALL} AND league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Career vs LHB
    data["career_lhb"] = conn.execute(text(
        "SELECT year, team_id, g, gs, w, l, s, ip, ha, hra, bb, k, er, hld, bf, hp, "
        "qs, cg, sho, gb, fb, war, wpa "
        "FROM players_career_pitching_stats "
        f"WHERE player_id = :pid AND split_id = {SPLIT_CAREER_VS_LHP} AND league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} "
        "ORDER BY year"), dict(pid=player_id)).fetchall()

    # Career vs RHB
    data["career_rhb"] = conn.execute(text(
        "SELECT year, team_id, g, gs, w, l, s, ip, ha, hra, bb, k, er, hld, bf, hp, "
        "qs, cg, sho, gb, fb, war, wpa "
        "FROM players_career_pitching_stats "
        f"WHERE player_id = :pid AND split_id = {SPLIT_CAREER_VS_RHP} AND league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} "
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
