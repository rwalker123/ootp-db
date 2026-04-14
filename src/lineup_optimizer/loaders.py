"""Database loaders for lineup optimizer."""

from config import CAREER_STATS_LOOKBACK_YEARS
from ootp_db_constants import (
    MLB_LEAGUE_ID,
    SPLIT_CAREER_FIELDING_HISTORICAL,
    SPLIT_CAREER_FIELDING_SIM_ERA,
)
from shared_css import get_engine
from sqlalchemy import text

from .engine import compute_woba


def resolve_team(conn, team_query):
    """Return (team_id, full_name, abbr) or (None, None, None).

    Raises ValueError if team_query matches multiple teams (ambiguous input).
    """
    if team_query:
        rows = conn.execute(text(
            "SELECT team_id, name, nickname, abbr FROM teams "
            "WHERE (LOWER(nickname) LIKE :q OR LOWER(name) LIKE :q) "
            f"AND league_id = {MLB_LEAGUE_ID} ORDER BY name, team_id"
        ), dict(q=f"%{team_query.lower()}%")).fetchall()
        if not rows:
            return None, None, None
        if len(rows) > 1:
            options = ", ".join(f"{r.name} {r.nickname} ({r.abbr})" for r in rows)
            raise ValueError(
                f"Ambiguous team query '{team_query}' — be more specific. Matches: {options}"
            )
        row = rows[0]
    else:
        row = conn.execute(text(
            "SELECT hm.team_id, t.name, t.nickname, t.abbr "
            "FROM human_managers hm JOIN teams t ON t.team_id = hm.team_id LIMIT 1"
        )).fetchone()
    if not row:
        return None, None, None
    return row.team_id, f"{row.name} {row.nickname}", row.abbr


def get_dh_used(conn, team_id):
    """Return True if the team's sub-league uses a designated hitter."""
    try:
        row = conn.execute(text(
            "SELECT sl.designated_hitter FROM teams t "
            "JOIN team_relations tr ON tr.team_id = t.team_id "
            "JOIN sub_leagues sl ON sl.league_id = tr.league_id "
            "  AND sl.sub_league_id = tr.sub_league_id "
            "WHERE t.team_id = :tid LIMIT 1"
        ), dict(tid=team_id)).fetchone()
        if row and row.designated_hitter is not None:
            return bool(row.designated_hitter)
    except Exception:
        conn.rollback()
    return True  # default: DH in use


def load_roster_batters(conn, team_id):
    """Load active-roster batters on the team via player_ratings.

    Joins team_roster (list_id=1) to restrict to the active roster only,
    excluding minor leaguers, 40-man non-actives, and IL players.
    """
    rows = conn.execute(text("""
        SELECT pr.player_id, pr.first_name, pr.last_name, pr.position,
               pr.age, pr.oa, pr.pot, pr.rating_overall, pr.rating_offense,
               pr.rating_baserunning, pr.rating_defense, pr.rating_discipline,
               pr.rating_durability, pr.flag_injury_risk, pr.prone_overall,
               pr.rating_now, pr.confidence,
               pr.rating_now_lhp, pr.rating_now_rhp,
               pr.confidence_lhp, pr.confidence_rhp,
               p.bats, p.fatigue_points
        FROM player_ratings pr
        JOIN players p ON p.player_id = pr.player_id
        JOIN team_roster tr ON tr.player_id = pr.player_id
            AND tr.team_id = :tid AND tr.list_id = 1
        WHERE pr.player_type = 'batter'
        ORDER BY pr.rating_overall DESC
    """), dict(tid=team_id)).fetchall()
    return [dict(r._mapping) for r in rows]


def load_fielding_ratings(conn, player_ids):
    """Load per-position fielding ratings from players_fielding.

    Returns dict of player_id -> {pos_code: rating} for positions with rating > 0.
    Positions: 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF.
    """
    if not player_ids:
        return {}
    clause = ",".join(str(i) for i in player_ids)
    rows = conn.execute(text(f"""
        SELECT player_id,
               fielding_rating_pos2, fielding_rating_pos3, fielding_rating_pos4,
               fielding_rating_pos5, fielding_rating_pos6, fielding_rating_pos7,
               fielding_rating_pos8, fielding_rating_pos9
        FROM players_fielding
        WHERE player_id IN ({clause})
    """)).fetchall()
    result = {}
    col_to_pos = {
        "fielding_rating_pos2": 2, "fielding_rating_pos3": 3,
        "fielding_rating_pos4": 4, "fielding_rating_pos5": 5,
        "fielding_rating_pos6": 6, "fielding_rating_pos7": 7,
        "fielding_rating_pos8": 8, "fielding_rating_pos9": 9,
    }
    for r in rows:
        ratings = {}
        for col, pos_code in col_to_pos.items():
            val = getattr(r, col, None)
            if val and val > 0:
                ratings[pos_code] = int(val)
        result[r.player_id] = ratings
    return result


