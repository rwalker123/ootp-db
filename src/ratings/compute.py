"""Batch computation: build the player_ratings table (run after analytics)."""

import sys
import time

import numpy as np
import pandas as pd
from sqlalchemy import text

from config import (
    BATTER_WEIGHT_BASERUNNING,
    BATTER_WEIGHT_CLUBHOUSE,
    BATTER_WEIGHT_CONTACT,
    BATTER_WEIGHT_DEFENSE,
    BATTER_WEIGHT_DISCIPLINE,
    BATTER_WEIGHT_DURABILITY,
    BATTER_WEIGHT_OFFENSE,
    BATTER_WEIGHT_POTENTIAL,
    CEILING_GAP_THRESHOLD,
    DEVELOPMENT_EXPONENT,
    DEVELOPMENT_MAX_AGE,
    DEVELOPMENT_MIN_AGE,
    DEVELOPMENT_REALIZATION_MULT_MAX,
    DEVELOPMENT_REALIZATION_MULT_MIN,
    DEVELOPMENT_TRAIT_WEIGHT_ADAPTABILITY,
    DEVELOPMENT_TRAIT_WEIGHT_INTELLIGENCE,
    DEVELOPMENT_TRAIT_WEIGHT_WORK_ETHIC,
    INJURY_OVERALL_DEDUCTION,
    INJURY_PRONE_THRESHOLD,
    IP_REGRESSION_THRESHOLD,
    LEADER_OVERALL_BONUS,
    LEADER_THRESHOLD,
    OFFENSE_WRC_WEIGHT,
    OFFENSE_XWOBA_WEIGHT,
    OOTP_MAX_BLEND_WEIGHT,
    OOTP_RATING_SCALE_MIN,
    PA_REGRESSION_THRESHOLD,
    PITCHER_WEIGHT_CLUBHOUSE,
    PITCHER_WEIGHT_COMMAND,
    PITCHER_WEIGHT_CONTACT_SUPPRESSION,
    PITCHER_WEIGHT_DOMINANCE,
    PITCHER_WEIGHT_DURABILITY,
    PITCHER_WEIGHT_POTENTIAL,
    PITCHER_WEIGHT_ROLE_VALUE,
    PITCHER_WEIGHT_RUN_PREVENTION,
    REGRESSION_EXPONENT,
    RELIEVER_G_TARGET,
    STARTER_IP_TARGET,
    STARTER_MIN_GS,
    ELITE_WRC,
    WRC_CAP_HEADROOM,
    WRC_SCORE_FLOOR,
    WRC_UNKNOWN_DEFAULT,
    SCORE_MAX,
    PERCENTILE_AVG,
    PLATOON_LHP_PA_THRESHOLD,
    PLATOON_RHP_PA_THRESHOLD,
)
from ootp_db_constants import (
    MLB_LEAGUE_ID,
    MLB_LEVEL_ID,
    POS_PITCHER,
    SPLIT_CAREER_OVERALL,
    SPLIT_TEAM_PITCHING_OVERALL,
)
from shared_css import get_write_engine

from .constants import BATTER_WEIGHTS, PITCHER_WEIGHTS, SCALE_RANGE
from .defense_blend import defense_score_from_rating_and_stats
from .grades import letter_grade


def clamp(val, lo=0, hi=100):
    """Clamp value to [lo, hi]."""
    if pd.isna(val):
        return 50.0  # default to average for missing data
    return float(max(lo, min(hi, val)))


