#!/usr/bin/env python3
"""Lineup optimizer report generator for OOTP Baseball.

Produces a batting order recommendation using one of four named philosophies:
  modern      — Tango/FanGraphs wOBA-rank order; best hitter bats #2
  traditional — Conventional roles; best hitter bats #3, cleanup at #4
  platoon     — Daily restructuring by opponent handedness using confidence-weighted split wOBA
  hot-hand    — Modern base with 30-day rolling wOBA modifier applied as rank shifts
"""

import html as html_mod
import json
import math
import sys
from datetime import datetime
from pathlib import Path

from config import (
    CAREER_STATS_LOOKBACK_YEARS, REGRESSION_EXPONENT, PA_REGRESSION_THRESHOLD,
    WRC_CAP_HEADROOM, WOBA_BB, WOBA_HBP, WOBA_1B, WOBA_2B, WOBA_3B, WOBA_HR,
)
from ootp_db_constants import (
    MLB_LEAGUE_ID,
    POS_MAP, BATS_MAP, POS_STR_MAP,
    SPLIT_CAREER_FIELDING_HISTORICAL,
    SPLIT_CAREER_FIELDING_SIM_ERA,
)
from report_write import write_report_html, report_filename
from shared_css import db_name_from_save, get_engine, get_report_css, get_reports_dir
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAST_IMPORT_PATH = PROJECT_ROOT / ".last_import"

# lineup_optimizer uses WOBA_HP as local alias (other modules use WOBA_HBP)
WOBA_HP = WOBA_HBP

PHILOSOPHIES = ("modern", "traditional", "platoon", "hot-hand")
PHIL_LABELS = {
    "modern": "Modern / Sabermetric",
    "traditional": "Traditional",
    "platoon": "Platoon",
    "hot-hand": "Hot Hand",
}

# Slot mapping: slot_number -> rank_index (rank 0 = best sort score)
# Modern / Platoon / Hot-Hand: best hitter at #2 (Tango-optimal)
MODERN_SLOT_MAP = {1: 1, 2: 0, 3: 3, 4: 2, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8}
# Traditional: best hitter at #3, 2nd-best at #4, table-setters at 1-2
TRADITIONAL_SLOT_MAP = {1: 2, 2: 3, 3: 0, 4: 1, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8}

# ── Platoon scoring constants ────────────────────────────────────────────────
# Veteran: 502+ career MLB PA in adv stats (proxy for 3-year window establishment).
# Full split confidence at 300 split PA (Tango's reliability threshold, The Book 2007).
# Below 10 total PA: no split data applied — use blended_woba only.
_PLATOON_VETERAN_PA    = 502   # total PA threshold separating veteran from rookie formula
_PLATOON_FULL_CONF_PA  = 300   # split PA at which confidence reaches 1.0
_PLATOON_MIN_PA        = 10    # minimum total PA to apply any split data

# ── PA regression constants ──────────────────────────────────────────────────
# Prevents small-sample call-ups (e.g. 9 games) from outranking established
# starters. Blends raw observed wOBA toward a ratings-derived expectation.
# At WOBA_REG_PA plate appearances the blend is 50/50; at 0 PA it is 100%
# ratings-based; at 5× REG_PA it is ~83% observed.
WOBA_REG_PA = 300           # credibility threshold (plate appearances)
                            # At 300 PA: 50/50 blend of observed vs ratings anchor
                            # At 13 PA: ~4% observed (matches Tango reliability threshold)
_RATING_TO_WOBA_SLOPE = 0.002   # each rating_offense point above/below 50 ≈ .002 wOBA

# ── Positional eligibility floors ────────────────────────────────────────────
# A player must clear BOTH thresholds to be considered eligible at a non-primary
# position in normal conditions.  If no player clears both (emergency), any
# player with a non-zero fielding rating at that position is used as a fallback.
MIN_FIELDING_RATING = 40          # floor for corner positions (1B, 3B, LF, RF)
MIN_FIELDING_RATING_PREMIUM = 50  # floor for premium defensive spots (C, 2B, SS, CF)
MIN_POS_GAMES = 5                 # minimum career games at position (any level); prevents
                                  # 1-game flukes (e.g. 100 games 3B, 1 game RF) from
                                  # making a player appear eligible there


# ── Helpers ─────────────────────────────────────────────────────────────────

def get_last_import_time():
    if LAST_IMPORT_PATH.exists():
        return LAST_IMPORT_PATH.read_text().strip()
    return None


def letter_grade(score):
    for threshold, grade in ((90,"A+"),(80,"A"),(70,"B+"),(60,"B"),(50,"C+"),(40,"C"),(30,"D")):
        if score >= threshold:
            return grade
    return "F"


def grade_color(score):
    if score >= 70: return "#1a7a1a"
    if score >= 50: return "#2266cc"
    if score >= 40: return "#cc7700"
    return "#cc2222"


def woba_color(val):
    if val is None: return "#888"
    if val >= 0.360: return "#1a7a1a"
    if val >= 0.320: return "#cc7700"
    return "#cc2222"


def wrc_color(val):
    if val is None: return "#888"
    if val >= 115: return "#1a7a1a"
    if val >= 85: return "#cc7700"
    return "#cc2222"


def fmt_woba(val):
    return f"{val:.3f}" if val is not None else "—"


def fmt_int(val):
    return str(int(val)) if val is not None else "—"


def compute_woba(ab, h, d, t, hr, bb, hp, sf):
    """Compute wOBA from counting stats."""
    ab, h, d, t, hr, bb, hp, sf = (int(v or 0) for v in (ab, h, d, t, hr, bb, hp, sf))
    singles = max(0, h - d - t - hr)
    denom = ab + bb + hp + sf
    if denom == 0:
        return None
    numer = (WOBA_BB * bb + WOBA_HP * hp + WOBA_1B * singles
             + WOBA_2B * d + WOBA_3B * t + WOBA_HR * hr)
    return numer / denom


# ── Database queries ─────────────────────────────────────────────────────────

def resolve_team(conn, team_query):
    """Return (team_id, full_name, abbr) or (None, None, None).

    Raises ValueError if team_query matches multiple teams (ambiguous input).
    """
    if team_query:
        rows = conn.execute(text(
            "SELECT team_id, name, nickname, abbr FROM teams "
            "WHERE (nickname ILIKE :q OR name ILIKE :q) "
            f"AND league_id = {MLB_LEAGUE_ID} ORDER BY name, team_id"
        ), dict(q=f"%{team_query}%")).fetchall()
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


# ── Lineup logic ─────────────────────────────────────────────────────────────

def temperature_flag(season_woba, rolling_woba, rolling_pa):
    """Classify a player's 30-day trend relative to season average."""
    if season_woba is None or rolling_woba is None or (rolling_pa or 0) < 30:
        return "neutral"
    diff = rolling_woba - season_woba
    if diff >= 0.060: return "hot_extreme"
    if diff >= 0.030: return "hot"
    if diff <= -0.060: return "cold_extreme"
    if diff <= -0.030: return "cold"
    return "neutral"