def load_position_games(conn, player_ids):
    """Load games played per position and 3-year usage share for each player.

    Returns dict: player_id -> {
        "games":          {pos_code: total_games},  # all-time, for eligibility check
        "usage_pct":      {pos_code: float 0-1},    # last 3 years, for primary-pos bonus
        "total_3yr_games": int,                      # total games in 3-yr window (sample size)
    }
    """
    if not player_ids:
        return {}
    clause = ",".join(str(i) for i in player_ids)
    result = {pid: {"games": {}, "usage_pct": {}, "total_3yr_games": 0} for pid in player_ids}
    try:
        # All-time games for eligibility (fielding: two era buckets — see AGENTS.md / ootp_db_constants).
        rows = conn.execute(text(f"""
            SELECT player_id, position, SUM(g) AS total_games
            FROM players_career_fielding_stats
            WHERE player_id IN ({clause})
              AND split_id IN ({SPLIT_CAREER_FIELDING_SIM_ERA}, {SPLIT_CAREER_FIELDING_HISTORICAL})
            GROUP BY player_id, position
        """)).fetchall()
        for r in rows:
            result[r.player_id]["games"][r.position] = int(r.total_games or 0)

        # 3-year usage share: games at each pos / total games across all pos in window.
        # Also returns total_games so the bonus can be confidence-weighted by sample size.
        # Per-player MAX(year) across both split_ids gives the true most-recent season.
        rows2 = conn.execute(text(f"""
            WITH recent AS (
                SELECT player_id, position, SUM(g) AS pos_games
                FROM players_career_fielding_stats
                WHERE player_id IN ({clause})
                  AND split_id IN ({SPLIT_CAREER_FIELDING_SIM_ERA}, {SPLIT_CAREER_FIELDING_HISTORICAL})
                  AND year >= (
                      SELECT MAX(year) - {CAREER_STATS_LOOKBACK_YEARS}
                      FROM players_career_fielding_stats AS sub
                      WHERE sub.player_id = players_career_fielding_stats.player_id
                        AND sub.split_id IN ({SPLIT_CAREER_FIELDING_SIM_ERA}, {SPLIT_CAREER_FIELDING_HISTORICAL})
                  )
                GROUP BY player_id, position
            ),
            totals AS (
                SELECT player_id, SUM(pos_games) AS total_games
                FROM recent GROUP BY player_id
            )
            SELECT r.player_id, r.position,
                   r.pos_games * 1.0 / NULLIF(t.total_games, 0) AS usage_pct,
                   t.total_games
            FROM recent r JOIN totals t USING (player_id)
        """)).fetchall()
        for r in rows2:
            result[r.player_id]["usage_pct"][r.position] = float(r.usage_pct or 0)
            result[r.player_id]["total_3yr_games"] = int(r.total_games or 0)
    except Exception as e:
        print(f"Warning: load_position_games failed: {e}")
    return result


def load_batter_stats(conn, player_ids):
    """Load batter_advanced_stats keyed by player_id."""
    if not player_ids:
        return {}
    clause = ",".join(str(i) for i in player_ids)
    rows = conn.execute(text(f"""
        SELECT player_id, pa, obp, slg, ops, woba, wrc_plus, iso,
               k_pct, bb_pct, babip, war, avg_ev, hard_hit_pct, barrel_pct, xwoba,
               woba_vs_lhp, woba_vs_rhp, wrc_plus_vs_lhp, wrc_plus_vs_rhp,
               obp_vs_lhp, obp_vs_rhp, pa_vs_lhp, pa_vs_rhp
        FROM batter_advanced_stats
        WHERE player_id IN ({clause})
    """)).fetchall()
    return {r.player_id: dict(r._mapping) for r in rows}


def load_30day_stats(conn, player_ids):
    """Compute 30-day rolling wOBA from last 30 game entries per player."""
    if not player_ids:
        return {}
    clause = ",".join(str(i) for i in player_ids)
    try:
        rows = conn.execute(text(f"""
            SELECT player_id,
                   SUM(ab) AS ab, SUM(h) AS h, SUM(d) AS d,
                   SUM(t) AS triples, SUM(hr) AS hr, SUM(bb) AS bb,
                   SUM(hp) AS hp, SUM(sf) AS sf, COUNT(*) AS games
            FROM (
                SELECT player_id,
                       COALESCE(ab, 0) AS ab, COALESCE(h, 0) AS h,
                       COALESCE(d, 0) AS d, COALESCE(t, 0) AS t,
                       COALESCE(hr, 0) AS hr, COALESCE(bb, 0) AS bb,
                       COALESCE(hp, 0) AS hp, COALESCE(sf, 0) AS sf,
                       ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_id DESC) AS rn
                FROM players_game_batting
                WHERE player_id IN ({clause})
            ) sub
            WHERE rn <= 30
            GROUP BY player_id
        """)).fetchall()
    except Exception:
        return {}

    result = {}
    for r in rows:
        woba = compute_woba(r.ab, r.h, r.d, r.triples, r.hr, r.bb, r.hp, r.sf)
        pa = (r.ab or 0) + (r.bb or 0) + (r.hp or 0) + (r.sf or 0)
        result[r.player_id] = dict(
            rolling_woba=woba,
            rolling_pa=pa,
            rolling_games=r.games or 0,
            rolling_hr=r.hr or 0,
        )
    return result