def percentile_rank(series):
    """Compute percentile rank (0-100) for each value in a series."""
    return series.rank(pct=True, na_option="keep") * 100


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
def load_batter_data(engine):
    """Load all data needed for batter ratings."""
    stats = pd.read_sql("SELECT * FROM batter_advanced_stats", engine)

    try:
        players = pd.read_sql(f"""
            SELECT player_id, age, position, prone_overall,
                   personality_work_ethic, personality_intelligence, personality_leader,
                   personality_greed, personality_loyalty, personality_adaptability
            FROM players
            WHERE player_id IN (SELECT player_id FROM batter_advanced_stats)
        """, engine)
    except Exception:
        players = pd.read_sql(f"""
            SELECT player_id, age, position, prone_overall,
                   personality_work_ethic, personality_intelligence, personality_leader,
                   personality_greed, personality_loyalty
            FROM players
            WHERE player_id IN (SELECT player_id FROM batter_advanced_stats)
        """, engine)
        players["personality_adaptability"] = pd.NA

    value = pd.read_sql(f"""
        SELECT player_id, oa, pot, oa_rating, pot_rating
        FROM players_value
        WHERE league_id = {MLB_LEAGUE_ID}
          AND player_id IN (SELECT player_id FROM batter_advanced_stats)
    """, engine)

    batting = pd.read_sql(f"""
        SELECT player_id,
               running_ratings_speed, running_ratings_stealing,
               running_ratings_baserunning,
               batting_ratings_talent_contact AS talent_contact,
               batting_ratings_talent_power   AS talent_power,
               batting_ratings_talent_eye     AS talent_eye,
               batting_ratings_talent_gap     AS talent_gap
        FROM players_batting
        WHERE league_id = {MLB_LEAGUE_ID}
          AND player_id IN (SELECT player_id FROM batter_advanced_stats)
    """, engine)

    fielding = pd.read_sql(f"""
        SELECT player_id,
               fielding_rating_pos2, fielding_rating_pos3, fielding_rating_pos4,
               fielding_rating_pos5, fielding_rating_pos6, fielding_rating_pos7,
               fielding_rating_pos8, fielding_rating_pos9,
               fielding_ratings_infield_range, fielding_ratings_infield_arm,
               fielding_ratings_outfield_range, fielding_ratings_outfield_arm,
               fielding_ratings_catcher_ability, fielding_ratings_catcher_framing
        FROM players_fielding
        WHERE league_id = {MLB_LEAGUE_ID}
          AND player_id IN (SELECT player_id FROM batter_advanced_stats)
    """, engine)

    # Current-season fielding stats at each player's primary position
    # Aggregated (SUM) to handle mid-season team changes; split_id excluded because
    # it changed conventions across seasons (0 for recent, 1 for older).
    fielding_cur = pd.read_sql(f"""
        SELECT pcfs.player_id,
               SUM(pcfs.g)       AS fld_g,
               SUM(pcfs.tc)      AS fld_tc,
               SUM(pcfs.po)      AS fld_po,
               SUM(pcfs.a)       AS fld_a,
               SUM(pcfs.e)       AS fld_e,
               SUM(pcfs.dp)      AS fld_dp,
               SUM(pcfs.pb)      AS fld_pb,
               SUM(pcfs.sba)     AS fld_sba,
               SUM(pcfs.rto)     AS fld_rto,
               SUM(pcfs.framing) AS fld_framing,
               SUM(pcfs.arm)     AS fld_arm,
               SUM(pcfs.zr)      AS fld_zr
        FROM players_career_fielding_stats pcfs
        JOIN players p ON p.player_id = pcfs.player_id
        WHERE pcfs.league_id = {MLB_LEAGUE_ID}
          AND pcfs.level_id = {MLB_LEVEL_ID}
          AND pcfs.position = p.position
          AND pcfs.year = (
              SELECT MAX(year) FROM players_career_fielding_stats
              WHERE league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID}
          )
          AND pcfs.player_id IN (SELECT player_id FROM batter_advanced_stats)
        GROUP BY pcfs.player_id
    """, engine)

    # Career trend: current year vs previous year wRC+
    trend = pd.read_sql(f"""
        SELECT player_id, year, SUM(pa) as pa, SUM(ab) as ab, SUM(h) as h,
               SUM(d) as d, SUM(t) as t, SUM(hr) as hr, SUM(bb) as bb,
               SUM(k) as k, SUM(hp) as hp, SUM(sf) as sf, SUM(ibb) as ibb,
               SUM(war) as war
        FROM players_career_batting_stats
        WHERE league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID}
          AND split_id = {SPLIT_CAREER_OVERALL}
          AND player_id IN (SELECT player_id FROM batter_advanced_stats)
        GROUP BY player_id, year
        ORDER BY player_id, year
    """, engine)

    # Ground-truth current batting ratings from players_scouted_ratings.
    # Only available when "Additional complete scouted ratings" is enabled in OOTP export.
    try:
        scouted_bat = pd.read_sql(f"""
            SELECT player_id,
                   batting_ratings_overall_contact AS sr_contact,
                   batting_ratings_overall_power   AS sr_power,
                   batting_ratings_overall_eye     AS sr_eye,
                   batting_ratings_overall_gap     AS sr_gap
            FROM players_scouted_ratings
            WHERE scouting_team_id = 0
              AND player_id IN (SELECT player_id FROM batter_advanced_stats)
        """, engine)
    except Exception:
        scouted_bat = pd.DataFrame(
            columns=["player_id", "sr_contact", "sr_power", "sr_eye", "sr_gap"])

    return stats, players, value, batting, fielding, fielding_cur, trend, scouted_bat


def load_pitcher_data(engine):
    """Load all data needed for pitcher ratings."""
    stats = pd.read_sql("SELECT * FROM pitcher_advanced_stats", engine)

    try:
        players = pd.read_sql(f"""
            SELECT player_id, age, position, prone_overall,
                   personality_work_ethic, personality_intelligence, personality_leader,
                   personality_greed, personality_loyalty, personality_adaptability
            FROM players
            WHERE player_id IN (SELECT player_id FROM pitcher_advanced_stats)
        """, engine)
    except Exception:
        players = pd.read_sql(f"""
            SELECT player_id, age, position, prone_overall,
                   personality_work_ethic, personality_intelligence, personality_leader,
                   personality_greed, personality_loyalty
            FROM players
            WHERE player_id IN (SELECT player_id FROM pitcher_advanced_stats)
        """, engine)
        players["personality_adaptability"] = pd.NA

    value = pd.read_sql(f"""
        SELECT player_id, oa, pot, oa_rating, pot_rating
        FROM players_value
        WHERE league_id = {MLB_LEAGUE_ID}
          AND player_id IN (SELECT player_id FROM pitcher_advanced_stats)
    """, engine)

    # Career trend: current year vs previous year FIP
    trend = pd.read_sql(f"""
        SELECT player_id, year, SUM(ip) as ip, SUM(er) as er, SUM(k) as k,
               SUM(bb) as bb, SUM(hp) as hp, SUM(hra) as hra, SUM(bf) as bf,
               SUM(gb) as gb, SUM(fb) as fb, SUM(war) as war
        FROM players_career_pitching_stats
        WHERE league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID}
          AND split_id = {SPLIT_CAREER_OVERALL}
          AND player_id IN (SELECT player_id FROM pitcher_advanced_stats)
        GROUP BY player_id, year
        ORDER BY player_id, year
    """, engine)

    # Ground-truth current pitching ratings from players_scouted_ratings.
    # Only available when "Additional complete scouted ratings" is enabled in OOTP export.
    try:
        scouted_pit = pd.read_sql(f"""
            SELECT player_id,
                   pitching_ratings_overall_stuff    AS sr_stuff,
                   pitching_ratings_overall_movement AS sr_movement,
                   pitching_ratings_overall_control  AS sr_control
            FROM players_scouted_ratings
            WHERE scouting_team_id = 0
              AND player_id IN (SELECT player_id FROM pitcher_advanced_stats)
        """, engine)
    except Exception:
        scouted_pit = pd.DataFrame(
            columns=["player_id", "sr_stuff", "sr_movement", "sr_control"])

    return stats, players, value, trend, scouted_pit


