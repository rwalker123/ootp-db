"""DB query functions for the contract extension advisor."""

from ootp_db_constants import (
    MLB_LEAGUE_ID, MLB_LEVEL_ID,
    POS_MAP,
    SPLIT_CAREER_OVERALL,
)
from shared_css import (
    get_engine,
    load_saves_registry,
)
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .formatting import (
    arb_status_label,
    fmt_salary,
    get_current_salary,
    get_years_remaining,
    injury_label,
)

_PLAYER_KEYS = [
    "player_id", "first_name", "last_name", "position",
    "age", "oa", "pot", "player_type",
    "rating_overall", "wrc_plus", "war",
    "rating_offense", "rating_defense", "rating_potential",
    "rating_durability", "rating_development", "rating_clubhouse",
    "rating_baserunning",
    "flag_injury_risk", "flag_leader", "flag_high_ceiling",
    "prone_overall", "work_ethic", "intelligence", "greed", "loyalty",
    "play_for_winner",
    "local_pop", "national_pop",
    "bats", "throws",
    "team_abbr",
    "years", "current_year", "no_trade",
    "salary0", "salary1", "salary2", "salary3", "salary4",
    "salary5", "salary6", "salary7", "salary8", "salary9",
    "mlb_service_years",
]


def _lookup_player_id(conn, first_name, last_name):
    """Lightweight lookup: return player_id for a non-retired, non-free-agent player, or None."""
    row = conn.execute(
        text(
            "SELECT p.player_id FROM players p"
            " JOIN player_ratings pr ON pr.player_id = p.player_id"
            " WHERE p.first_name = :f AND p.last_name = :l"
            " AND p.retired = 0 AND p.free_agent = 0 LIMIT 1"
        ),
        dict(f=first_name, l=last_name),
    ).fetchone()
    return row[0] if row else None