def compute_blended_woba(observed_woba, pa, rating_offense, league_avg_woba,
                         avg_rating_offense=50.0, reg_pa=WOBA_REG_PA):
    """Regress raw wOBA toward a ratings-derived expectation.

    Protects against small-sample call-ups with inflated wOBA while still
    allowing genuinely talented rookies (high rating_offense) to rank well.

      • At 0 PA  → 100% ratings-based (star prospect earns the spot on talent)
      • At 300 PA → 50/50 observed vs expected
      • At 600 PA → 67% observed (established starters mostly judged by results)

    The pivot for rating_offense is the actual MLB-wide mean (not 50), because
    rating_offense doesn't center at 50 — established batters average ~39.
    A player at the mean gets league_avg_woba as their anchor.

    Args:
        observed_woba:      raw career wOBA from batter_advanced_stats (may be None)
        pa:                 career plate appearances vs MLB pitching
        rating_offense:     player_ratings.rating_offense (0–100 composite)
        league_avg_woba:    MLB-wide average wOBA of batters with PA ≥ 100
        avg_rating_offense: MLB-wide mean rating_offense for batters with PA ≥ 100
        reg_pa:             credibility threshold; default WOBA_REG_PA
    """
    expected = league_avg_woba + ((rating_offense or avg_rating_offense) - avg_rating_offense) * _RATING_TO_WOBA_SLOPE
    expected = max(0.200, min(0.450, expected))  # clamp to realistic range
    pa = pa or 0
    obs = observed_woba if observed_woba is not None else expected
    if pa < PA_REGRESSION_THRESHOLD and obs is not None:
        pa_trust = min((pa / PA_REGRESSION_THRESHOLD) ** REGRESSION_EXPONENT, 1.0)
        woba_cap = league_avg_woba + pa_trust * WRC_CAP_HEADROOM * _RATING_TO_WOBA_SLOPE
        obs = min(obs, woba_cap)
    return (obs * pa + expected * reg_pa) / (pa + reg_pa)


def is_star(player):
    """Career wOBA >= .370 OR rating_overall >= 70 qualifies as a star."""
    woba = (player.get("adv") or {}).get("woba") or 0
    return woba >= 0.370 or (player.get("rating_overall") or 0) >= 70


def platoon_score(player, hand):
    """Confidence-weighted split sort score (0–100 scale) for positional assignment
    and batting-order ranking.

    Uses precomputed rating_now_lhp/rhp × confidence_lhp/rhp from player_ratings.
    - hand="L" (opponent is LHP): use rating_now_lhp × confidence_lhp
    - hand="R" (opponent is RHP): use rating_now_rhp × confidence_rhp
    - no hand: return sort_score (rating_now × confidence, overall)

    confidence_lhp/rhp encodes the PA-ramp from the ratings package using
    PLATOON_LHP_PA_THRESHOLD / PLATOON_RHP_PA_THRESHOLD, so a player with
    6 PA vs LHP gets near-zero confidence and won't beat an established hitter.
    """
    if hand == "L":
        rating = player.get("rating_now_lhp")
        conf = player.get("confidence_lhp")
        return (50.0 if rating is None else rating) * (0.5 if conf is None else conf)
    elif hand == "R":
        rating = player.get("rating_now_rhp")
        conf = player.get("confidence_rhp")
        return (50.0 if rating is None else rating) * (0.5 if conf is None else conf)
    ss = player.get("sort_score")
    return 0.0 if ss is None else ss


def hot_hand_sort_score(player):
    """Sort score adjusted by 30-day temperature modifier. Stars get half-penalty."""
    temp = player.get("temp_flag", "neutral")
    star = is_star(player)
    base = player.get("sort_score") or 0.0

    modifiers = dict(
        hot_extreme=3.0,
        hot=1.5,
        cold=-1.5 if not star else -0.8,
        cold_extreme=-3.0 if not star else -1.5,
        neutral=0.0,
    )
    return base + modifiers.get(temp, 0.0)


def _resolve_player_name(name, players):
    """Case-insensitive name match: full name, then last name, then partial last name."""
    name_lower = name.lower().strip()
    for p in players:
        if f"{p['first_name']} {p['last_name']}".lower() == name_lower:
            return p
    for p in players:
        if p["last_name"].lower() == name_lower:
            return p
    for p in players:
        if name_lower in p["last_name"].lower():
            return p
    return None


def _fatigue_color(val):
    if val is None or val == 0:
        return "#aaa"
    if val >= 70: return "#cc2222"
    if val >= 40: return "#cc7700"
    return "#1a7a1a"


def rank_players(players, philosophy, hand):
    """Sort all eligible players by the philosophy's primary metric (best first)."""
    if philosophy == "platoon":
        key = lambda p: platoon_score(p, hand)
    elif philosophy == "hot-hand":
        key = lambda p: hot_hand_sort_score(p)
    else:  # modern and traditional both sort by sort_score; slot mapping differs
        key = lambda p: p.get("sort_score") or 0.0
    return sorted(players, key=key, reverse=True)


FIELD_POSITIONS = (2, 3, 4, 5, 6, 7, 8, 9)  # C, 1B, 2B, 3B, SS, LF, CF, RF

PREMIUM_DEFENSE_POSITIONS = frozenset([2, 4, 6, 8])  # C, 2B, SS, CF
CORNER_POSITIONS = frozenset([5, 7, 9])               # 3B, LF, RF — bat-first but defense matters
BATTER_POSITIONS = frozenset([3, 5, 7, 9])            # 1B, 3B, LF, RF — bat-first spots

# Defense bonus scales per position class (fielding_rating / 100 * scale = sort_score bonus).
# Calibrated relative to sort_score range (0–100): premium max ~4 pts, corners ~2, 1B ~1.5.
# favor_offense halves all scales.
_DEFENSE_BONUS_SCALE_PREMIUM  = 4.0    # C/2B/SS/CF: 70 rating → +2.8 pts
_DEFENSE_BONUS_SCALE_CORNER   = 2.0    # 3B/LF/RF:   70 rating → +1.4 pts
_DEFENSE_BONUS_SCALE_1B       = 1.5    # 1B:         70 rating → +1.05 pts
_FAVOR_OFFENSE_DIVISOR        = 2      # favor_offense halves each scale above

_PRIMARY_POS_BONUS_MAX = 1.0           # max primary-position bonus (at 100% usage)