# ---------------------------------------------------------------------------
# Sub-score calculations: Batters
# ---------------------------------------------------------------------------
def score_offense(row, xwoba_pctile, ootp_bat_score=None, career_pa=0, pa_threshold=None):
    """Offensive production score from wRC+ and xwOBA.

    Blends in an OOTP-based talent anchor for players with thin MLB career
    stats using a sqrt ramp: anchor=100% at 0 PA, stats=100% at 300+ PA.
    Sqrt matches how statistical confidence actually builds (consistent with
    the platoon score convention in this codebase).

    Anchor: players_scouted_ratings (scouting_team_id=0) — ground-truth current ratings.
    Only available when CUR scale is enabled in OOTP (Game Settings → Global Settings →
    Player Rating Scales). When unavailable, stats drive the score with no anchor;
    confidence in player_ratings reflects how much PA backs that score.

    Without this anchor, a player with 13 PA and an inflated wOBA would get a
    near-perfect rating_offense, corrupting the blended_woba talent anchor.
    """
    threshold = pa_threshold if pa_threshold is not None else PA_REGRESSION_THRESHOLD
    wrc = row.get("wrc_plus", WRC_UNKNOWN_DEFAULT)
    if wrc is None or pd.isna(wrc):
        wrc = WRC_UNKNOWN_DEFAULT
    if career_pa < threshold:
        pa_trust = min((career_pa / threshold) ** REGRESSION_EXPONENT, 1.0)
        wrc_cap = WRC_UNKNOWN_DEFAULT + pa_trust * WRC_CAP_HEADROOM
        wrc = min(wrc, wrc_cap)
    wrc_score = clamp((wrc - WRC_SCORE_FLOOR) * (SCORE_MAX / (ELITE_WRC - WRC_SCORE_FLOOR)))
    xwoba_score = xwoba_pctile if not pd.isna(xwoba_pctile) else PERCENTILE_AVG
    if career_pa < threshold:
        pa_trust = min((career_pa / threshold) ** REGRESSION_EXPONENT, 1.0)
        xwoba_score = xwoba_score * pa_trust + PERCENTILE_AVG * (1.0 - pa_trust)
    stats_score = wrc_score * OFFENSE_WRC_WEIGHT + xwoba_score * OFFENSE_XWOBA_WEIGHT

    if career_pa < threshold and ootp_bat_score is not None:
        pa_trust = min((career_pa / threshold) ** REGRESSION_EXPONENT, 1.0)
        return stats_score * pa_trust + ootp_bat_score * (1.0 - pa_trust)

    return stats_score


def score_contact_quality(row, pctiles, career_pa=0):
    """Contact quality score from EV/LA percentiles.

    Regresses toward 50 for thin samples — 2 balls in play can hit the 99th
    percentile for avg_ev/barrel_pct, inflating OVR just like wRC+ does.
    Uses the same sqrt ramp as score_offense (full trust at PA_REGRESSION_THRESHOLD PA).
    """
    vals = []
    for col in ["barrel_pct", "hard_hit_pct", "avg_ev", "xslg"]:
        p = pctiles.get(col)
        if p is not None and not pd.isna(p):
            vals.append(p)
    stats_score = np.mean(vals) if vals else 50.0

    if career_pa < PA_REGRESSION_THRESHOLD:
        stats_weight = min((career_pa / PA_REGRESSION_THRESHOLD) ** REGRESSION_EXPONENT, 1.0)
        return stats_score * stats_weight + 50.0 * (1.0 - stats_weight)

    return stats_score


def score_discipline(row, career_pa=0):
    """Plate discipline from K% and BB%.

    Regresses toward 50 for thin samples — K%/BB% from 4 PAs is noise.
    Uses the same sqrt ramp as score_offense (full trust at PA_REGRESSION_THRESHOLD PA).
    """
    k_pct = row.get("k_pct", 0.22) or 0.22
    bb_pct = row.get("bb_pct", 0.08) or 0.08
    k_score = clamp((0.30 - k_pct) / 0.20 * 100)
    bb_score = clamp(bb_pct / 0.15 * 100)
    stats_score = k_score * 0.5 + bb_score * 0.5

    if career_pa < PA_REGRESSION_THRESHOLD:
        stats_weight = min((career_pa / PA_REGRESSION_THRESHOLD) ** REGRESSION_EXPONENT, 1.0)
        return stats_score * stats_weight + 50.0 * (1.0 - stats_weight)

    return stats_score


def score_defense(row, fielding_row, position):
    """Defense score blending OOTP fielding rating (50%) with actual fielding stats (50%).

    Falls back to rating-only when fewer than 10 games of fielding stats are available
    (e.g. focus-modifier path, rookies, or players without current-season data).

    Position-specific stat weights (within the stats component):
      Catcher:   ZR 30% | FPct 15% | CS% 30% | Framing 25%
      2B / SS:   ZR 40% | FPct 20% | DP rate 40%
      3B / 1B:   ZR 40% | FPct 30% | DP rate 30%
      CF:        ZR 40% | FPct 10% | Arm 20% | PO/G 30%
      LF / RF:   ZR 40% | FPct 20% | Arm 40%
    """
    return defense_score_from_rating_and_stats(fielding_row, row, position)


def score_baserunning(batting_row):
    """Baserunning score from OOTP running ratings."""
    if batting_row is None:
        return 50.0
    vals = []
    for col in ["running_ratings_speed", "running_ratings_stealing",
                "running_ratings_baserunning"]:
        v = batting_row.get(col)
        if pd.notna(v) and v > 0:
            vals.append(clamp((v - OOTP_RATING_SCALE_MIN) / SCALE_RANGE * 100))
    return np.mean(vals) if vals else 50.0


# ---------------------------------------------------------------------------
# Sub-score calculations: Pitchers
# ---------------------------------------------------------------------------
def score_run_prevention(row):
    """Run prevention from FIP, xFIP, ERA."""
    fip = row.get("fip", 4.0)
    xfip = row.get("xfip", 4.0)
    era = row.get("era", 4.0)
    fip_s = clamp((6.0 - (fip or 4.0)) / 4.0 * 100)
    xfip_s = clamp((6.0 - (xfip or 4.0)) / 4.0 * 100)
    era_s = clamp((6.0 - (era or 4.0)) / 4.0 * 100)
    return fip_s * 0.50 + xfip_s * 0.25 + era_s * 0.25


def score_dominance(row):
    """Dominance from K-BB%."""
    kbb = row.get("k_bb_pct", 0.14) or 0.14
    return clamp(kbb / 0.30 * 100)


def score_contact_suppression(pctiles):
    """Contact suppression from inverse percentiles (lower = better for pitcher)."""
    vals = []
    for col in ["barrel_pct_against", "hard_hit_pct_against", "avg_ev_against"]:
        p = pctiles.get(col)
        if p is not None and not pd.isna(p):
            vals.append(100 - p)  # invert: low barrel% = high score
    return np.mean(vals) if vals else 50.0


