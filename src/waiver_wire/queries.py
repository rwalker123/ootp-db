"""DB query functions and public query entry point for the waiver wire evaluator."""

from ootp_db_constants import (
    MLB_LEAGUE_ID, POS_MAP, ROLE_MAP,
)
from shared_css import (
    get_engine,
    load_saves_registry,
)
from sqlalchemy import text

from .formatting import (
    fmt_salary,
    get_current_salary,
    get_years_remaining,
    arb_status_label,
    injury_label,
    trait_label,
)

# Positions considered "pitcher" for group comparison
PITCHER_POS = {1}
# OF positions that are compared together
OF_POS = {7, 8, 9}
# Corner IF that share comparison
CORNER_IF_POS = {3, 5}
# Middle IF that share comparison
MIDDLE_IF_POS = {4, 6}


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