def _positional_assignment_score(player, pos_code, favor_offense=False, hand=None):
    """
    Score used only for positional assignment (not batting order).
    = batting wOBA + usage-scaled primary-position bonus + defense bonus.

    Batting base: platoon_score(player, hand) when opponent handedness is known,
    otherwise blended_woba (season overall). Ensures positional assignment is
    consistent with batting-order ranking.

    Primary-position bonus: scales with 3-year usage share at pos_code.
    Max _PRIMARY_POS_BONUS_MAX (.010, ~3 wRC+) at 100% usage; proportionally
    less for partial usage (e.g. 50% → +.005).

    Defense bonus scales by position class:
      Premium (C/2B/SS/CF): full scale  — 70 rating → +.028
      Corner  (3B/LF/RF):   half scale  — 70 rating → +.014
      1B:                   ~37.5% scale— 70 rating → +.0105
    favor_offense halves all three scales.
    """
    score = platoon_score(player, hand) if hand else (player.get("sort_score") or 0.0)

    # Usage-scaled primary position bonus, confidence-weighted by 3-year sample size.
    # sqrt(min(total_3yr_games / 100, 1.0)) prevents a player with 9 games at 100%
    # usage from outscoring a veteran with 300 games at 75% usage.
    usage = (player.get("pos_usage_pct") or {}).get(pos_code, 0.0)
    total_3yr = player.get("total_3yr_games") or 0
    usage_conf = math.sqrt(min(total_3yr / 100, 1.0))
    score += _PRIMARY_POS_BONUS_MAX * usage * usage_conf

    # Defense bonus — scale depends on position class
    fielding = (player.get("fielding_ratings") or {}).get(pos_code) \
               or player.get("rating_defense") or 0
    if pos_code in PREMIUM_DEFENSE_POSITIONS:
        scale = _DEFENSE_BONUS_SCALE_PREMIUM
    elif pos_code == 3:  # 1B
        scale = _DEFENSE_BONUS_SCALE_1B
    elif pos_code in CORNER_POSITIONS:
        scale = _DEFENSE_BONUS_SCALE_CORNER
    else:
        scale = 0.0
    if favor_offense:
        scale /= _FAVOR_OFFENSE_DIVISOR
    score += (fielding / 100.0) * scale
    return score


def _select_positional_nine(ranked, dh_used, primary_only=False,
                             forced_pos=None, forced_start_ids=None,
                             favor_offense=False, hand=None):
    """
    Assign one player per field position (C–RF), then optionally a DH.

    forced_pos:        {player_id: pos_code} — player is locked to that exact position,
                       bypassing eligibility floors (manager knows best).
    forced_start_ids:  set of player_ids — must appear in the lineup somewhere.
                       The algorithm places them at their primary position by priority;
                       if that position is taken they get the DH slot (or displace the
                       lowest-ranked non-forced DH candidate if DH is not in use).
    favor_offense:     reduces defense bonus weight at premium positions (prioritise batting).

    Returns a list of player dicts, each with an added 'assigned_pos' key.
    'forced' flag is set True on pre-assigned players for HTML badge display.
    """
    forced_pos = forced_pos or {}
    forced_start_ids = forced_start_ids or set()

    selected: dict = {}   # pos_code -> player dict
    used_ids: set = set()

    # ── Step 1: Pre-assign position-forced players ────────────────────────────
    # These bypass eligibility floors entirely — manager override is explicit.
    for pid, pos_code in forced_pos.items():
        player = next((p for p in ranked if p["player_id"] == pid), None)
        if player is None:
            continue
        if pos_code == 0:   # DH — handled after field positions
            continue
        if pos_code not in FIELD_POSITIONS:
            continue
        if pos_code in selected:
            existing = selected[pos_code]
            raise ValueError(
                f"Forced-start conflict: {player['first_name']} {player['last_name']} and "
                f"{existing['first_name']} {existing['last_name']} are both forced to "
                f"{POS_MAP[pos_code]}. Remove one override."
            )
        p = dict(player)
        label = POS_MAP[pos_code]
        if player.get("position") != pos_code:
            label += "*"
        p["assigned_pos"] = label
        p["forced"] = True
        selected[pos_code] = p
        used_ids.add(pid)

    # ── Step 2: Build eligibility maps for the remaining positions ────────────
    # Three tiers:
    #   by_pos       — meets floor + games threshold; natural fit for the position
    #   secondary_pos— meets floor + games BUT player's primary is a batter position
    #                  (1B/3B/LF/RF); at premium spots they defer to natural defenders
    #   emergency_pos— rating > 0 only; last resort when nothing else available
    by_pos: dict = {pos: [] for pos in FIELD_POSITIONS}
    secondary_pos: dict = {pos: [] for pos in FIELD_POSITIONS}
    emergency_pos: dict = {pos: [] for pos in FIELD_POSITIONS}
    for p in ranked:
        if p["player_id"] in used_ids:
            continue
        primary = p.get("position")
        # Boost forced-start-ids to front of their primary position queue
        is_forced = p["player_id"] in forced_start_ids
        if primary_only:
            if primary in FIELD_POSITIONS:
                if is_forced:
                    by_pos[primary].insert(0, p)
                else:
                    by_pos[primary].append(p)
        else:
            if primary in FIELD_POSITIONS:
                if is_forced:
                    by_pos[primary].insert(0, p)
                else:
                    by_pos[primary].append(p)
            for pos_code, rating in (p.get("fielding_ratings") or {}).items():
                if pos_code == primary or pos_code not in FIELD_POSITIONS:
                    continue
                games = (p.get("pos_games") or {}).get(pos_code, 0)
                if rating > 0:
                    emergency_pos[pos_code].append(p)
                # Premium positions use a higher floor (50 vs 40 for corners)
                floor = MIN_FIELDING_RATING_PREMIUM if pos_code in PREMIUM_DEFENSE_POSITIONS \
                        else MIN_FIELDING_RATING
                if rating >= floor and games >= MIN_POS_GAMES:
                    # Batter-primary players defer to natural defenders at premium spots
                    if pos_code in PREMIUM_DEFENSE_POSITIONS and primary in BATTER_POSITIONS:
                        secondary_pos[pos_code].append(p)
                    else:
                        by_pos[pos_code].append(p)

    # ── Step 3: Fill remaining positions in scarcity order ───────────────────
    def _scarcity_key(pos):
        if pos in selected:
            return (999, 0)   # already filled
        return (len(by_pos[pos]), 0 if pos in PREMIUM_DEFENSE_POSITIONS else 1)

    fill_order = sorted(FIELD_POSITIONS, key=_scarcity_key)

    for pos_code in fill_order:
        if pos_code in selected:
            continue
        standard_candidates = [p for p in by_pos[pos_code] if p["player_id"] not in used_ids]
        emergency_used = False
        if standard_candidates:
            candidates = standard_candidates
        else:
            # Secondary tier: batter-primary players who meet the floor but defer to naturals
            secondary_candidates = [p for p in secondary_pos[pos_code] if p["player_id"] not in used_ids]
            if secondary_candidates:
                candidates = secondary_candidates
            else:
                candidates = [p for p in emergency_pos[pos_code] if p["player_id"] not in used_ids]
                emergency_used = bool(candidates)
        if not candidates:
            continue
        # Forced-start players win ties; otherwise use positional score
        best = max(candidates, key=lambda p: (
            1 if p["player_id"] in forced_start_ids else 0,
            _positional_assignment_score(p, pos_code, favor_offense=favor_offense,
                                         hand=hand),
        ))
        player = dict(best)
        label = POS_MAP[pos_code]
        if best.get("position") != pos_code:
            label += "*"
        player["assigned_pos"] = label
        if best["player_id"] in forced_start_ids:
            player["forced"] = True
        if emergency_used:
            player["emergency"] = True
        selected[pos_code] = player
        used_ids.add(best["player_id"])

    # ── Step 4: DH slot ───────────────────────────────────────────────────────
    result = [selected[k] for k in FIELD_POSITIONS if k in selected]
    if dh_used:
        # Forced DH (pos_code == 0 in forced_pos)
        forced_dh_pid = next((pid for pid, pc in forced_pos.items() if pc == 0), None)
        if forced_dh_pid and forced_dh_pid not in used_ids:
            player = next((p for p in ranked if p["player_id"] == forced_dh_pid), None)
            if player:
                dh = dict(player)
                dh["assigned_pos"] = "DH"
                dh["forced"] = True
                result.append(dh)
                used_ids.add(forced_dh_pid)
        else:
            # Normal DH: best remaining batter by rank
            extras = [p for p in ranked if p["player_id"] not in used_ids
                      and p.get("position") in FIELD_POSITIONS]
            if extras:
                dh = dict(extras[0])
                dh["assigned_pos"] = "DH"
                result.append(dh)
                used_ids.add(extras[0]["player_id"])

    # ── Step 4b: Defensive swap pass ─────────────────────────────────────────
    # If the DH is a better defender at any filled field position than the current
    # fielder, swap them. Both players remain in the lineup so batting is unchanged;
    # only the defensive assignment improves. Skip if either player is force-locked.
    if dh_used:
        dh_player = next((p for p in result if p.get("assigned_pos") == "DH"), None)
        if dh_player and not dh_player.get("forced"):
            dh_fielding = dh_player.get("fielding_ratings") or {}
            dh_games    = dh_player.get("pos_games") or {}
            best_swap_pos = None
            best_improvement = 0
            for pos_code in FIELD_POSITIONS:
                if pos_code not in selected:
                    continue
                fielder = selected[pos_code]
                if fielder.get("forced"):
                    continue
                floor = MIN_FIELDING_RATING_PREMIUM if pos_code in PREMIUM_DEFENSE_POSITIONS \
                        else MIN_FIELDING_RATING
                dh_rating = dh_fielding.get(pos_code, 0)
                if dh_rating < floor or dh_games.get(pos_code, 0) < MIN_POS_GAMES:
                    continue
                current_rating = (fielder.get("fielding_ratings") or {}).get(pos_code, 0)
                improvement = dh_rating - current_rating
                if improvement > best_improvement:
                    best_improvement = improvement
                    best_swap_pos = pos_code
            if best_swap_pos is not None:
                old_fielder = selected[best_swap_pos]
                # DH takes the field position
                new_fielder = dict(dh_player)
                label = POS_MAP[best_swap_pos]
                if dh_player.get("position") != best_swap_pos:
                    label += "*"
                new_fielder["assigned_pos"] = label
                new_fielder.pop("forced", None)
                # Old fielder becomes DH
                new_dh = dict(old_fielder)
                new_dh["assigned_pos"] = "DH"
                new_dh.pop("forced", None)
                selected[best_swap_pos] = new_fielder
                result = [selected[k] for k in FIELD_POSITIONS if k in selected]
                result.append(new_dh)

    # ── Step 5: Guarantee forced_start_ids are in the lineup ─────────────────
    # If a forced player still isn't assigned (edge case: primary pos taken by
    # a position-locked player), append them as an extra DH-style slot.
    selected_ids = {p["player_id"] for p in result}
    for pid in forced_start_ids:
        if pid in selected_ids:
            continue
        player = next((p for p in ranked if p["player_id"] == pid), None)
        if player is None:
            continue
        p = dict(player)
        p["assigned_pos"] = "DH [F]"
        p["forced"] = True
        result.append(p)

    return result