def score_command(row):
    """Command from BB% and WHIP."""
    bb_pct = row.get("bb_pct", 0.08) or 0.08
    whip = row.get("whip", 1.30) or 1.30
    bb_s = clamp((0.15 - bb_pct) / 0.12 * 100)
    whip_s = clamp((2.0 - whip) / 1.2 * 100)
    return bb_s * 0.6 + whip_s * 0.4


def score_role_value(row):
    """Role value based on IP volume."""
    ip = row.get("ip", 0) or 0
    gs = row.get("gs", 0) or 0
    g = row.get("g", 0) or 0
    if gs >= STARTER_MIN_GS:  # starter
        return clamp(ip / STARTER_IP_TARGET * 100)
    else:  # reliever
        return clamp(g / RELIEVER_G_TARGET * 100)


# ---------------------------------------------------------------------------
# Shared sub-scores
# ---------------------------------------------------------------------------
def compute_ceiling_score(value_row):
    """Raw ceiling score (0–100) based on OA/POT gap, independent of age.

    Exposed separately so callers can store rating_ceiling without re-computing.
    gap * 5 maps the 20-point max gap on OOTP's scale to a 0-100 score.
    """
    oa = value_row.get("oa", 50) if value_row is not None else 50
    pot = value_row.get("pot", 50) if value_row is not None else 50
    if pd.isna(oa):
        oa = 50
    if pd.isna(pot):
        pot = 50
    return clamp((pot - oa) * 5)


def score_development_traits(player_row):
    """0–100 blend of work ethic, intelligence, adaptability.

    Stored as rating_development for display; also drives the multiplier inside
    score_potential(). OOTP traits are on a 0–200 scale → halved then clamped.
    """
    we = player_row.get("personality_work_ethic", 100)
    iq = player_row.get("personality_intelligence", 100)
    ad = player_row.get("personality_adaptability", 100)
    if pd.isna(we) or we is None:
        we = 100
    if pd.isna(iq) or iq is None:
        iq = 100
    if pd.isna(ad) or ad is None:
        ad = 100
    t_we = clamp(float(we) / 2)
    t_iq = clamp(float(iq) / 2)
    t_ad = clamp(float(ad) / 2)
    return (
        t_we * DEVELOPMENT_TRAIT_WEIGHT_WORK_ETHIC
        + t_iq * DEVELOPMENT_TRAIT_WEIGHT_INTELLIGENCE
        + t_ad * DEVELOPMENT_TRAIT_WEIGHT_ADAPTABILITY
    )


def score_potential(value_row, age, player_row, _current_metric=None, _prev_metric=None):
    """Trade upside: OA/POT ceiling × development realization × age runway.

    Realization maps trait score to [DEVELOPMENT_REALIZATION_MULT_MIN, MAX] so
    elite traits can sit above the naive ceiling gap and poor traits below it.
    Age credit (growth runway) uses DEVELOPMENT_MIN_AGE / DEVELOPMENT_MAX_AGE /
    DEVELOPMENT_EXPONENT — same curve as before, applied after ceiling×traits.
    """
    ceiling = compute_ceiling_score(value_row)
    d_traits = score_development_traits(player_row)
    mult = (
        DEVELOPMENT_REALIZATION_MULT_MIN
        + (d_traits / 100.0)
        * (DEVELOPMENT_REALIZATION_MULT_MAX - DEVELOPMENT_REALIZATION_MULT_MIN)
    )

    if pd.isna(age):
        age = DEVELOPMENT_MAX_AGE
    age = float(age)

    age_clamped = max(DEVELOPMENT_MIN_AGE, min(DEVELOPMENT_MAX_AGE, age))
    years_remaining = DEVELOPMENT_MAX_AGE - age_clamped
    years_total = DEVELOPMENT_MAX_AGE - DEVELOPMENT_MIN_AGE

    if years_total <= 0 or years_remaining <= 0:
        growth_credit = 0.0
    else:
        growth_credit = (years_remaining / years_total) ** DEVELOPMENT_EXPONENT

    return clamp(ceiling * mult * growth_credit)


def score_durability(player_row):
    """Injury risk score (proneness only). Iron Man (0) → 100, Wrecked (200) → 0."""
    prone = player_row.get("prone_overall", 100)
    if pd.isna(prone):
        prone = 100
    return clamp(100 - prone / 2)


def score_clubhouse(player_row):
    """Clubhouse impact: Leadership (50%) + Greed inverted (25%) + Loyalty (25%).
    High greed penalizes the score. play_for_winner is display-only.
    """
    leader = player_row.get("personality_leader", 100)
    greed = player_row.get("personality_greed", 100)
    loyalty = player_row.get("personality_loyalty", 100)
    if pd.isna(leader):
        leader = 100
    if pd.isna(greed):
        greed = 100
    if pd.isna(loyalty):
        loyalty = 100
    return (clamp(leader / 2) * 0.50 +
            clamp((200 - greed) / 2) * 0.25 +
            clamp(loyalty / 2) * 0.25)


# ---------------------------------------------------------------------------
# Compute career trend metrics
# ---------------------------------------------------------------------------
def get_trend_metrics_batting(trend_df):
    """Get current and previous year wRC+ for each player."""
    if trend_df.empty:
        return {}

    # Compute wOBA per player-year (simplified)
    WOBA_BB, WOBA_HBP = 0.69, 0.72
    WOBA_1B, WOBA_2B, WOBA_3B, WOBA_HR = 0.87, 1.27, 1.62, 2.10

    results = {}
    for pid, grp in trend_df.groupby("player_id"):
        grp = grp.sort_values("year")
        if len(grp) < 1:
            continue
        years_data = []
        for _, row in grp.iterrows():
            ab, h, d, t, hr = int(row.ab), int(row.h), int(row.d), int(row.t), int(row.hr)
            bb, hp, sf, ibb, pa = int(row.bb), int(row.hp), int(row.sf), int(row.ibb), int(row.pa)
            if pa < 50:
                continue
            s = h - d - t - hr
            denom = ab + bb - ibb + sf + hp
            if denom > 0:
                woba = (WOBA_BB * (bb - ibb) + WOBA_HBP * hp + WOBA_1B * s +
                        WOBA_2B * d + WOBA_3B * t + WOBA_HR * hr) / denom
                # Approximate wRC+ (using ~0.315 as lgwOBA, ~0.045 as lgR/PA)
                wrc = ((woba - 0.315) / 1.15 + 0.045) / 0.045 * 100
                years_data.append((int(row.year), wrc))

        if len(years_data) >= 2:
            results[pid] = (years_data[-1][1], years_data[-2][1])  # current, prev
        elif len(years_data) == 1:
            results[pid] = (years_data[-1][1], None)

    return results