def query_contract_extension(save_name, first_name, last_name):
    """Query all data needed for a contract extension recommendation.

    Returns the complete data dict (with private _* keys for HTML generation),
    or None if the player is not found. Does NOT perform a cache check.
    """
    from .tables import (
        _compute_war_vals_batter,
        _compute_war_vals_pitcher,
        _compute_adv_most_recent_batter,
        _compute_adv_most_recent_pitcher,
        _compute_comp_scalars,
        _adv_data_dict,
    )

    saves = load_saves_registry()
    save_data = saves.get("saves", {}).get(save_name, {})
    my_team_abbr = save_data.get("my_team_abbr") or "your team"
    my_team_id = int(save_data.get("my_team_id") or 0)

    engine = get_engine(save_name)

    # ── 1. Main player query ────────────────────────────────────────────
    with engine.connect() as conn:
        if my_team_id:
            _row = conn.execute(text(
                "SELECT name, nickname FROM teams WHERE team_id = :tid LIMIT 1"
            ), dict(tid=my_team_id)).mappings().fetchone()
            my_team_name = f"{_row['name']} {_row['nickname']}" if _row else my_team_abbr
        else:
            my_team_name = my_team_abbr

        player_row = conn.execute(
            text("""
            SELECT pr.player_id, pr.first_name, pr.last_name, pr.position,
                   pr.age, pr.oa, pr.pot, pr.player_type,
                   pr.rating_overall, pr.wrc_plus, pr.war,
                   pr.rating_offense, pr.rating_defense, pr.rating_potential,
                   pr.rating_durability, pr.rating_development, pr.rating_clubhouse,
                   pr.rating_baserunning,
                   pr.flag_injury_risk, pr.flag_leader, pr.flag_high_ceiling,
                   pr.prone_overall, pr.work_ethic, pr.intelligence, pr.greed, pr.loyalty,
                   COALESCE(p.personality_play_for_winner, 100) AS play_for_winner,
                   COALESCE(p.local_pop, 0) AS local_pop,
                   COALESCE(p.national_pop, 0) AS national_pop,
                   p.bats, p.throws,
                   t.abbr AS team_abbr,
                   pc.years, pc.current_year, pc.no_trade,
                   pc.salary0, pc.salary1, pc.salary2, pc.salary3, pc.salary4,
                   pc.salary5, pc.salary6, pc.salary7, pc.salary8, pc.salary9,
                   prs.mlb_service_years
            FROM player_ratings pr
            JOIN players p ON p.player_id = pr.player_id
            LEFT JOIN teams t ON t.team_id = p.team_id
            LEFT JOIN players_contract pc ON pc.player_id = pr.player_id
            LEFT JOIN players_roster_status prs ON prs.player_id = pr.player_id
            WHERE p.first_name = :f AND p.last_name = :l
              AND p.retired = 0 AND p.free_agent = 0
            LIMIT 1
            """),
            dict(f=first_name, l=last_name),
        ).fetchone()

    if player_row is None:
        return None

    d = dict(zip(_PLAYER_KEYS, player_row))
    player_id = d["player_id"]
    player_type = d["player_type"]

    # ── 2. WAR trend (last 5 MLB seasons) ───────────────────────────────
    with engine.connect() as conn:
        if player_type == "pitcher":
            war_rows = conn.execute(
                text("""
                SELECT year, g, gs, ip, ha, bb, k, er, hra, war
                FROM players_career_pitching_stats
                WHERE player_id = :pid AND split_id = :split_id
                  AND league_id = :league_id AND level_id = :level_id
                ORDER BY year DESC LIMIT 5
                """),
                dict(pid=player_id, split_id=SPLIT_CAREER_OVERALL,
                     league_id=MLB_LEAGUE_ID, level_id=MLB_LEVEL_ID),
            ).fetchall()
        else:
            war_rows = conn.execute(
                text("""
                SELECT year, g, pa, ab, h, d, t, hr, bb, k, hp, sf, war
                FROM players_career_batting_stats
                WHERE player_id = :pid AND split_id = :split_id
                  AND league_id = :league_id AND level_id = :level_id
                ORDER BY year DESC LIMIT 5
                """),
                dict(pid=player_id, split_id=SPLIT_CAREER_OVERALL,
                     league_id=MLB_LEAGUE_ID, level_id=MLB_LEVEL_ID),
            ).fetchall()

    # ── 3. Advanced stats (contact quality) — last 3 years ──────────────
    with engine.connect() as conn:
        try:
            if player_type == "pitcher":
                adv_rows = conn.execute(
                    text("""
                    SELECT year, avg_ev_against, hard_hit_pct_against, barrel_pct_against,
                           xba_against, xwoba_against, fip, xfip, k_pct, bb_pct, war
                    FROM pitcher_advanced_stats_history
                    WHERE player_id = :pid
                    ORDER BY year DESC LIMIT 3
                    """),
                    dict(pid=player_id),
                ).fetchall()
            else:
                adv_rows = conn.execute(
                    text("""
                    SELECT year, batted_balls, avg_ev, hard_hit_pct, barrel_pct,
                           sweet_spot_pct, xba, xslg, xwoba, wrc_plus, war
                    FROM batter_advanced_stats_history
                    WHERE player_id = :pid
                    ORDER BY year DESC LIMIT 3
                    """),
                    dict(pid=player_id),
                ).fetchall()
        except OperationalError:
            adv_rows = []

    # ── 4. Market comparables ────────────────────────────────────────────
    oa_val = int(d["oa"] or 0)
    position_val = int(d["position"])
    with engine.connect() as conn:
        comp_rows = conn.execute(
            text("""
            SELECT pr.first_name, pr.last_name, pr.age, pr.oa, pr.pot,
                   pr.rating_overall, t.abbr AS team_abbr,
                   pc.years, pc.current_year,
                   pc.salary0, pc.salary1, pc.salary2, pc.salary3, pc.salary4,
                   pc.salary5, pc.salary6, pc.salary7, pc.salary8, pc.salary9,
                   prs.mlb_service_years
            FROM player_ratings pr
            JOIN players p ON p.player_id = pr.player_id
            LEFT JOIN teams t ON t.team_id = p.team_id
            LEFT JOIN players_contract pc ON pc.player_id = pr.player_id
            LEFT JOIN players_roster_status prs ON prs.player_id = pr.player_id
            WHERE pr.player_type = :ptype
              AND pr.position = :pos
              AND pr.oa BETWEEN :oa_lo AND :oa_hi
              AND p.free_agent = 0 AND p.retired = 0
              AND pr.player_id != :pid
            ORDER BY pr.oa DESC, pr.rating_overall DESC
            LIMIT 10
            """),
            dict(
                ptype=player_type,
                pos=position_val,
                oa_lo=oa_val - 5,
                oa_hi=oa_val + 5,
                pid=player_id,
            ),
        ).fetchall()

    # ── Compute scalars ────────────────────────────────────────────────────
    if player_type == "pitcher":
        war_vals = _compute_war_vals_pitcher(war_rows)
        adv_most_recent = _compute_adv_most_recent_pitcher(adv_rows)
    else:
        war_vals = _compute_war_vals_batter(war_rows)
        adv_most_recent = _compute_adv_most_recent_batter(adv_rows)

    median_comp_salary, comp_names = _compute_comp_scalars(comp_rows)

    # Contract details
    years_remaining = get_years_remaining(d)
    current_salary = get_current_salary(d)
    service_years = d.get("mlb_service_years")

    pos_str = POS_MAP.get(d["position"], str(d["position"]))
    avg_war = (
        sum(v for _, v in war_vals) / len(war_vals) if war_vals else None
    )
    war_trend_str = "|".join(f"{yr}:{v:.1f}" for yr, v in war_vals)

    oa_v = int(d.get("oa") or 0)
    pot_v = int(d.get("pot") or 0)
    age_v = int(d.get("age") or 0)
    team_abbr = d.get("team_abbr") or "—"
    rating_overall = float(d.get("rating_overall") or 0)
    wrc_fip = d.get("wrc_plus")
    is_pitcher = player_type == "pitcher"
    key_stat_label = "FIP" if is_pitcher else "wRC+"
    key_stat_str = (
        f"{float(wrc_fip):.2f}" if wrc_fip is not None and is_pitcher
        else str(int(wrc_fip)) if wrc_fip is not None
        else "—"
    )
    war_str = f"{float(d.get('war')):.1f}" if d.get("war") is not None else "—"
    status_label = arb_status_label(service_years)

    greed_v = int(d.get("greed") or 100)
    loyalty_v = int(d.get("loyalty") or 100)
    pfw_v = int(d.get("play_for_winner") or 100)
    local_pop_v = int(d.get("local_pop") or 0)
    national_pop_v = int(d.get("national_pop") or 0)
    prone_v = d.get("prone_overall")

    if age_v < 26:
        age_phase = "Pre-Peak"
    elif age_v <= 30:
        age_phase = "Peak Years"
    elif age_v <= 33:
        age_phase = "Late Peak"
    else:
        age_phase = "Decline Phase"

    data_dict = dict(
        player_name=f"{first_name} {last_name}",
        player_type=player_type,
        position=pos_str,
        team_abbr=team_abbr,
        age=age_v,
        oa=oa_v,
        pot=pot_v,
        oa_pot_gap=pot_v - oa_v,
        age_phase=age_phase,
        rating_overall=round(rating_overall, 1),
        key_stat_label=key_stat_label,
        key_stat=key_stat_str,
        war_current_season=war_str,
        war_trend=war_trend_str,
        avg_war_last_seasons=f"{avg_war:.2f}" if avg_war is not None else "—",
        current_salary=fmt_salary(current_salary),
        years_remaining=years_remaining,
        mlb_service_years=f"{float(service_years):.1f}" if service_years is not None else "—",
        arb_status=status_label,
        greed=greed_v,
        loyalty=loyalty_v,
        play_for_winner=pfw_v,
        local_pop=local_pop_v,
        national_pop=national_pop_v,
        prone_overall=injury_label(prone_v),
        flag_injury_risk=bool(d.get("flag_injury_risk")),
        flag_high_ceiling=bool(d.get("flag_high_ceiling")),
        rating_development=round(float(d.get("rating_development") or 0), 1),
        rating_potential=round(float(d.get("rating_potential") or 0), 1),
        rating_durability=round(float(d.get("rating_durability") or 0), 1),
        median_comp_salary=fmt_salary(median_comp_salary),
        top_comps=comp_names,
        adv_years_available=len(adv_rows),
        my_team_abbr=my_team_abbr,
        my_team_name=my_team_name,
        **_adv_data_dict(adv_most_recent, player_type),
        # Private keys for HTML generation
        _war_rows=war_rows,
        _adv_rows=adv_rows,
        _comp_rows=comp_rows,
        _player_row_d=d,
        _player_id=player_id,
    )

    return data_dict