def build_lineup(ranked, philosophy, max_slots, primary_only=False,
                 forced_pos=None, forced_start_ids=None, favor_offense=False,
                 hand=None):
    """
    Select one player per defensive position, assign the DH slot if applicable,
    then apply the philosophy's batting-order slot mapping to the selected nine.
    """
    dh_used = max_slots == 9
    selected = _select_positional_nine(
        ranked, dh_used, primary_only=primary_only,
        forced_pos=forced_pos, forced_start_ids=forced_start_ids,
        favor_offense=favor_offense, hand=hand,
    )
    if not selected:
        return {}

    # Re-rank the selected players using the same original sort order so the
    # philosophy's slot mapping (which rank goes to which batting slot) is correct.
    selected_ids = {p["player_id"] for p in selected}
    re_ranked = [p for p in ranked if p["player_id"] in selected_ids]

    # Build a quick lookup so we can restore the assigned_pos after re-ranking
    assigned_pos = {p["player_id"]: p["assigned_pos"] for p in selected}

    slot_map = TRADITIONAL_SLOT_MAP if philosophy == "traditional" else MODERN_SLOT_MAP
    lineup = {}
    for slot, rank_idx in slot_map.items():
        if slot > max_slots:
            continue
        if rank_idx < len(re_ranked):
            p = dict(re_ranked[rank_idx])
            p["assigned_pos"] = assigned_pos[p["player_id"]]
            lineup[slot] = p

    return lineup


def score_alternation(lineup):
    """Score L/R/S alternation 0–10 (10 = perfect alternation)."""
    bats_seq = [lineup[s].get("bats") or 1 for s in range(1, 10) if s in lineup]
    score = 10
    run = 1
    for i in range(1, len(bats_seq)):
        curr, prev = bats_seq[i], bats_seq[i - 1]
        if curr == 3 or prev == 3:  # switch hitter: reset run, no penalty
            run = 1
            continue
        if curr == prev:
            run += 1
            if run == 3: score -= 1
            if run == 4: score -= 1
            if run >= 5: score -= 1
        else:
            run = 1
    return max(0, score)


def handedness_pattern(lineup):
    return "-".join(BATS_MAP.get(lineup[s].get("bats") or 1, "?") for s in range(1, 10) if s in lineup)


# ── HTML rendering ────────────────────────────────────────────────────────────

def temp_emoji(flag):
    """Inline emoji badge appended to player name — replaces the old Temp column."""
    emojis = dict(
        hot_extreme=' 🔥🔥',
        hot=' 🔥',
        cold=' 🧊',
        cold_extreme=' 🧊🧊',
        neutral='',
    )
    return emojis.get(flag, '')


def iso_td(val):
    if val is None:
        return "<td>—</td>"
    if val >= 0.200: c = "#1a7a1a"
    elif val >= 0.120: c = "#cc7700"
    else: c = "#cc2222"
    return f'<td style="color:{c};font-weight:bold">{val:.3f}</td>'


def woba_td(val):
    if val is None:
        return "<td>—</td>"
    c = woba_color(val)
    return f'<td style="color:{c};font-weight:bold">{val:.3f}</td>'


def wrc_td(val):
    if val is None:
        return "<td>—</td>"
    c = wrc_color(val)
    return f'<td style="color:{c};font-weight:bold">{int(val)}</td>'