def get_trend_metrics_pitching(trend_df, cfip):
    """Get current and previous year FIP for each player."""
    if trend_df.empty:
        return {}

    results = {}
    for pid, grp in trend_df.groupby("player_id"):
        grp = grp.sort_values("year")
        years_data = []
        for _, row in grp.iterrows():
            ip = float(row.ip)
            if ip < 20:
                continue
            hra, bb, hp, k = float(row.hra), float(row.bb), float(row.hp), float(row.k)
            fip = (13 * hra + 3 * (bb + hp) - 2 * k) / ip + cfip
            years_data.append((int(row.year), fip))

        if len(years_data) >= 2:
            # For FIP, lower is better, so invert for trend
            # current_fip, prev_fip — improvement = prev > current
            results[pid] = (years_data[-1][1], years_data[-2][1])
        elif len(years_data) == 1:
            results[pid] = (years_data[-1][1], None)

    return results


# ---------------------------------------------------------------------------
# Main rating computation
# ---------------------------------------------------------------------------
def compute_batter_ratings(engine):
    """Compute ratings for all position players."""
    stats, players, value, batting, fielding, fielding_cur, trend, scouted_bat = load_batter_data(engine)

    # Merge all data
    df = stats.merge(players, on="player_id", how="left", suffixes=("", "_p"))
    df = df.merge(value, on="player_id", how="left")
    df = df.merge(batting, on="player_id", how="left")
    df = df.merge(fielding, on="player_id", how="left")
    df = df.merge(fielding_cur, on="player_id", how="left")
    df = df.merge(scouted_bat, on="player_id", how="left")

    # Compute percentile ranks for contact stats
    contact_pctile_cols = ["barrel_pct", "hard_hit_pct", "avg_ev", "xslg", "xwoba"]
    pctiles = {}
    for col in contact_pctile_cols:
        if col in df.columns:
            pctiles[col] = percentile_rank(df[col])

    # Split xwOBA percentiles for LHP/RHP offense scores
    for col in ("xwoba_vs_lhp", "xwoba_vs_rhp"):
        if col in df.columns:
            pctiles[col] = percentile_rank(df[col])

    # Career trends
    trend_data = get_trend_metrics_batting(trend)

    # Career PA totals (all MLB years) — used for OOTP rating blend threshold
    career_pa_totals = trend.groupby("player_id")["pa"].sum().to_dict()

    results = []
    for idx, row in df.iterrows():
        pid = row["player_id"]
        pos = row.get("position", 0)
        if pd.isna(pos):
            pos = 0
        pos = int(pos)
        age = row.get("age", 27)

        # Get per-player percentiles
        player_pctiles = {}
        for col in contact_pctile_cols + ["xwoba_vs_lhp", "xwoba_vs_rhp"]:
            if col in pctiles:
                player_pctiles[col] = pctiles[col].iloc[idx]

        # Trend
        trend_current, trend_prev = trend_data.get(pid, (None, None))

        # OOTP batting anchor for thin-stat blend (scale → 0-100).
        # Only uses CUR scouted ratings — talent/POT is the ceiling, not current ability,
        # and oa blends pitching skill for two-way players. If CUR is unavailable (setting
        # off or < 500 career PA), confidence < 1.0 and the score is stats-only.
        sr_vals = [row.get(c) for c in ("sr_contact", "sr_power", "sr_eye", "sr_gap")]
        sr_vals = [v for v in sr_vals if v is not None and not pd.isna(v) and v > 0]
        if sr_vals:
            ootp_bat_score = clamp((sum(sr_vals) / len(sr_vals) - OOTP_RATING_SCALE_MIN) / SCALE_RANGE * 100)
            cur_available = True
        else:
            ootp_bat_score = None
            cur_available = False
        career_pa = int(career_pa_totals.get(pid, 0))

        # Confidence: 1.0 when CUR ratings available; PA-based ramp otherwise.
        if cur_available:
            confidence = 1.0
        else:
            confidence = round(min((career_pa / PA_REGRESSION_THRESHOLD) ** REGRESSION_EXPONENT, 1.0), 3)

        # Sub-scores
        s_offense = score_offense(row, player_pctiles.get("xwoba", 50), ootp_bat_score, career_pa)
        s_contact = score_contact_quality(row, player_pctiles, career_pa)
        s_discipline = score_discipline(row, career_pa)
        s_defense = score_defense(row, row, pos)
        s_baserunning = score_baserunning(row)
        s_development = score_development_traits(row)
        s_potential = score_potential(row, age, row, trend_current, trend_prev)
        s_durability = score_durability(row)
        s_clubhouse = score_clubhouse(row)

        # Split offense scores (vs LHP / vs RHP)
        # Use a split-specific wRC+ row and split xwOBA percentile with narrower PA thresholds.
        pa_vs_lhp = int(row.get("pa_vs_lhp") or 0) if not pd.isna(row.get("pa_vs_lhp") or 0) else 0
        pa_vs_rhp = int(row.get("pa_vs_rhp") or 0) if not pd.isna(row.get("pa_vs_rhp") or 0) else 0
        lhp_row = dict(row)
        lhp_row["wrc_plus"] = row.get("wrc_plus_vs_lhp") or WRC_UNKNOWN_DEFAULT
        rhp_row = dict(row)
        rhp_row["wrc_plus"] = row.get("wrc_plus_vs_rhp") or WRC_UNKNOWN_DEFAULT
        s_offense_lhp = score_offense(
            lhp_row,
            player_pctiles.get("xwoba_vs_lhp", PERCENTILE_AVG),
            ootp_bat_score,
            pa_vs_lhp,
            pa_threshold=PLATOON_LHP_PA_THRESHOLD,
        )
        s_offense_rhp = score_offense(
            rhp_row,
            player_pctiles.get("xwoba_vs_rhp", PERCENTILE_AVG),
            ootp_bat_score,
            pa_vs_rhp,
            pa_threshold=PLATOON_RHP_PA_THRESHOLD,
        )

        # confidence_lhp / confidence_rhp: split-specific PA ramp
        confidence_lhp = round(min((pa_vs_lhp / PLATOON_LHP_PA_THRESHOLD) ** REGRESSION_EXPONENT, 1.0), 3)
        confidence_rhp = round(min((pa_vs_rhp / PLATOON_RHP_PA_THRESHOLD) ** REGRESSION_EXPONENT, 1.0), 3)

        # Ceiling score (raw, age-independent) stored as rating_ceiling
        ceiling_score = compute_ceiling_score(row)

        # rating_now: production dimensions only, potential excluded.
        # Weights are renormalized so they still sum to 1.0.
        now_total_weight = (
            BATTER_WEIGHT_OFFENSE + BATTER_WEIGHT_CONTACT + BATTER_WEIGHT_DISCIPLINE +
            BATTER_WEIGHT_DEFENSE + BATTER_WEIGHT_DURABILITY + BATTER_WEIGHT_BASERUNNING
        )
        rating_now = clamp((
            s_offense    * BATTER_WEIGHT_OFFENSE     +
            s_contact    * BATTER_WEIGHT_CONTACT      +
            s_discipline * BATTER_WEIGHT_DISCIPLINE   +
            s_defense    * BATTER_WEIGHT_DEFENSE      +
            s_durability * BATTER_WEIGHT_DURABILITY   +
            s_baserunning * BATTER_WEIGHT_BASERUNNING
        ) / now_total_weight)

        # rating_now_lhp / rating_now_rhp: same as rating_now but with split offense score.
        rating_now_lhp = clamp((
            s_offense_lhp * BATTER_WEIGHT_OFFENSE     +
            s_contact     * BATTER_WEIGHT_CONTACT      +
            s_discipline  * BATTER_WEIGHT_DISCIPLINE   +
            s_defense     * BATTER_WEIGHT_DEFENSE      +
            s_durability  * BATTER_WEIGHT_DURABILITY   +
            s_baserunning * BATTER_WEIGHT_BASERUNNING
        ) / now_total_weight)
        rating_now_rhp = clamp((
            s_offense_rhp * BATTER_WEIGHT_OFFENSE     +
            s_contact     * BATTER_WEIGHT_CONTACT      +
            s_discipline  * BATTER_WEIGHT_DISCIPLINE   +
            s_defense     * BATTER_WEIGHT_DEFENSE      +
            s_durability  * BATTER_WEIGHT_DURABILITY   +
            s_baserunning * BATTER_WEIGHT_BASERUNNING
        ) / now_total_weight)

        # Weighted composite
        overall = (
            s_offense * BATTER_WEIGHTS["offense"] +
            s_contact * BATTER_WEIGHTS["contact_quality"] +
            s_discipline * BATTER_WEIGHTS["discipline"] +
            s_defense * BATTER_WEIGHTS["defense"] +
            s_potential * BATTER_WEIGHTS["potential"] +
            s_durability * BATTER_WEIGHTS["durability"] +
            s_clubhouse * BATTER_WEIGHTS["clubhouse"] +
            s_baserunning * BATTER_WEIGHTS["baserunning"]
        )

        # Flags and adjustments
        prone = row.get("prone_overall", 100)
        leader = row.get("personality_leader", 0)
        if pd.isna(prone):
            prone = 100
        if pd.isna(leader):
            leader = 0

        flag_injury = bool(prone >= INJURY_PRONE_THRESHOLD)
        flag_leader = bool(leader >= LEADER_THRESHOLD)
        flag_ceiling = bool((row.get("pot", 0) or 0) - (row.get("oa", 0) or 0) >= CEILING_GAP_THRESHOLD)

        if flag_injury:
            overall -= INJURY_OVERALL_DEDUCTION
        if flag_leader:
            overall += LEADER_OVERALL_BONUS

        overall = clamp(overall)

        # PA-based regression on the overall: applied after flag adjustments so
        # that leader/injury bonuses don't carry unproven bats for free.
        # Pulls toward s_offense (itself already regressed toward 50 for low PA),
        # ensuring personality/durability traits don't inflate players with no
        # batting history. Same sqrt ramp as sub-scores: full trust at 500+ PA.
        if career_pa < PA_REGRESSION_THRESHOLD:
            pa_weight = min((career_pa / PA_REGRESSION_THRESHOLD) ** REGRESSION_EXPONENT, 1.0)
            overall = clamp(overall * pa_weight + s_offense * (1.0 - pa_weight))

        results.append(dict(
            player_id=pid,
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            team_abbr=row.get("team_abbr"),
            position=pos,
            age=age,
            player_type="batter",
            oa=row.get("oa"),
            pot=row.get("pot"),
            rating_overall=round(overall, 1),
            rating_now=round(rating_now, 1),
            rating_ceiling=round(ceiling_score, 1),
            rating_offense=round(s_offense, 1),
            rating_contact_quality=round(s_contact, 1),
            rating_discipline=round(s_discipline, 1),
            rating_defense=round(s_defense, 1),
            rating_potential=round(s_potential, 1),
            rating_durability=round(s_durability, 1),
            rating_development=round(s_development, 1),
            rating_clubhouse=round(s_clubhouse, 1),
            rating_baserunning=round(s_baserunning, 1),
            confidence=confidence,
            rating_now_lhp=round(rating_now_lhp, 1),
            rating_now_rhp=round(rating_now_rhp, 1),
            confidence_lhp=confidence_lhp,
            confidence_rhp=confidence_rhp,
            flag_injury_risk=flag_injury,
            flag_leader=flag_leader,
            flag_high_ceiling=flag_ceiling,
            wrc_plus=row.get("wrc_plus"),
            war=row.get("war"),
            prone_overall=prone,
            work_ethic=row.get("personality_work_ethic"),
            intelligence=row.get("personality_intelligence"),
            greed=row.get("personality_greed"),
            loyalty=row.get("personality_loyalty"),
        ))

    return pd.DataFrame(results)


