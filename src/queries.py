#!/usr/bin/env python3
"""Central query module — all DB query functions for OOTP Baseball tools.

Generators define their own query_* functions (since they rely on internal helpers).
This module re-exports them alongside standalone queries for standings, player lookup,
and draft prospects.
"""

from pathlib import Path

from ootp_db_constants import (  # noqa: F401 (re-exported for callers)
    MLB_LEAGUE_ID,
    POS_MAP, BATS_MAP, THROWS_MAP,
    SPLIT_CAREER_OVERALL, SPLIT_TEAM_BATTING_OVERALL, SPLIT_TEAM_PITCHING_OVERALL,
)
from sqlalchemy import text

from shared_css import get_engine, db_name_from_save, load_saves_registry  # noqa: F401 (re-exported for callers)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Shared helpers ───────────────────────────────────────────────────────────

POS_CODE = {v: k for k, v in POS_MAP.items()}


def _fmt(v, fmt=".1f", fallback="—"):
    if v is None:
        return fallback
    try:
        return format(float(v), fmt)
    except (TypeError, ValueError):
        return fallback


def _pct(v, fallback="—"):
    if v is None:
        return fallback
    try:
        return f"{float(v)*100:.1f}%"
    except (TypeError, ValueError):
        return fallback




def _load_saves():
    return load_saves_registry()


def _active_save():
    saves = _load_saves()
    active = saves.get("active")
    if not active:
        raise RuntimeError(
            "No active save configured. Run `./import.sh <save-name>` to import a save first."
        )
    return active


# ── Standalone query functions ───────────────────────────────────────────────