def build_html(team_name, team_abbr, philosophy, hand, lineup, all_players,
               alternation_score, dh_used, save_name, excluded_names,
               primary_only=False, forced_bench=None, fatigue_threshold=None,
               fatigue_benched=None, favor_offense=False, args_str="",
               args_display=""):
    now = datetime.now()
    now_str = now.strftime("%B %d, %Y %I:%M %p")
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S")
    hand_label = {"L": "vs LHP", "R": "vs RHP"}.get(hand, "Handedness Not Specified")
    phil_label = PHIL_LABELS.get(philosophy, philosophy.title())

    # Build a descriptive title that encodes all active options
    _title_parts = [f"Lineup Optimizer \u2014 {team_name}", phil_label]
    if hand:
        _title_parts.append(hand_label)
    if primary_only:
        _title_parts.append("Primary Only")
    if favor_offense:
        _title_parts.append("Favor Offense")
    report_title = " | ".join(_title_parts)

    if alternation_score >= 8:
        alt_color, alt_label = "#155724", "Excellent"
        alt_bg = "#d4edda"
    elif alternation_score >= 6:
        alt_color, alt_label = "#856404", "Good"
        alt_bg = "#fff3cd"
    else:
        alt_color, alt_label = "#721c24", "Poor"
        alt_bg = "#f8d7da"

    pattern_str = handedness_pattern(lineup)

    # ── Lineup card rows ──────────────────────────────────────────────────
    lineup_rows = []
    for slot in range(1, (10 if dh_used else 9)):
        if slot not in lineup:
            continue
        p = lineup[slot]
        adv = p.get("adv") or {}
        name = html_mod.escape(f"{p['first_name']} {p['last_name']}")
        pos_str = p.get("assigned_pos") or POS_MAP.get(p.get("position"), "?")
        bats_str = BATS_MAP.get(p.get("bats") or 1, "R")
        star_badge = ' <span style="color:#f0c040;font-weight:bold" title="Star player">★</span>' if is_star(p) else ""
        rolling = p.get("rolling") or {}
        r_woba = rolling.get("rolling_woba")

        pa_val = adv.get("pa") or 0
        pa_style = ' style="color:#cc7700;font-weight:bold"' if pa_val < 80 else ' style="color:#555"'
        fat_val = p.get("fatigue_points") or 0
        fat_color = _fatigue_color(fat_val)
        fat_cell = f'<td style="color:{fat_color};font-weight:bold">{fat_val}</td>'
        force_badge = ' <span class="tag tag-force" title="Manager force-start override">[F]</span>' if p.get("forced") else ""
        emg_badge = ' <span class="tag tag-bad" title="Emergency assignment — no qualified player met rating/games floors">[!]</span>' if p.get("emergency") else ""
        temp_badge = temp_emoji(p.get('temp_flag', 'neutral'))

        if hand == "L":
            woba_cell = f'<td>{fmt_woba(adv.get("woba_vs_lhp"))}</td>'
            rating_now_val = p.get("rating_now_lhp") or 0
            conf_val = p.get("confidence_lhp") or 0
        elif hand == "R":
            woba_cell = f'<td>{fmt_woba(adv.get("woba_vs_rhp"))}</td>'
            rating_now_val = p.get("rating_now_rhp") or 0
            conf_val = p.get("confidence_rhp") or 0
        else:
            woba_cell = woba_td(adv.get('woba'))
            rating_now_val = p.get("rating_now") or 0
            conf_val = p.get("confidence") or 0

        rating_now_color = grade_color(rating_now_val)
        conf_color = "#1a7a1a" if conf_val >= 0.8 else "#cc7700" if conf_val >= 0.4 else "#cc2222"

        lineup_rows.append(f"""
          <tr>
            <td style="font-size:16px;font-weight:900;color:#1a1a2e;width:28px">{slot}</td>
            <td class="left">{name}{temp_badge}{star_badge}{force_badge}{emg_badge}</td>
            <td>{pos_str}</td>
            <td>{bats_str}</td>
            {wrc_td(adv.get('wrc_plus'))}
            <td{pa_style}>{fmt_int(pa_val) if pa_val else "—"}</td>
            <td>{fmt_woba(adv.get('obp'))}</td>
            {iso_td(adv.get('iso'))}
            {woba_cell}
            <td style="background:#e8f5e9;color:{rating_now_color};font-weight:bold">{rating_now_val:.0f}</td>
            <td style="color:{conf_color};font-weight:bold">{conf_val:.2f}</td>
            {fat_cell}
            <td style="color:#555">{int(p.get('rating_baserunning') or 0)}</td>
          </tr>""")
    lineup_rows_html = "\n".join(lineup_rows)

    # ── Full roster rows ──────────────────────────────────────────────────
    lineup_pids = {p["player_id"] for p in lineup.values()}
    _fb_lower = {n.lower() for n in (forced_bench or [])}
    _fatb_lower = {n.lower() for n in (fatigue_benched or [])}
    roster_rows = []
    for p in sorted(all_players, key=lambda x: (x["player_id"] not in lineup_pids,
                                                  ((x.get("adv") or {}).get("pa") or 0) == 0,
                                                  -(x.get("sort_score") or 0))):
        adv = p.get("adv") or {}
        in_lineup = p["player_id"] in lineup_pids
        name = html_mod.escape(f"{p['first_name']} {p['last_name']}")
        pos_str = POS_MAP.get(p.get("position"), "?")
        bats_str = BATS_MAP.get(p.get("bats") or 1, "R")
        rolling = p.get("rolling") or {}
        r_woba = rolling.get("rolling_woba")
        row_style = "" if in_lineup else ' style="opacity:0.65"'
        role_cell = ('<td class="left"><span class="tag tag-good">Starting</span></td>'
                     if in_lineup else
                     '<td class="left"><span class="tag tag-neutral">Bench</span></td>')

        all_forced_bench_lower = _fb_lower
        fat_benched_lower = _fatb_lower
        full_name_lower = f"{p['first_name']} {p['last_name']}".lower()
        is_forced_bench = full_name_lower in all_forced_bench_lower
        is_fat_benched = full_name_lower in fat_benched_lower
        if is_forced_bench:
            role_cell = '<td class="left"><span class="tag tag-force">[F] Bench</span></td>'
        elif is_fat_benched:
            role_cell = '<td class="left"><span class="tag tag-bad">Fatigued</span></td>'

        pa_val = adv.get("pa") or 0
        pa_style = ' style="color:#cc7700;font-weight:bold"' if pa_val < 80 else ' style="color:#555"'
        fat_val = p.get("fatigue_points") or 0
        fat_color = _fatigue_color(fat_val)
        force_badge = ' <span class="tag tag-force" title="Manager force-start override">[F]</span>' if p.get("forced") else ""
        temp_badge = temp_emoji(p.get('temp_flag', 'neutral'))

        if hand == "L":
            woba_cell = f'<td>{fmt_woba(adv.get("woba_vs_lhp"))}</td>'
            rating_now_val = p.get("rating_now_lhp") or 0
            conf_val = p.get("confidence_lhp") or 0
        elif hand == "R":
            woba_cell = f'<td>{fmt_woba(adv.get("woba_vs_rhp"))}</td>'
            rating_now_val = p.get("rating_now_rhp") or 0
            conf_val = p.get("confidence_rhp") or 0
        else:
            woba_cell = woba_td(adv.get('woba'))
            rating_now_val = p.get("rating_now") or 0
            conf_val = p.get("confidence") or 0

        rating_now_color = grade_color(rating_now_val)
        conf_color = "#1a7a1a" if conf_val >= 0.8 else "#cc7700" if conf_val >= 0.4 else "#cc2222"

        roster_rows.append(f"""
          <tr{row_style}>
            <td class="left">{name}{temp_badge}{force_badge}</td>
            <td>{pos_str}</td>
            <td>{bats_str}</td>
            {wrc_td(adv.get('wrc_plus'))}
            <td{pa_style}>{fmt_int(pa_val) if pa_val else "—"}</td>
            <td>{fmt_woba(adv.get('obp'))}</td>
            {iso_td(adv.get('iso'))}
            {woba_cell}
            <td style="background:#e8f5e9;color:{rating_now_color};font-weight:bold">{rating_now_val:.0f}</td>
            <td style="color:{conf_color};font-weight:bold">{conf_val:.2f}</td>
            <td style="color:{fat_color};font-weight:bold">{fat_val}</td>
            <td style="color:#555">{int(p.get('rating_baserunning') or 0)}</td>
            {role_cell}
          </tr>""")
    roster_rows_html = "\n".join(roster_rows)

    # ── Override / exclusion banners ──────────────────────────────────────
    excl_html = ""
    if excluded_names:
        excl_list = ", ".join(html_mod.escape(n) for n in excluded_names)
        excl_html += f'<div class="stale-banner" style="margin-top:8px">Excluded (without): <b>{excl_list}</b></div>'
    if forced_bench:
        fb_list = ", ".join(html_mod.escape(n) for n in forced_bench)
        excl_html += f'<div class="stale-banner-blue" style="margin-top:4px"><b>[F] Manager bench:</b> {fb_list}</div>'
    if fatigue_benched:
        fat_list = ", ".join(html_mod.escape(n) for n in fatigue_benched)
        thr_label = f" (threshold: {fatigue_threshold}%)" if fatigue_threshold is not None else ""
        excl_html += f'<div class="stale-banner-red" style="margin-top:4px"><b>Fatigued — auto-benched{thr_label}:</b> {fat_list}</div>'
    if favor_offense:
        excl_html += '<div class="stale-banner" style="margin-top:4px"><b>Favor Offense:</b> defense weight reduced at C / 2B / SS / CF — batting quality has more influence over positional assignments.</div>'

    css = get_report_css("1120px")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html_mod.escape(report_title)}</title>
  <meta name="ootp-skill" content="lineup-optimizer">
  <meta name="ootp-args" content="{html_mod.escape(args_str)}">
  <meta name="ootp-args-display" content="{html_mod.escape(args_display)}">
  <meta name="ootp-save" content="{html_mod.escape(save_name)}">
  <meta name="ootp-generated" content="{now_iso}">
  <style>{css}
    .pattern-str {{ font-family: monospace; font-size: 14px; letter-spacing: 3px;
                   color: #f0c040; font-weight: bold; }}
    .temp-legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 8px 0;
                   font-size: 12px; color: #ccc; }}
  </style>
</head>
<body>
<div class="container">

  <div class="page-header">
    <div class="header-top">
      <div>
        <div class="player-name">{html_mod.escape(team_name)}</div>
        <div class="player-meta">Lineup Optimizer &mdash;
          <b>{html_mod.escape(phil_label)}</b> &mdash; {hand_label}
        </div>
        <div class="player-meta">Generated {now_str}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:13px;color:#aaa;margin-bottom:4px">{hand_label}</div>
        <div class="pattern-str">{pattern_str}</div>
        <div style="font-size:12px;color:#aaa;margin-top:4px">L/R/S batting pattern</div>
      </div>
    </div>
    <div class="flags" style="margin-top:14px">
      <span class="flag flag-blue">Philosophy: {html_mod.escape(phil_label)}</span>
      <span class="flag" style="background:{alt_bg};color:{alt_color}">
        Alternation: {alternation_score}/10 &mdash; {alt_label}
      </span>
      {'<span class="flag flag-green">DH In Use</span>' if dh_used else '<span class="flag flag-neutral">No DH</span>'}
      {'<span class="flag flag-yellow">Primary Position Only</span>' if primary_only else '<span class="flag flag-blue">Multi-Position</span>'}
    </div>
    <div class="temp-legend">
      <span>🔥🔥 extreme hot streak (30-day wOBA &ge;+.060)</span>
      <span>🔥 hot (+.030&ndash;.059)</span>
      <span>🧊 cold (&minus;.030&ndash;.059)</span>
      <span>🧊🧊 extreme cold (&le;&minus;.060)</span>
      <span style="color:#f0c040;font-weight:bold">★</span>&nbsp;= Star (wOBA &ge;.370 or Rating &ge;70) &mdash; cold-streak penalty halved
    </div>
    {excl_html}
  </div>

  <!-- Lineup Card -->
  <div class="section">
    <div class="section-title">Batting Order</div>
    <table>
      <thead>
        <tr>
          <th style="width:36px">#</th>
          <th class="left">Name</th>
          <th>Pos</th><th>Bats</th>
          <th>wRC+</th><th title="Career MLB plate appearances — amber = low sample, ranking adjusted">PA</th>
          <th>OBP</th><th>ISO</th>
          <th>{"vs LHP" if hand == "L" else "vs RHP" if hand == "R" else "wOBA"}</th>
          <th title="Performance rating (rating_now or split equivalent)">Rating</th>
          <th title="Statistical confidence 0–1. Red = thin sample, green = established">Conf</th>
          <th title="Fatigue 0–100. Red ≥70, amber ≥40, green &lt;40">Fat.</th>
          <th>Speed</th>
        </tr>
      </thead>
      <tbody>
{lineup_rows_html}
      </tbody>
    </table>
    <div class="split-note">
      wOBA column shows career split vs today&rsquo;s opponent handedness (or overall when unspecified).
      🔥 = hot streak (30-day wOBA +.030+), 🔥🔥 = extreme (+.060+).
      🧊 = cold (−.030+), 🧊🧊 = extreme (−.060+).<br>
      * = playing out of primary position.
      C, 2B, SS, CF selection applies a small defense tiebreaker.<br>
      <b>PA (amber = &lt;80):</b> Low-PA players rank by talent rating until they have meaningful MLB samples.<br>
      <b>[F]</b> = manager override (force-start or force-position). Bypasses eligibility floors.
      <b>Fat.</b> = fatigue 0&ndash;100 (green &lt;40, amber &ge;40, red &ge;70).
      Use <code>fatigue &lt;N&gt;</code> in skill args to auto-bench players above a threshold.
    </div>
  </div>

  <!-- Analysis Placeholder -->
  <div class="section">
    <div class="section-title">Lineup Analysis</div>
    <!-- LINEUP_ANALYSIS -->
  </div>

  <!-- Full Roster -->
  <div class="section">
    <div class="section-title">Full Roster — Batter Stats</div>
    <table>
      <thead>
        <tr>
          <th class="left">Name</th><th>Pos</th><th>Bats</th>
          <th>wRC+</th><th title="Career MLB plate appearances — amber = low sample, ranking adjusted">PA</th>
          <th>OBP</th><th>ISO</th>
          <th>{"vs LHP" if hand == "L" else "vs RHP" if hand == "R" else "wOBA"}</th>
          <th title="Performance rating (rating_now or split equivalent)">Rating</th>
          <th title="Statistical confidence 0–1. Red = thin sample, green = established">Conf</th>
          <th title="Fatigue 0–100">Fat.</th><th>Speed</th>
          <th class="left">Role</th>
        </tr>
      </thead>
      <tbody>
{roster_rows_html}
      </tbody>
    </table>
    <div class="split-note">
      wOBA column reflects career PA vs today&rsquo;s opponent handedness (or overall when unspecified).
      Values may be sparse at low sample sizes. Bench players are dimmed.
    </div>
  </div>

</div>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def query_lineup(save_name, team_query=None, philosophy="modern",
                 opponent_hand=None, excluded_names=None,
                 primary_only=False, forced_starts=None,
                 forced_bench=None, fatigue_threshold=None,
                 favor_offense=False):
    """Query all data and compute the lineup without generating HTML or checking cache.

    Returns the complete data_dict (which includes 'slug', '_team_name', '_team_abbr',
    '_lineup', '_batters', '_alt_score', '_dh_used', '_fatigue_benched', '_args_str'),
    or None if the team is not found or there are no eligible batters.
    """
    if philosophy not in PHILOSOPHIES:
        philosophy = "modern"
    excluded_names = list(excluded_names or [])
    forced_starts = forced_starts or []
    forced_bench = forced_bench or []
    hand = (opponent_hand or "").upper()[:1]
    if hand not in ("L", "R"):
        hand = None

    engine = get_engine(save_name)
    with engine.connect() as conn:
        team_id, team_name, team_abbr = resolve_team(conn, team_query)
        if not team_id:
            return None

        dh_used = get_dh_used(conn, team_id)
        batters = load_roster_batters(conn, team_id)
        if not batters:
            return None

        player_ids = [p["player_id"] for p in batters]
        adv_stats = load_batter_stats(conn, player_ids)
        rolling_stats = load_30day_stats(conn, player_ids)
        fielding_ratings = load_fielding_ratings(conn, player_ids)
        pos_games = load_position_games(conn, player_ids)

        # Full-league anchors — use MLB-wide averages, not roster averages
        league_avg_woba = conn.execute(text(f"""
            SELECT AVG(b.woba) FROM batter_advanced_stats b
            JOIN players p ON p.player_id = b.player_id
            WHERE p.league_id = {MLB_LEAGUE_ID} AND b.pa >= 100
        """)).scalar() or 0.320
        avg_rating_offense = conn.execute(text("""
            SELECT AVG(pr.rating_offense) FROM player_ratings pr
            JOIN batter_advanced_stats b ON b.player_id = pr.player_id
            WHERE pr.player_type = 'batter' AND b.pa >= 100
        """)).scalar() or 50.0

    # Enrich player dicts with stats, fielding, and temperature
    for p in batters:
        pid = p["player_id"]
        p["adv"] = adv_stats.get(pid) or {}
        p["rolling"] = rolling_stats.get(pid) or {}
        p["fielding_ratings"] = fielding_ratings.get(pid) or {}
        _pg = pos_games.get(pid) or {}
        p["pos_games"]        = _pg.get("games") or {}
        p["pos_usage_pct"]    = _pg.get("usage_pct") or {}
        p["total_3yr_games"]  = _pg.get("total_3yr_games") or 0
        season_woba = p["adv"].get("woba")
        r = p["rolling"]
        p["temp_flag"] = temperature_flag(season_woba, r.get("rolling_woba"), r.get("rolling_pa"))
        p["bats_str"] = BATS_MAP.get(p.get("bats") or 1, "R")
        p["forced"] = False

    # Sort score: rating_now × confidence from player_ratings.
    # Precomputed in ratings.compute — no regression needed here.
    for p in batters:
        rating_now = p.get("rating_now")
        confidence = p.get("confidence")
        p["sort_score"] = (50.0 if rating_now is None else rating_now) * (0.5 if confidence is None else confidence)

    # Apply fatigue auto-bench
    fatigue_benched = []
    if fatigue_threshold is not None:
        for p in batters:
            fat = p.get("fatigue_points") or 0
            if fat >= fatigue_threshold:
                fatigue_benched.append(f"{p['first_name']} {p['last_name']}")

    # Merge all exclusions
    all_excluded = set(n.lower() for n in excluded_names + forced_bench + fatigue_benched)
    if all_excluded:
        batters = [
            p for p in batters
            if f"{p['first_name']} {p['last_name']}".lower() not in all_excluded
        ]

    # Resolve forced_starts to player_ids
    forced_pos: dict = {}
    forced_start_ids: set = set()
    for fs in forced_starts:
        player = _resolve_player_name(fs["name"], batters)
        if player is None:
            continue
        pid = player["player_id"]
        forced_start_ids.add(pid)
        pos_code = fs.get("pos")
        if pos_code is not None:
            forced_pos[pid] = pos_code

    max_slots = 9 if dh_used else 8
    ranked = rank_players(batters, philosophy, hand)
    lineup = build_lineup(ranked, philosophy, max_slots, primary_only=primary_only,
                          forced_pos=forced_pos, forced_start_ids=forced_start_ids,
                          favor_offense=favor_offense, hand=hand)

    alt_score = score_alternation(lineup)

    # Reconstruct args string
    _pos_names = {2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF", 0: "DH"}
    _args_parts = []
    if team_query:
        _args_parts.append(team_query)
    _args_parts.append(philosophy)
    if hand:
        _args_parts.append("vs LHP" if hand == "L" else "vs RHP")
    if primary_only:
        _args_parts.append("primary")
    if favor_offense:
        _args_parts.append("favor-offense")
    for fs in forced_starts:
        pos_code = fs.get("pos")
        if pos_code is not None:
            _args_parts.append(f"{fs['name']} starts at {_pos_names.get(pos_code, str(pos_code))}")
        else:
            _args_parts.append(f"{fs['name']} starts")
    for fb in forced_bench:
        _args_parts.append(f"{fb} bench")
    for ex in excluded_names:
        _args_parts.append(f"without {ex}")
    if fatigue_threshold is not None:
        _args_parts.append(f"fatigue {fatigue_threshold}")
    args_str = " ".join(_args_parts)

    # Build data_dict for agent
    hand_key = hand or "any"
    pos_key = "primary" if primary_only else "multi"
    fd_key = "_fo" if favor_offense else ""
    slug = f"{team_abbr.lower()}_{philosophy}_{hand_key}_{pos_key}{fd_key}"

    lineup_summary = []
    for slot in range(1, 10):
        if slot not in lineup:
            continue
        p = lineup[slot]
        adv = p.get("adv") or {}
        lineup_summary.append(dict(
            slot=slot,
            name=f"{p['first_name']} {p['last_name']}",
            pos=p.get("assigned_pos") or POS_MAP.get(p.get("position"), "?"),
            bats=BATS_MAP.get(p.get("bats") or 1, "R"),
            woba=adv.get("woba"),
            wrc_plus=adv.get("wrc_plus"),
            temp=p.get("temp_flag", "neutral"),
            star=is_star(p),
        ))

    wrc_vals = [p["wrc_plus"] for p in lineup_summary if p["wrc_plus"] is not None]
    avg_wrc = round(sum(wrc_vals) / len(wrc_vals), 1) if wrc_vals else None
    hot_players = [p["name"] for p in lineup_summary if p["temp"] in ("hot", "hot_extreme")]
    cold_stars = [p["name"] for p in lineup_summary if p["temp"] in ("cold", "cold_extreme") and p["star"]]
    lhb_count = sum(1 for p in lineup_summary if p["bats"] == "L")
    rhb_count = sum(1 for p in lineup_summary if p["bats"] == "R")

    data_dict = dict(
        team_name=team_name,
        team_abbr=team_abbr,
        philosophy=philosophy,
        phil_label=PHIL_LABELS.get(philosophy, philosophy),
        opponent_hand=hand or "None",
        hand_label=dict(L="vs LHP", R="vs RHP").get(hand, "Neutral"),
        alternation_score=alt_score,
        dh_used=int(dh_used),
        avg_lineup_wrc_plus=avg_wrc,
        hot_players=", ".join(hot_players) or "None",
        cold_stars=", ".join(cold_stars) or "None",
        excluded_players=", ".join(excluded_names) or "None",
        primary_only=int(primary_only),
        lhb_count=lhb_count,
        rhb_count=rhb_count,
        lineup_json=json.dumps([
            dict(slot=p["slot"], name=p["name"], pos=p["pos"],
                 bats=p["bats"], woba=p["woba"], wrc_plus=p["wrc_plus"])
            for p in lineup_summary
        ]),
        slug=slug,
        save_name=save_name,
        # Private keys for HTML generation
        _team_name=team_name,
        _team_abbr=team_abbr,
        _lineup=lineup,
        _batters=batters,
        _alt_score=alt_score,
        _dh_used=dh_used,
        _fatigue_benched=fatigue_benched,
        _args_str=args_str,
        _hand=hand,
        _excluded_names=excluded_names,
        _forced_bench=forced_bench,
        _primary_only=primary_only,
        _fatigue_threshold=fatigue_threshold,
        _favor_offense=favor_offense,
    )
    return data_dict


def generate_lineup_report(save_name, team_query=None, philosophy="modern",
                           opponent_hand=None, excluded_names=None,
                           primary_only=False, forced_starts=None,
                           forced_bench=None, fatigue_threshold=None,
                           favor_offense=False, raw_args=""):
    """
    Generate (or return cached) lineup optimizer report.

    forced_starts:     list of {"name": str, "pos": int|None} — player is guaranteed
                       a lineup spot; if pos is given they're locked to that position
                       (bypasses eligibility floors).
    forced_bench:      list of player name strings — excluded from lineup regardless.
    fatigue_threshold: int 0-100 — auto-bench any player whose fatigue_points >= this.
                       When set, also bypasses cache.
    favor_offense:     bool — reduces defense weight at premium positions (C, 2B,
                       SS, CF), overriding moderate batting advantages.

    Returns:
        (path_str, data_dict)  on generation
        (path_str, None)       on cache hit
        (None, None)           on error / team not found
    """
    if philosophy not in PHILOSOPHIES:
        philosophy = "modern"
    excluded_names = list(excluded_names or [])
    forced_starts = forced_starts or []
    forced_bench = forced_bench or []
    hand = (opponent_hand or "").upper()[:1]
    if hand not in ("L", "R"):
        hand = None

    # Cache check requires team_abbr — resolve team with a quick DB call
    engine = get_engine(save_name)
    with engine.connect() as conn:
        team_id, team_name, team_abbr = resolve_team(conn, team_query)
        if not team_id:
            return None, None

        args_key = dict(
            philosophy=philosophy,
            hand=hand,
            primary_only=primary_only,
            excluded=sorted(excluded_names),
            forced_starts=sorted(str(fs) for fs in (forced_starts or [])),
            forced_bench=sorted(forced_bench or []),
            fatigue_threshold=fatigue_threshold,
            favor_offense=favor_offense,
            raw_args=raw_args.strip().lower(),
        )
        report_dir = get_reports_dir(save_name, "lineups")
        report_path = report_dir / report_filename("lineup_" + team_abbr.lower(), args_key)
        last_import = get_last_import_time()
        if report_path.exists() and last_import:
            if report_path.stat().st_mtime > datetime.fromisoformat(last_import).timestamp():
                return str(report_path), None

    # Cache miss — query all data
    data = query_lineup(save_name, team_query=team_query, philosophy=philosophy,
                        opponent_hand=opponent_hand, excluded_names=excluded_names,
                        primary_only=primary_only, forced_starts=forced_starts,
                        forced_bench=forced_bench, fatigue_threshold=fatigue_threshold,
                        favor_offense=favor_offense)
    if data is None:
        return None, None

    # Extract private keys for HTML
    team_name = data.pop("_team_name")
    team_abbr = data.pop("_team_abbr")
    lineup = data.pop("_lineup")
    batters = data.pop("_batters")
    alt_score = data.pop("_alt_score")
    dh_used = data.pop("_dh_used")
    fatigue_benched = data.pop("_fatigue_benched")
    args_str = data.pop("_args_str")
    hand = data.pop("_hand")
    excluded_names = data.pop("_excluded_names")
    forced_bench = data.pop("_forced_bench")
    primary_only = data.pop("_primary_only")
    fatigue_threshold = data.pop("_fatigue_threshold")
    favor_offense = data.pop("_favor_offense")

    _disp = []
    if hand:
        _disp.append("vs LHP" if hand == "L" else "vs RHP")
    if primary_only:
        _disp.append("Primary only")
    if favor_offense:
        _disp.append("Favor offense")
    if excluded_names:
        names = ", ".join(excluded_names[:3]) + ("…" if len(excluded_names) > 3 else "")
        _disp.append(f"Excl: {names}")
    if forced_bench:
        _disp.append("Bench: " + ", ".join(forced_bench[:2]))
    if fatigue_threshold is not None:
        _disp.append(f"Fatigue ≤{fatigue_threshold}%")
    if raw_args.strip():
        _disp.append(raw_args.strip())
    args_display = " · ".join(_disp)

    html_content = build_html(
        team_name, team_abbr, philosophy, hand,
        lineup, batters, alt_score,
        dh_used, save_name, excluded_names,
        primary_only=primary_only,
        forced_bench=forced_bench,
        fatigue_threshold=fatigue_threshold,
        fatigue_benched=fatigue_benched,
        favor_offense=favor_offense,
        args_str=args_str,
        args_display=args_display,
    )
    write_report_html(report_path, html_content)

    return str(report_path), data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: lineup_optimizer.py <save_name> [philosophy] [L|R] [team_query]")
        sys.exit(1)
    save = sys.argv[1]
    phil = sys.argv[2] if len(sys.argv) > 2 else "modern"
    hd   = sys.argv[3] if len(sys.argv) > 3 else None
    tq   = sys.argv[4] if len(sys.argv) > 4 else None
    path, data = generate_lineup_report(save, team_query=tq, philosophy=phil, opponent_hand=hd)
    if path is None:
        print("ERROR: Team or data not found")
        sys.exit(1)
    print(f"CACHED:{path}" if data is None else f"GENERATED:{path}")