def compute_pitcher_ratings(engine):
    """Compute ratings for all pitchers."""
    stats, players, value, trend, scouted_pit = load_pitcher_data(engine)

    df = stats.merge(players, on="player_id", how="left", suffixes=("", "_p"))
    df = df.merge(value, on="player_id", how="left")
    df = df.merge(scouted_pit, on="player_id", how="left")

    # Percentile ranks for contact suppression (inverse)
    suppress_cols = ["barrel_pct_against", "hard_hit_pct_against", "avg_ev_against"]
    pctiles = {}
    for col in suppress_cols:
        if col in df.columns:
            pctiles[col] = percentile_rank(df[col])

    # Get league FIP constant (NULL when no rows match export league/level keys or IP=0)
    with engine.connect() as conn:
        r = conn.execute(
            text("""
            SELECT sum_er * 9.0 / NULLIF(ip_sum, 0) AS era,
                   (sum_er * 9.0 / NULLIF(ip_sum, 0)) -
                   ((13.0 * sum_hra + 3.0 * (sum_bb + sum_hp) - 2.0 * sum_k) / NULLIF(ip_sum, 0)) AS cfip
            FROM (
                SELECT SUM(er) AS sum_er,
                       SUM(ip) AS ip_sum,
                       SUM(hra) AS sum_hra,
                       SUM(bb) AS sum_bb,
                       SUM(hp) AS sum_hp,
                       SUM(k) AS sum_k
                FROM team_pitching_stats
                WHERE league_id = :league_id AND level_id = :level_id AND split_id = :split_id
            ) t
            """),
            dict(
                league_id=MLB_LEAGUE_ID,
                level_id=MLB_LEVEL_ID,
                split_id=SPLIT_TEAM_PITCHING_OVERALL,
            ),
        ).fetchone()
        cfip_raw = r[1] if r else None
        cfip = (
            float(cfip_raw)
            if cfip_raw is not None and not (isinstance(cfip_raw, float) and pd.isna(cfip_raw))
            else 4.0
        )

    trend_data = get_trend_metrics_pitching(trend, cfip)

    # Career IP totals (all MLB years) — used for OOTP rating blend threshold
    career_ip_totals = trend.groupby("player_id")["ip"].sum().to_dict()

    results = []
    for idx, row in df.iterrows():
        pid = row["player_id"]
        age = row.get("age", 27)

        player_pctiles = {}
        for col in suppress_cols:
            if col in pctiles:
                player_pctiles[col] = pctiles[col].iloc[idx]

        trend_current, trend_prev = trend_data.get(pid, (None, None))
        # For pitchers, improving FIP means lower number, so invert for trend score
        if trend_current is not None and trend_prev is not None:
            # Convert FIP trend to "improvement" score (lower FIP = better)
            fip_improvement = trend_prev - trend_current  # positive = got better
            trend_score_current = 50 + fip_improvement * 10  # scale FIP change
            trend_score_prev = 50
            pot_current = trend_score_current
            pot_prev = trend_score_prev
        else:
            pot_current = None
            pot_prev = None

        s_run_prev = score_run_prevention(row)

        # Blend OOTP current pitching rating into run prevention for thin-IP pitchers.
        # Stuff/movement/control are averaged (20-80 → 0-100) and mixed in up to
        # OOTP_MAX_BLEND_WEIGHT at 0 IP, tapering to 0 at IP_REGRESSION_THRESHOLD.
        # Uses the same REGRESSION_EXPONENT curve as the batter PA ramp.
        sr_pit_vals = [row.get(c) for c in ("sr_stuff", "sr_movement", "sr_control")]
        sr_pit_vals = [v for v in sr_pit_vals if v is not None and not pd.isna(v) and v > 0]
        career_ip = float(career_ip_totals.get(pid, 0))
        if sr_pit_vals:
            ootp_pit_score = clamp((sum(sr_pit_vals) / len(sr_pit_vals) - OOTP_RATING_SCALE_MIN) / SCALE_RANGE * 100)
            pit_cur_available = True
            if career_ip < IP_REGRESSION_THRESHOLD:
                ip_trust = min(career_ip / IP_REGRESSION_THRESHOLD, 1.0) ** REGRESSION_EXPONENT
                ootp_weight = (1.0 - ip_trust) * OOTP_MAX_BLEND_WEIGHT
                s_run_prev = s_run_prev * (1 - ootp_weight) + ootp_pit_score * ootp_weight
        else:
            pit_cur_available = False

        # Confidence: 1.0 when CUR ratings available; IP-based ramp otherwise.
        if pit_cur_available:
            pit_confidence = 1.0
        else:
            pit_confidence = round(min((career_ip / IP_REGRESSION_THRESHOLD) ** REGRESSION_EXPONENT, 1.0), 3)

        s_dominance = score_dominance(row)
        s_suppress = score_contact_suppression(player_pctiles)
        s_command = score_command(row)
        s_development = score_development_traits(row)
        s_potential = score_potential(row, age, row, pot_current, pot_prev)
        s_durability = score_durability(row)
        s_clubhouse = score_clubhouse(row)
        s_role = score_role_value(row)

        # Ceiling score (raw, age-independent) stored as rating_ceiling
        ceiling_score = compute_ceiling_score(row)

        # rating_now: production dimensions only, potential excluded.
        # Weights are renormalized so they still sum to 1.0.
        now_total_weight = (
            PITCHER_WEIGHT_RUN_PREVENTION + PITCHER_WEIGHT_DOMINANCE +
            PITCHER_WEIGHT_CONTACT_SUPPRESSION + PITCHER_WEIGHT_COMMAND +
            PITCHER_WEIGHT_DURABILITY + PITCHER_WEIGHT_ROLE_VALUE
        )
        rating_now = clamp((
            s_run_prev   * PITCHER_WEIGHT_RUN_PREVENTION      +
            s_dominance  * PITCHER_WEIGHT_DOMINANCE           +
            s_suppress   * PITCHER_WEIGHT_CONTACT_SUPPRESSION +
            s_command    * PITCHER_WEIGHT_COMMAND             +
            s_durability * PITCHER_WEIGHT_DURABILITY          +
            s_role       * PITCHER_WEIGHT_ROLE_VALUE
        ) / now_total_weight)

        overall = (
            s_run_prev * PITCHER_WEIGHTS["run_prevention"] +
            s_dominance * PITCHER_WEIGHTS["dominance"] +
            s_suppress * PITCHER_WEIGHTS["contact_suppression"] +
            s_command * PITCHER_WEIGHTS["command"] +
            s_potential * PITCHER_WEIGHTS["potential"] +
            s_durability * PITCHER_WEIGHTS["durability"] +
            s_clubhouse * PITCHER_WEIGHTS["clubhouse"] +
            s_role * PITCHER_WEIGHTS["role_value"]
        )

        prone = row.get("prone_overall", 100)
        leader = row.get("personality_leader", 0)
        if pd.isna(prone):
            prone = 100
        if pd.isna(leader):
            leader = 0

        flag_injury = bool(prone >= INJURY_PRONE_THRESHOLD)
        flag_leader = bool(leader >= LEADER_THRESHOLD)
        flag_ceiling = bool((row.get("pot", 0) or 0) - (row.get("oa", 0) or 0) >= CEILING_GAP_THRESHOLD)

        if flag_injury:
            overall -= INJURY_OVERALL_DEDUCTION
        if flag_leader:
            overall += LEADER_OVERALL_BONUS

        overall = clamp(overall)

        results.append(dict(
            player_id=pid,
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            team_abbr=row.get("team_abbr"),
            position=POS_PITCHER,
            age=age,
            player_type="pitcher",
            oa=row.get("oa"),
            pot=row.get("pot"),
            rating_overall=round(overall, 1),
            rating_now=round(rating_now, 1),
            rating_ceiling=round(ceiling_score, 1),
            rating_offense=round(s_run_prev, 1),  # reuse column, means "run prevention"
            rating_contact_quality=round(s_suppress, 1),  # means "contact suppression"
            rating_discipline=round(s_dominance, 1),  # means "dominance"
            rating_defense=round(s_command, 1),  # means "command"
            rating_potential=round(s_potential, 1),
            rating_durability=round(s_durability, 1),
            rating_development=round(s_development, 1),
            rating_clubhouse=round(s_clubhouse, 1),
            rating_baserunning=round(s_role, 1),  # means "role value"
            confidence=pit_confidence,
            flag_injury_risk=flag_injury,
            flag_leader=flag_leader,
            flag_high_ceiling=flag_ceiling,
            wrc_plus=row.get("fip"),  # store FIP in this column for pitchers
            war=row.get("war"),
            prone_overall=prone,
            work_ethic=row.get("personality_work_ethic"),
            intelligence=row.get("personality_intelligence"),
            greed=row.get("personality_greed"),
            loyalty=row.get("personality_loyalty"),
        ))

    return pd.DataFrame(results)