def query_standings(save_name) -> list:
    """Return current MLB standings as list of dicts."""
    engine = get_engine(save_name)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT d.name AS division, t.name, t.nickname,
                   tr.w, tr.l, tr.pct, tr.pos, tr.gb,
                   rel.sub_league_id, rel.division_id
            FROM team_relations rel
            JOIN teams t ON t.team_id = rel.team_id
            JOIN team_record tr ON tr.team_id = rel.team_id
            JOIN divisions d ON d.league_id = rel.league_id
                AND d.sub_league_id = rel.sub_league_id
                AND d.division_id = rel.division_id
            WHERE rel.league_id = :lid
            ORDER BY rel.sub_league_id, rel.division_id, tr.pos
        """), dict(lid=MLB_LEAGUE_ID)).mappings().fetchall()
    return [dict(r) for r in rows]


def query_player(save_name, first_name, last_name) -> dict | None:
    """Return player bio, composite ratings, and advanced stats. None if not found."""
    engine = get_engine(save_name)
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT pr.player_id, pr.first_name, pr.last_name, pr.team_abbr,
                   pr.position, pr.age, pr.oa, pr.pot, pr.player_type,
                   pr.rating_overall, pr.rating_offense, pr.rating_defense,
                   pr.rating_potential, pr.rating_durability, pr.rating_clubhouse,
                   pr.rating_development, pr.rating_baserunning,
                   pr.rating_contact_quality, pr.rating_discipline,
                   pr.wrc_plus, pr.war, pr.prone_overall,
                   pr.flag_injury_risk, pr.flag_leader, pr.flag_high_ceiling,
                   p.bats, p.throws, p.free_agent
            FROM player_ratings pr
            JOIN players p ON p.player_id = pr.player_id
            WHERE LOWER(pr.first_name) = LOWER(:f) AND LOWER(pr.last_name) = LOWER(:l)
            LIMIT 1
        """), dict(f=first_name, l=last_name)).mappings().fetchone()

        if not row:
            return None

        pid = row["player_id"]
        ptype = row["player_type"]

        if ptype == "pitcher":
            adv = conn.execute(text("""
                SELECT era, fip, xfip, k_pct, bb_pct, k_bb_pct, whip, war,
                       g, gs, ip, k_9, bb_9, hr_9, gb_pct,
                       hard_hit_pct_against, barrel_pct_against, xwoba_against
                FROM pitcher_advanced_stats WHERE player_id = :pid
            """), dict(pid=pid)).mappings().fetchone()
        else:
            adv = conn.execute(text("""
                SELECT ba, obp, slg, ops, wrc_plus, ops_plus, war,
                       k_pct, bb_pct, iso, babip, g, pa, hr, sb,
                       avg_ev, hard_hit_pct, barrel_pct, xwoba
                FROM batter_advanced_stats WHERE player_id = :pid
            """), dict(pid=pid)).mappings().fetchone()

    return dict(
        player_id=row["player_id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        team_abbr=row["team_abbr"],
        position=int(row["position"] or 0),
        age=row["age"],
        oa=row["oa"],
        pot=row["pot"],
        player_type=ptype,
        rating_overall=row["rating_overall"],
        rating_offense=row["rating_offense"],
        rating_defense=row["rating_defense"],
        rating_potential=row["rating_potential"],
        rating_durability=row["rating_durability"],
        rating_clubhouse=row["rating_clubhouse"],
        rating_development=row["rating_development"],
        rating_baserunning=row["rating_baserunning"],
        rating_contact_quality=row["rating_contact_quality"],
        rating_discipline=row["rating_discipline"],
        wrc_plus=row["wrc_plus"],
        war=row["war"],
        prone_overall=row["prone_overall"],
        flag_injury_risk=bool(row["flag_injury_risk"]),
        flag_leader=bool(row["flag_leader"]),
        flag_high_ceiling=bool(row["flag_high_ceiling"]),
        bats=int(row["bats"] or 1),
        throws=int(row["throws"] or 1),
        free_agent=bool(row["free_agent"]),
        adv=dict(adv) if adv else None,
    )


_DRAFT_ORDER_ALLOWLIST = {
    "dr.rating_overall DESC",
    "ir.rating_overall DESC",
    "dr.rating_ceiling DESC",
    "ir.rating_ceiling DESC",
    "dr.age ASC",
    "ir.age ASC",
}


def query_draft_prospects(save_name, criteria_label, where_clause,
                          order_by="dr.rating_overall DESC", limit=25,
                          pool="draft") -> list:
    """Return draft or IFA prospects as list of dicts.

    pool: "draft" uses draft_ratings table, "ifa" uses ifa_ratings table.
    where_clause: raw SQL fragment (uses dr/ir alias depending on pool).

    Security note: where_clause is caller-supplied SQL. This is an internal MCP
    tool not exposed to untrusted user input, but callers must sanitise values
    they interpolate into where_clause. limit is always int-coerced here.
    """
    # Coerce limit defensively regardless of what the caller passes
    limit = int(limit)
    # Validate order_by against allowlist to prevent injection via that parameter
    if order_by not in _DRAFT_ORDER_ALLOWLIST:
        default_alias = "ir" if pool == "ifa" else "dr"
        order_by = f"{default_alias}.rating_overall DESC"
    engine = get_engine(save_name)
    if pool == "ifa":
        sql = f"""
            SELECT ir.player_id, ir.first_name, ir.last_name, ir.position, ir.age,
                   ir.player_type, ir.bats, ir.throws, ir.nation_id, ir.nation,
                   ir.oa, ir.pot, ir.rating_overall,
                   ir.rating_ceiling, ir.rating_tools, ir.rating_development,
                   ir.rating_defense, ir.rating_age,
                   ir.flag_elite_ceiling, ir.flag_high_ceiling,
                   ir.flag_elite_we, ir.flag_elite_iq, ir.flag_demanding,
                   ir.flag_prime_age,
                   ir.work_ethic, ir.intelligence, ir.greed
            FROM ifa_ratings ir
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT {limit}
        """
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        results = []
        for r in rows:
            results.append(dict(
                player_id=r[0], first_name=r[1], last_name=r[2], position=r[3],
                age=r[4], player_type=r[5], bats=r[6], throws=r[7],
                nation_id=r[8], nation=r[9], oa=r[10], pot=r[11],
                rating_overall=r[12], rating_ceiling=r[13], rating_tools=r[14],
                rating_development=r[15], rating_defense=r[16], rating_age=r[17],
                flag_elite_ceiling=r[18], flag_high_ceiling=r[19],
                flag_elite_we=r[20], flag_elite_iq=r[21], flag_demanding=r[22],
                flag_prime_age=r[23],
                work_ethic=r[24], intelligence=r[25], greed=r[26],
                # draft-only fields as None for uniform interface
                college=None, domestic=None, rating_proximity=None,
                flag_international=None, flag_hs=None,
            ))
    else:
        sql = f"""
            SELECT dr.player_id, dr.first_name, dr.last_name, dr.position, dr.age,
                   dr.player_type, dr.bats, dr.throws, dr.college, dr.domestic,
                   dr.oa, dr.pot, dr.rating_overall,
                   dr.rating_ceiling, dr.rating_tools, dr.rating_development,
                   dr.rating_defense, dr.rating_proximity,
                   dr.flag_elite_ceiling, dr.flag_high_ceiling,
                   dr.flag_elite_we, dr.flag_elite_iq, dr.flag_demanding,
                   dr.flag_international, dr.flag_hs,
                   dr.work_ethic, dr.intelligence, dr.greed
            FROM draft_ratings dr
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT {limit}
        """
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        results = []
        for r in rows:
            results.append(dict(
                player_id=r[0], first_name=r[1], last_name=r[2], position=r[3],
                age=r[4], player_type=r[5], bats=r[6], throws=r[7],
                college=r[8], domestic=r[9], oa=r[10], pot=r[11],
                rating_overall=r[12], rating_ceiling=r[13], rating_tools=r[14],
                rating_development=r[15], rating_defense=r[16], rating_proximity=r[17],
                flag_elite_ceiling=r[18], flag_high_ceiling=r[19],
                flag_elite_we=r[20], flag_elite_iq=r[21], flag_demanding=r[22],
                flag_international=r[23], flag_hs=r[24],
                work_ethic=r[25], intelligence=r[26], greed=r[27],
                # ifa-only fields as None for uniform interface
                nation_id=None, nation=None, rating_age=None, flag_prime_age=None,
            ))
    return results


# ── Re-exports from generator modules ───────────────────────────────────────

from waiver_wire import query_waiver_claim          # noqa: E402
from contract_extension import query_contract_extension  # noqa: E402
from lineup_optimizer import query_lineup            # noqa: E402
from trade_targets import query_trade_targets        # noqa: E402
from free_agents import query_free_agents            # noqa: E402
from ratings import query_player_rating              # noqa: E402