def main():
    if len(sys.argv) != 2:
        print("Usage: python -m ratings <save_name>")
        print("Example: (cd src && python -m ratings My-Save-2026)")
        sys.exit(1)

    save_name = sys.argv[1]
    engine = get_write_engine(save_name)
    start = time.time()

    print("Computing batter ratings...")
    batter_ratings = compute_batter_ratings(engine)
    print(f"  {len(batter_ratings)} batters rated")

    print("Computing pitcher ratings...")
    pitcher_ratings = compute_pitcher_ratings(engine)
    print(f"  {len(pitcher_ratings)} pitchers rated")

    # Combine and deduplicate (two-way players: keep higher rating)
    all_ratings = pd.concat([batter_ratings, pitcher_ratings], ignore_index=True)
    all_ratings = all_ratings.sort_values("rating_overall", ascending=False)
    all_ratings = all_ratings.drop_duplicates(subset="player_id", keep="first")

    print("Writing player_ratings table...")
    all_ratings.to_sql("player_ratings", engine, if_exists="replace", index=False)
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_player_ratings_player_id ON player_ratings (player_id)"))
        else:
            conn.execute(text("ALTER TABLE player_ratings ADD PRIMARY KEY (player_id)"))
        conn.commit()

    elapsed = time.time() - start

    print(f"\n{'='*70}")
    print(f"Ratings complete in {elapsed:.1f}s — {len(all_ratings)} players rated")
    print(f"{'='*70}")

    # Top position players
    qual_bat = batter_ratings[batter_ratings["wrc_plus"].notna()].copy()
    if len(qual_bat) > 0:
        print("\nTop 15 position players:")
        top = qual_bat.nlargest(15, "rating_overall")
        for _, row in top.iterrows():
            abbr = str(row.get("team_abbr", ""))[:4] or "???"
            flags = ""
            if row["flag_injury_risk"]:
                flags += " [INJURY]"
            if row["flag_leader"]:
                flags += " [LEADER]"
            if row["flag_high_ceiling"]:
                flags += " [CEILING]"
            print(f"  {letter_grade(row['rating_overall']):>2s} {row['rating_overall']:5.1f}  "
                  f"{row['first_name']} {row['last_name']:15s} {abbr:>4s}  "
                  f"wRC+={row['wrc_plus']:5.1f}  WAR={row['war']:4.1f}  "
                  f"OA={int(row['oa']) if pd.notna(row['oa']) else 0:2d} POT={int(row['pot']) if pd.notna(row['pot']) else 0:2d}{flags}")

    # Top pitchers
    qual_pit = pitcher_ratings[pitcher_ratings["wrc_plus"].notna()].copy()  # fip stored here
    if len(qual_pit) > 0:
        print("\nTop 15 pitchers:")
        top = qual_pit.nlargest(15, "rating_overall")
        for _, row in top.iterrows():
            abbr = str(row.get("team_abbr", ""))[:4] or "???"
            flags = ""
            if row["flag_injury_risk"]:
                flags += " [INJURY]"
            if row["flag_leader"]:
                flags += " [LEADER]"
            if row["flag_high_ceiling"]:
                flags += " [CEILING]"
            print(f"  {letter_grade(row['rating_overall']):>2s} {row['rating_overall']:5.1f}  "
                  f"{row['first_name']} {row['last_name']:15s} {abbr:>4s}  "
                  f"FIP={row['wrc_plus']:5.2f}  WAR={row['war']:4.1f}  "
                  f"OA={int(row['oa']) if pd.notna(row['oa']) else 0:2d} POT={int(row['pot']) if pd.notna(row['pot']) else 0:2d}{flags}")

