#!/usr/bin/env python3
"""Post-import analytics for OOTP Baseball data.

Computes advanced batting and pitching stats from career counting stats
and at-bat level Statcast-style data (exit velocity, launch angle).

Produces two tables:
  - batter_advanced_stats: all hitters with 30+ stats, overall + L/R splits
  - pitcher_advanced_stats: all pitchers with FIP, xFIP, contact quality, etc.

Run after import.py:
    python src/analytics.py My-Save-2026
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from shared_css import db_name_from_save, get_engine
from sqlalchemy import inspect, text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MLB_LEAGUE_ID = 203
MLB_LEVEL_ID = 1

# At-bat result codes
RESULT_K = 1
RESULT_BB = 2
RESULT_GROUNDOUT = 4
RESULT_FLYOUT = 5
RESULT_SINGLE = 6
RESULT_DOUBLE = 7
RESULT_TRIPLE = 8
RESULT_HR = 9
RESULT_HBP = 10

BATTED_BALL_RESULTS = {RESULT_GROUNDOUT, RESULT_FLYOUT, RESULT_SINGLE,
                       RESULT_DOUBLE, RESULT_TRIPLE, RESULT_HR}
HIT_RESULTS = {RESULT_SINGLE, RESULT_DOUBLE, RESULT_TRIPLE, RESULT_HR}

# Total bases by result
TB_MAP = {RESULT_GROUNDOUT: 0, RESULT_FLYOUT: 0,
          RESULT_SINGLE: 1, RESULT_DOUBLE: 2, RESULT_TRIPLE: 3, RESULT_HR: 4}

# Standard FanGraphs wOBA linear weights (2010-era, widely used baseline)
WOBA_BB = 0.69
WOBA_HBP = 0.72
WOBA_1B = 0.87
WOBA_2B = 1.27
WOBA_3B = 1.62
WOBA_HR = 2.10

# wOBA weights for batted ball results (used in xwOBA bin lookups)
WOBA_RESULT_MAP = {RESULT_GROUNDOUT: 0.0, RESULT_FLYOUT: 0.0,
                   RESULT_SINGLE: WOBA_1B, RESULT_DOUBLE: WOBA_2B,
                   RESULT_TRIPLE: WOBA_3B, RESULT_HR: WOBA_HR}

# Bin sizes for EV/LA lookup tables
EV_BIN_SIZE = 2   # mph
LA_BIN_SIZE = 5   # degrees
MIN_BIN_SAMPLE = 10

# Barrel definition: EV >= 100 mph, LA 8-35 degrees (matched to OOTP in-game)
BARREL_EV_MIN = 100
BARREL_LA_MIN = 8
BARREL_LA_MAX = 35

# Hard hit: EV >= 95 mph
HARD_HIT_EV = 95

# Sweet spot: LA 8-32 degrees
SWEET_SPOT_LA_MIN = 8
SWEET_SPOT_LA_MAX = 32


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
def get_current_year(engine):
    """Get the current (max) season year for MLB career stats."""
    with engine.connect() as conn:
        row = conn.execute(text(
            f"SELECT MAX(year) FROM players_career_batting_stats "
            f"WHERE league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID}"
        )).fetchone()
        return row[0]


def get_player_info(engine):
    """Load player names and team info."""
    return pd.read_sql("""
        SELECT p.player_id, p.first_name, p.last_name, p.team_id,
               p.position, t.abbr as team_abbr
        FROM players p
        LEFT JOIN teams t ON t.team_id = p.team_id
    """, engine)


# ---------------------------------------------------------------------------
# League averages
# ---------------------------------------------------------------------------
def get_league_batting_averages(engine, year):
    """Compute league-wide batting averages from team stats."""
    df = pd.read_sql(f"""
        SELECT SUM(pa) as pa, SUM(ab) as ab, SUM(h) as h, SUM(d) as d,
               SUM(t) as t, SUM(hr) as hr, SUM(bb) as bb, SUM(k) as k,
               SUM(hp) as hp, SUM(sf) as sf, SUM(sh) as sh, SUM(r) as r,
               SUM(ibb) as ibb, SUM(tb) as tb
        FROM team_batting_stats
        WHERE league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} AND split_id = 0
    """, engine)
    row = df.iloc[0]
    s = row.h - row.d - row.t - row.hr
    lg = dict(
        pa=row.pa, ab=row.ab, h=row.h, hr=row.hr, bb=row.bb, k=row.k,
        hp=row.hp, sf=row.sf, r=row.r, ibb=row.ibb,
        obp=(row.h + row.bb + row.hp) / (row.ab + row.bb + row.hp + row.sf),
        slg=row.tb / row.ab,
        woba=((WOBA_BB * (row.bb - row.ibb) + WOBA_HBP * row.hp +
               WOBA_1B * s + WOBA_2B * row.d + WOBA_3B * row.t +
               WOBA_HR * row.hr) /
              (row.ab + row.bb - row.ibb + row.sf + row.hp)),
        r_per_pa=row.r / row.pa,
    )
    lg["avg"] = row.h / row.ab
    lg["ops"] = lg["obp"] + lg["slg"]
    return lg


def get_league_pitching_averages(engine, year):
    """Compute league-wide pitching averages from team stats."""
    df = pd.read_sql(f"""
        SELECT SUM(ip) as ip, SUM(er) as er, SUM(k) as k, SUM(bb) as bb,
               SUM(hp) as hp, SUM(hra) as hra, SUM(ha) as ha, SUM(bf) as bf,
               SUM(gb) as gb, SUM(fb) as fb, SUM(ab) as ab, SUM(sf) as sf
        FROM team_pitching_stats
        WHERE league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} AND split_id IN (0, 1)
    """, engine)
    row = df.iloc[0]
    lg_era = row.er * 9 / row.ip if row.ip > 0 else 4.00
    lg_hr_per_fb = row.hra / row.fb if row.fb > 0 else 0.10
    cfip = lg_era - ((13 * row.hra + 3 * (row.bb + row.hp) - 2 * row.k) / row.ip)
    return dict(
        era=lg_era, cfip=cfip, hr_per_fb=lg_hr_per_fb,
        ip=row.ip, k=row.k, bb=row.bb, hp=row.hp, hra=row.hra,
        ha=row.ha, bf=row.bf, gb=row.gb, fb=row.fb, ab=row.ab, sf=row.sf,
    )


# ---------------------------------------------------------------------------
# Batter career stats
# ---------------------------------------------------------------------------
def compute_batter_career_stats(engine, year, lg):
    """Compute traditional + advanced batting stats from career data."""
    # SUM across teams for traded players
    df = pd.read_sql(f"""
        SELECT player_id,
               CASE WHEN split_id IN (0, 1) THEN 1 ELSE split_id END AS split_id,
               SUM(pa) as pa, SUM(ab) as ab, SUM(h) as h, SUM(d) as d,
               SUM(t) as t, SUM(hr) as hr, SUM(bb) as bb, SUM(k) as k,
               SUM(hp) as hp, SUM(sf) as sf, SUM(sh) as sh, SUM(rbi) as rbi,
               SUM(r) as r, SUM(sb) as sb, SUM(cs) as cs, SUM(ibb) as ibb,
               SUM(gdp) as gdp, SUM(g) as g,
               SUM(war) as war, SUM(wpa) as wpa
        FROM players_career_batting_stats
        WHERE league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID}
          AND split_id IN (0, 1, 2, 3)
        GROUP BY player_id,
                 CASE WHEN split_id IN (0, 1) THEN 1 ELSE split_id END
    """, engine)

    if df.empty:
        return pd.DataFrame()

    def calc_stats(g):
        ab = g["ab"]; h = g["h"]; hr = g["hr"]; bb = g["bb"]
        k = g["k"]; hp = g["hp"]; sf = g["sf"]; pa = g["pa"]
        d = g["d"]; t = g["t"]; ibb = g["ibb"]
        singles = h - d - t - hr
        tb = singles + 2 * d + 3 * t + 4 * hr

        ba = np.where(ab > 0, h / ab, np.nan)
        obp = np.where((ab + bb + hp + sf) > 0,
                       (h + bb + hp) / (ab + bb + hp + sf), np.nan)
        slg = np.where(ab > 0, tb / ab, np.nan)
        ops = obp + slg
        iso = slg - ba

        k_pct = np.where(pa > 0, k / pa, np.nan)
        bb_pct = np.where(pa > 0, bb / pa, np.nan)

        babip_denom = ab - k - hr + sf
        babip = np.where(babip_denom > 0, (h - hr) / babip_denom, np.nan)

        woba_denom = ab + bb - ibb + sf + hp
        woba = np.where(woba_denom > 0,
                        (WOBA_BB * (bb - ibb) + WOBA_HBP * hp +
                         WOBA_1B * singles + WOBA_2B * d +
                         WOBA_3B * t + WOBA_HR * hr) / woba_denom,
                        np.nan)

        # wRC+ (simplified, no park adjustment for now)
        woba_scale = 1.15  # standard scale factor
        wraa_per_pa = (woba - lg["woba"]) / woba_scale
        wrc_plus = np.where(
            pa > 0,
            ((wraa_per_pa + lg["r_per_pa"]) / lg["r_per_pa"]) * 100,
            np.nan)

        # OPS+
        ops_plus = np.where(
            (lg["obp"] > 0) & (lg["slg"] > 0),
            100 * (obp / lg["obp"] + slg / lg["slg"] - 1),
            np.nan)

        return pd.DataFrame(dict(
            player_id=g["player_id"], split_id=g["split_id"],
            g=g["g"], pa=pa, ab=ab, h=h, r=g["r"], rbi=g["rbi"],
            hr=hr, sb=g["sb"], bb=bb, k=k,
            ba=ba, obp=obp, slg=slg, ops=ops, iso=iso,
            k_pct=k_pct, bb_pct=bb_pct, babip=babip,
            woba=woba, wrc_plus=wrc_plus, ops_plus=ops_plus,
            war=g["war"], wpa=g["wpa"],
        ))

    stats = calc_stats(df)

    # Pivot splits into columns
    overall = stats[stats["split_id"] == 1].drop(columns="split_id").copy()
    vs_lhp = stats[stats["split_id"] == 2].drop(columns="split_id").copy()
    vs_rhp = stats[stats["split_id"] == 3].drop(columns="split_id").copy()

    # Rename split columns
    keep_overall = ["player_id", "g", "pa", "ab", "h", "r", "rbi", "hr", "sb",
                    "bb", "k", "ba", "obp", "slg", "ops", "iso", "k_pct",
                    "bb_pct", "babip", "woba", "wrc_plus", "ops_plus", "war", "wpa"]
    split_cols = ["player_id", "pa", "ab", "ba", "obp", "slg", "iso",
                  "k_pct", "bb_pct", "woba", "wrc_plus"]

    overall = overall[keep_overall]
    lhp = vs_lhp[[c for c in split_cols if c in vs_lhp.columns]].copy()
    rhp = vs_rhp[[c for c in split_cols if c in vs_rhp.columns]].copy()

    lhp = lhp.rename(columns={c: f"{c}_vs_lhp" for c in lhp.columns if c != "player_id"})
    rhp = rhp.rename(columns={c: f"{c}_vs_rhp" for c in rhp.columns if c != "player_id"})

    result = overall.merge(lhp, on="player_id", how="left")
    result = result.merge(rhp, on="player_id", how="left")
    return result


# ---------------------------------------------------------------------------
# Batted ball / Statcast-style stats (current season at-bat data)
# ---------------------------------------------------------------------------
def load_all_plate_appearances(engine):
    """Load all regular-season plate appearances with pitcher handedness."""
    query = """
        SELECT ab.player_id, ab.opponent_player_id,
               ab.exit_velo, ab.launch_angle, ab.sprint_speed,
               ab.result, p_opp.throws as pitcher_throws
        FROM players_at_bat_batting_stats ab
        JOIN games g ON g.game_id = ab.game_id
        JOIN players p_opp ON p_opp.player_id = ab.opponent_player_id
        WHERE g.game_type = 0
    """
    df = pd.read_sql(query, engine)

    # Derived columns for batted balls
    is_batted = df["result"].isin(BATTED_BALL_RESULTS) & (df["exit_velo"] > 0)
    df["is_batted_ball"] = is_batted.astype(int)
    df["is_hit"] = df["result"].isin(HIT_RESULTS).astype(int)
    df["tb"] = df["result"].map(TB_MAP).fillna(0).astype(int)
    df["woba_value"] = df["result"].map(WOBA_RESULT_MAP).fillna(0)
    # For non-batted-ball events, assign wOBA values
    df.loc[df["result"] == RESULT_BB, "woba_value"] = WOBA_BB
    df.loc[df["result"] == RESULT_HBP, "woba_value"] = WOBA_HBP

    df["ev_bin"] = (df["exit_velo"] // EV_BIN_SIZE) * EV_BIN_SIZE
    df["la_bin"] = (df["launch_angle"] // LA_BIN_SIZE) * LA_BIN_SIZE

    return df


def build_ev_la_lookups(df):
    """Build EV/LA lookup tables for xBA, xSLG, and xwOBA."""
    batted = df[df["is_batted_ball"] == 1].copy()

    def build_lookup(batted_df, value_col):
        bin_stats = batted_df.groupby(["ev_bin", "la_bin"])[value_col].agg(["count", "mean"])
        bin_stats.columns = ["n", "rate"]
        ev_stats = batted_df.groupby("ev_bin")[value_col].agg(["count", "mean"])
        ev_stats.columns = ["n", "rate"]
        overall_rate = batted_df[value_col].mean()

        lookup = {}
        for (ev, la), row in bin_stats.iterrows():
            if row["n"] >= MIN_BIN_SAMPLE:
                lookup[(ev, la)] = row["rate"]
            elif ev in ev_stats.index and ev_stats.loc[ev, "n"] >= MIN_BIN_SAMPLE:
                lookup[(ev, la)] = ev_stats.loc[ev, "rate"]
            else:
                lookup[(ev, la)] = overall_rate
        return lookup, overall_rate

    xba_lookup, lg_hit_rate = build_lookup(batted, "is_hit")
    xslg_lookup, _ = build_lookup(batted, "tb")
    xwoba_lookup, _ = build_lookup(batted, "woba_value")

    print(f"  League batted-ball hit rate: {lg_hit_rate:.3f}")
    print(f"  EV/LA bins: {len(xba_lookup)}")

    return xba_lookup, xslg_lookup, xwoba_lookup


def compute_contact_stats(df, xba_lookup, xslg_lookup, xwoba_lookup):
    """Compute per-batter contact quality and expected stats."""
    batted = df[df["is_batted_ball"] == 1].copy()

    # Apply lookups to each batted ball
    keys = list(zip(batted["ev_bin"], batted["la_bin"]))
    default_xba = batted["is_hit"].mean()
    default_xslg = batted["tb"].mean()
    default_xwoba = batted["woba_value"].mean()

    batted["xba_val"] = [xba_lookup.get(k, default_xba) for k in keys]
    batted["xslg_val"] = [xslg_lookup.get(k, default_xslg) for k in keys]
    batted["xwoba_bb_val"] = [xwoba_lookup.get(k, default_xwoba) for k in keys]

    # Flags
    batted["is_hard_hit"] = (batted["exit_velo"] >= HARD_HIT_EV).astype(int)
    batted["is_barrel"] = ((batted["exit_velo"] >= BARREL_EV_MIN) &
                           (batted["launch_angle"] >= BARREL_LA_MIN) &
                           (batted["launch_angle"] <= BARREL_LA_MAX)).astype(int)
    batted["is_sweet_spot"] = ((batted["launch_angle"] >= SWEET_SPOT_LA_MIN) &
                               (batted["launch_angle"] <= SWEET_SPOT_LA_MAX)).astype(int)
    batted["is_gb"] = (batted["launch_angle"] < 11).astype(int)
    batted["is_ld"] = ((batted["launch_angle"] >= 11) &
                       (batted["launch_angle"] <= 25)).astype(int)
    batted["is_fb"] = (batted["launch_angle"] > 25).astype(int)

    def agg_contact(group, suffix=""):
        n = len(group)
        if n == 0:
            return {}
        return {
            f"batted_balls{suffix}": n,
            f"avg_ev{suffix}": group["exit_velo"].mean(),
            f"max_ev{suffix}": group["exit_velo"].max(),
            f"avg_la{suffix}": group["launch_angle"].mean(),
            f"hard_hit_pct{suffix}": group["is_hard_hit"].mean(),
            f"barrel_pct{suffix}": group["is_barrel"].mean(),
            f"sweet_spot_pct{suffix}": group["is_sweet_spot"].mean(),
            f"gb_pct{suffix}": group["is_gb"].mean(),
            f"ld_pct{suffix}": group["is_ld"].mean(),
            f"fb_pct{suffix}": group["is_fb"].mean(),
            f"xbacon{suffix}": group["xba_val"].mean(),
            f"xba_contact{suffix}": group["xba_val"].sum(),  # will divide by AB later
            f"xslg_contact{suffix}": group["xslg_val"].sum(),
            f"xwoba_bb_sum{suffix}": group["xwoba_bb_val"].sum(),
        }

    # Also need K/BB/HBP counts for xwOBA (non-batted-ball events)
    def agg_pa_events(group, suffix=""):
        return {
            f"total_pa{suffix}": len(group),
            f"n_k{suffix}": (group["result"] == RESULT_K).sum(),
            f"n_bb{suffix}": (group["result"] == RESULT_BB).sum(),
            f"n_hbp{suffix}": (group["result"] == RESULT_HBP).sum(),
        }

    results = []
    for pid, grp in batted.groupby("player_id"):
        row = {"player_id": pid}
        row.update(agg_contact(grp))
        # vs LHP
        lhp = grp[grp["pitcher_throws"] == 2]
        if len(lhp) > 0:
            row.update(agg_contact(lhp, "_vs_lhp"))
        # vs RHP
        rhp = grp[grp["pitcher_throws"] == 1]
        if len(rhp) > 0:
            row.update(agg_contact(rhp, "_vs_rhp"))
        results.append(row)

    contact_df = pd.DataFrame(results)

    # Get PA-level events for xwOBA denominator
    pa_results = []
    for pid, grp in df.groupby("player_id"):
        row = {"player_id": pid}
        row.update(agg_pa_events(grp))
        lhp = grp[grp["pitcher_throws"] == 2]
        if len(lhp) > 0:
            row.update(agg_pa_events(lhp, "_vs_lhp"))
        rhp = grp[grp["pitcher_throws"] == 1]
        if len(rhp) > 0:
            row.update(agg_pa_events(rhp, "_vs_rhp"))
        pa_results.append(row)
    pa_df = pd.DataFrame(pa_results)

    contact_df = contact_df.merge(pa_df, on="player_id", how="left")

    # Compute xwOBA: (xwOBA_batted_balls_sum + BB_woba + HBP_woba) / PA
    for suffix in ["", "_vs_lhp", "_vs_rhp"]:
        bb_sum = f"xwoba_bb_sum{suffix}"
        n_bb = f"n_bb{suffix}"
        n_hbp = f"n_hbp{suffix}"
        total_pa = f"total_pa{suffix}"
        if bb_sum in contact_df.columns and total_pa in contact_df.columns:
            contact_df[f"xwoba{suffix}"] = (
                (contact_df[bb_sum] +
                 contact_df[n_bb] * WOBA_BB +
                 contact_df[n_hbp] * WOBA_HBP) /
                contact_df[total_pa]
            )

    return contact_df


def finalize_batter_stats(career_df, contact_df, player_info):
    """Merge career stats with contact stats and player info."""
    result = career_df.merge(player_info[["player_id", "first_name", "last_name",
                                          "team_abbr", "position"]],
                             on="player_id", how="left")

    if not contact_df.empty:
        # Select contact columns to merge
        contact_cols = ["player_id"]
        for suffix in ["", "_vs_lhp", "_vs_rhp"]:
            for col in ["batted_balls", "avg_ev", "max_ev", "avg_la",
                        "hard_hit_pct", "barrel_pct", "sweet_spot_pct",
                        "gb_pct", "ld_pct", "fb_pct", "xbacon", "xwoba"]:
                full = f"{col}{suffix}"
                if full in contact_df.columns:
                    contact_cols.append(full)
        result = result.merge(contact_df[contact_cols], on="player_id", how="left")

    # Compute traditional xBA and xSLG from contact data + career AB
    if "xba_contact" in contact_df.columns:
        xba_merge = contact_df[["player_id", "xba_contact", "xslg_contact"]].copy()
        for suffix in ["_vs_lhp", "_vs_rhp"]:
            for col in ["xba_contact", "xslg_contact"]:
                full = f"{col}{suffix}"
                if full in contact_df.columns:
                    xba_merge[full] = contact_df[full]
        result = result.merge(xba_merge, on="player_id", how="left")

        # xBA = expected_hits / AB
        if "ab" in result.columns and "xba_contact" in result.columns:
            result["xba"] = result["xba_contact"] / result["ab"]
            result["xslg"] = result["xslg_contact"] / result["ab"]
        for suffix in ["_vs_lhp", "_vs_rhp"]:
            ab_col = f"ab{suffix}"
            if ab_col in result.columns and f"xba_contact{suffix}" in result.columns:
                result[f"xba{suffix}"] = result[f"xba_contact{suffix}"] / result[ab_col]
                result[f"xslg{suffix}"] = result[f"xslg_contact{suffix}"] / result[ab_col]

    # Drop intermediate columns
    drop_cols = [c for c in result.columns if c.startswith("xba_contact") or
                 c.startswith("xslg_contact") or c.startswith("xwoba_bb") or
                 c.startswith("n_k") or c.startswith("n_bb") or c.startswith("n_hbp") or
                 c.startswith("total_pa")]
    result = result.drop(columns=[c for c in drop_cols if c in result.columns], errors="ignore")

    # Reorder: identity first, then overall career, then contact, then splits
    id_cols = ["player_id", "first_name", "last_name", "team_abbr", "position"]
    career_cols = ["g", "pa", "ab", "h", "r", "rbi", "hr", "sb", "bb", "k",
                   "ba", "obp", "slg", "ops", "iso", "k_pct", "bb_pct",
                   "babip", "woba", "wrc_plus", "ops_plus", "war", "wpa"]
    contact_overall = ["batted_balls", "avg_ev", "max_ev", "avg_la",
                       "hard_hit_pct", "barrel_pct", "sweet_spot_pct",
                       "gb_pct", "ld_pct", "fb_pct",
                       "xba", "xslg", "xwoba", "xbacon"]

    ordered = id_cols + career_cols + contact_overall
    # Add all remaining columns (splits)
    remaining = [c for c in result.columns if c not in ordered]
    ordered = [c for c in ordered if c in result.columns] + remaining

    return result[ordered]


# ---------------------------------------------------------------------------
# Pitcher career stats
# ---------------------------------------------------------------------------
def compute_pitcher_career_stats(engine, year, lg_pitch):
    """Compute advanced pitching stats from career data."""
    df = pd.read_sql(f"""
        SELECT player_id, split_id,
               SUM(ip) as ip, SUM(er) as er, SUM(k) as k, SUM(bb) as bb,
               SUM(hp) as hp, SUM(hra) as hra, SUM(ha) as ha, SUM(bf) as bf,
               SUM(gb) as gb, SUM(fb) as fb, SUM(ab) as ab, SUM(sf) as sf,
               SUM(g) as g, SUM(gs) as gs, SUM(w) as w, SUM(l) as l,
               SUM(s) as s, SUM(hld) as hld, SUM(qs) as qs,
               SUM(war) as war, SUM(wpa) as wpa, SUM(outs) as outs
        FROM players_career_pitching_stats
        WHERE league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} AND year = {year}
          AND split_id IN (1, 2, 3)
        GROUP BY player_id, split_id
    """, engine)

    if df.empty:
        return pd.DataFrame()

    cfip = lg_pitch["cfip"]
    lg_hr_per_fb = lg_pitch["hr_per_fb"]

    ip = df["ip"]; er = df["er"]; k = df["k"]; bb = df["bb"]
    hp = df["hp"]; hra = df["hra"]; ha = df["ha"]; bf = df["bf"]
    gb = df["gb"]; fb = df["fb"]; ab = df["ab"]; sf = df["sf"]

    era = np.where(ip > 0, er * 9 / ip, np.nan)
    fip = np.where(ip > 0, (13 * hra + 3 * (bb + hp) - 2 * k) / ip + cfip, np.nan)
    xfip_hr = np.where(fb > 0, fb * lg_hr_per_fb, hra)
    xfip = np.where(ip > 0, (13 * xfip_hr + 3 * (bb + hp) - 2 * k) / ip + cfip, np.nan)

    k_pct = np.where(bf > 0, k / bf, np.nan)
    bb_pct = np.where(bf > 0, bb / bf, np.nan)
    k_bb_pct = k_pct - bb_pct

    whip = np.where(ip > 0, (ha + bb) / ip, np.nan)
    k_9 = np.where(ip > 0, k * 9 / ip, np.nan)
    bb_9 = np.where(ip > 0, bb * 9 / ip, np.nan)
    hr_9 = np.where(ip > 0, hra * 9 / ip, np.nan)

    babip_denom = ab - k - hra + sf
    babip = np.where(babip_denom > 0, (ha - hra) / babip_denom, np.nan)
    gb_pct = np.where((gb + fb) > 0, gb / (gb + fb), np.nan)

    stats = pd.DataFrame(dict(
        player_id=df["player_id"], split_id=df["split_id"],
        g=df["g"], gs=df["gs"], w=df["w"], l=df["l"], s=df["s"],
        hld=df["hld"], ip=ip, bf=bf,
        era=era, fip=fip, xfip=xfip,
        k_pct=k_pct, bb_pct=bb_pct, k_bb_pct=k_bb_pct,
        whip=whip, k_9=k_9, bb_9=bb_9, hr_9=hr_9,
        babip=babip, gb_pct=gb_pct, war=df["war"], wpa=df["wpa"],
    ))

    # Pivot splits
    overall = stats[stats["split_id"] == 1].drop(columns="split_id").copy()
    vs_lhb = stats[stats["split_id"] == 2].drop(columns="split_id").copy()
    vs_rhb = stats[stats["split_id"] == 3].drop(columns="split_id").copy()

    split_cols = ["player_id", "bf", "era", "fip", "k_pct", "bb_pct",
                  "k_bb_pct", "whip", "babip"]
    lhb = vs_lhb[[c for c in split_cols if c in vs_lhb.columns]].copy()
    rhb = vs_rhb[[c for c in split_cols if c in vs_rhb.columns]].copy()
    lhb = lhb.rename(columns={c: f"{c}_vs_lhb" for c in lhb.columns if c != "player_id"})
    rhb = rhb.rename(columns={c: f"{c}_vs_rhb" for c in rhb.columns if c != "player_id"})

    result = overall.merge(lhb, on="player_id", how="left")
    result = result.merge(rhb, on="player_id", how="left")
    return result


# ---------------------------------------------------------------------------
# Pitcher contact-quality stats (from at-bat data, pitcher perspective)
# ---------------------------------------------------------------------------
def compute_pitcher_contact_stats(df, xba_lookup, xwoba_lookup):
    """Compute contact quality stats from pitcher perspective."""
    batted = df[df["is_batted_ball"] == 1].copy()

    keys = list(zip(batted["ev_bin"], batted["la_bin"]))
    default_xba = batted["is_hit"].mean()
    default_xwoba = batted["woba_value"].mean()
    batted["xba_val"] = [xba_lookup.get(k, default_xba) for k in keys]
    batted["xwoba_val"] = [xwoba_lookup.get(k, default_xwoba) for k in keys]
    batted["is_hard_hit"] = (batted["exit_velo"] >= HARD_HIT_EV).astype(int)
    batted["is_barrel"] = ((batted["exit_velo"] >= BARREL_EV_MIN) &
                           (batted["launch_angle"] >= BARREL_LA_MIN) &
                           (batted["launch_angle"] <= BARREL_LA_MAX)).astype(int)

    def agg(group, suffix=""):
        n = len(group)
        if n == 0:
            return {}
        return {
            f"bb_against{suffix}": n,
            f"avg_ev_against{suffix}": group["exit_velo"].mean(),
            f"hard_hit_pct_against{suffix}": group["is_hard_hit"].mean(),
            f"barrel_pct_against{suffix}": group["is_barrel"].mean(),
            f"xba_against{suffix}": group["xba_val"].mean(),
            f"xwoba_against{suffix}": group["xwoba_val"].mean(),
        }

    results = []
    for pid, grp in batted.groupby("opponent_player_id"):
        row = {"player_id": pid}
        row.update(agg(grp))
        lhb = grp[grp["pitcher_throws"] == 1]  # batter is LH when pitcher throws R... no
        # Actually: pitcher_throws is the pitcher's throw hand.
        # For pitcher splits we want vs LHB and vs RHB.
        # The at-bat table has the batter's player_id, not their handedness.
        # We'd need to join players.bats for batter handedness.
        # For now, just do overall.
        results.append(row)

    return pd.DataFrame(results)


def finalize_pitcher_stats(career_df, contact_df, player_info):
    """Merge pitcher career + contact stats with player info."""
    result = career_df.merge(player_info[["player_id", "first_name", "last_name",
                                          "team_abbr", "position"]],
                             on="player_id", how="left")
    if not contact_df.empty:
        contact_cols = ["player_id", "bb_against", "avg_ev_against",
                        "hard_hit_pct_against", "barrel_pct_against",
                        "xba_against", "xwoba_against"]
        contact_cols = [c for c in contact_cols if c in contact_df.columns]
        result = result.merge(contact_df[contact_cols], on="player_id", how="left")

    id_cols = ["player_id", "first_name", "last_name", "team_abbr", "position"]
    career_cols = ["g", "gs", "w", "l", "s", "hld", "ip", "bf",
                   "era", "fip", "xfip", "k_pct", "bb_pct", "k_bb_pct",
                   "whip", "k_9", "bb_9", "hr_9", "babip", "gb_pct", "war", "wpa"]
    contact_cols_ordered = ["bb_against", "avg_ev_against", "hard_hit_pct_against",
                            "barrel_pct_against", "xba_against", "xwoba_against"]
    ordered = id_cols + career_cols + contact_cols_ordered
    remaining = [c for c in result.columns if c not in ordered]
    ordered = [c for c in ordered if c in result.columns] + remaining
    return result[ordered]


# ---------------------------------------------------------------------------
# History archiving
# ---------------------------------------------------------------------------
def archive_to_history(engine, batter_df, pitcher_df, year):
    """Archive current-year advanced stats to history tables (idempotent)."""
    batter_hist = batter_df.copy()
    batter_hist.insert(0, "year", year)
    pitcher_hist = pitcher_df.copy()
    pitcher_hist.insert(0, "year", year)

    for tbl, df in [("batter_advanced_stats_history", batter_hist),
                    ("pitcher_advanced_stats_history", pitcher_hist)]:
        if inspect(engine).has_table(tbl):
            with engine.begin() as conn:
                conn.execute(text(f"DELETE FROM {tbl} WHERE year = :yr"), dict(yr=year))
        df.to_sql(tbl, engine, if_exists="append", index=False)

    print(f"  batter_advanced_stats_history:  {len(batter_hist)} rows")
    print(f"  pitcher_advanced_stats_history: {len(pitcher_hist)} rows")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <save_name>")
        print("Example: python src/analytics.py My-Save-2026")
        sys.exit(1)

    save_name = sys.argv[1]
    engine = get_engine(save_name)
    start = time.time()

    year = get_current_year(engine)
    print(f"Current season: {year}")

    player_info = get_player_info(engine)

    # --- League averages ---
    print("Computing league averages...")
    lg_bat = get_league_batting_averages(engine, year)
    lg_pitch = get_league_pitching_averages(engine, year)
    print(f"  Batting: lgBA={lg_bat['avg']:.3f}, lgOBP={lg_bat['obp']:.3f}, "
          f"lgSLG={lg_bat['slg']:.3f}, lgwOBA={lg_bat['woba']:.3f}")
    print(f"  Pitching: lgERA={lg_pitch['era']:.2f}, cFIP={lg_pitch['cfip']:.2f}")

    # --- Batter career stats ---
    print("Computing batter career stats...")
    batter_career = compute_batter_career_stats(engine, year, lg_bat)
    print(f"  {len(batter_career)} batters with career stats")

    # --- Load at-bat data ---
    print("Loading at-bat data...")
    ab_df = load_all_plate_appearances(engine)
    batted_count = ab_df["is_batted_ball"].sum()
    print(f"  {len(ab_df):,} plate appearances, {batted_count:,} batted balls")

    # --- Build EV/LA lookups ---
    print("Building EV/LA lookup tables...")
    xba_lookup, xslg_lookup, xwoba_lookup = build_ev_la_lookups(ab_df)

    # --- Batter contact stats ---
    print("Computing batter contact quality stats...")
    batter_contact = compute_contact_stats(ab_df, xba_lookup, xslg_lookup, xwoba_lookup)
    print(f"  {len(batter_contact)} batters with contact data")

    # --- Finalize batter table ---
    batter_df = finalize_batter_stats(batter_career, batter_contact, player_info)

    # --- Pitcher career stats ---
    print("Computing pitcher career stats...")
    pitcher_career = compute_pitcher_career_stats(engine, year, lg_pitch)
    print(f"  {len(pitcher_career)} pitchers with career stats")

    # --- Pitcher contact stats ---
    print("Computing pitcher contact quality stats...")
    pitcher_contact = compute_pitcher_contact_stats(ab_df, xba_lookup, xwoba_lookup)
    print(f"  {len(pitcher_contact)} pitchers with contact data")

    # --- Finalize pitcher table ---
    pitcher_df = finalize_pitcher_stats(pitcher_career, pitcher_contact, player_info)

    # --- Write to database ---
    print("Writing tables...")
    batter_df.to_sql("batter_advanced_stats", engine, if_exists="replace", index=False)
    pitcher_df.to_sql("pitcher_advanced_stats", engine, if_exists="replace", index=False)
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_batter_advanced_stats_player_id ON batter_advanced_stats (player_id)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_pitcher_advanced_stats_player_id ON pitcher_advanced_stats (player_id)"))
        else:
            conn.execute(text("ALTER TABLE batter_advanced_stats ADD PRIMARY KEY (player_id)"))
            conn.execute(text("ALTER TABLE pitcher_advanced_stats ADD PRIMARY KEY (player_id)"))
        conn.commit()

    # Also drop the old batter_xba table if it exists
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS batter_xba"))
        conn.commit()

    # Archive to history tables
    print("Archiving to history tables...")
    archive_to_history(engine, batter_df, pitcher_df, year)

    elapsed = time.time() - start

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"Analytics complete in {elapsed:.1f}s")
    print(f"  batter_advanced_stats:  {len(batter_df)} rows")
    print(f"  pitcher_advanced_stats: {len(pitcher_df)} rows")
    print(f"{'='*60}")

    # Top hitters by wRC+
    qual_bat = batter_df[batter_df["pa"] >= 300].copy()
    if len(qual_bat) > 0:
        print("\nTop 10 hitters by wRC+ (min 300 PA):")
        top = qual_bat.nlargest(10, "wrc_plus")
        for _, row in top.iterrows():
            abbr = str(row.get('team_abbr', ''))[:4] or '???'
            xwoba_str = f"  xwOBA={row['xwoba']:.3f}" if pd.notna(row.get('xwoba')) else ""
            print(f"  {row['first_name']} {row['last_name']:15s} {abbr:>4s}  "
                  f"wRC+={row['wrc_plus']:5.1f}  wOBA={row['woba']:.3f}  "
                  f"BA={row['ba']:.3f}  OPS={row['ops']:.3f}{xwoba_str}")

    # Top pitchers by FIP
    qual_pit = pitcher_df[(pitcher_df["ip"] >= 50) & (pitcher_df["gs"] >= 10)].copy()
    if len(qual_pit) > 0:
        print("\nTop 10 starting pitchers by FIP (min 50 IP, 10 GS):")
        top = qual_pit.nsmallest(10, "fip")
        for _, row in top.iterrows():
            abbr = str(row.get('team_abbr', ''))[:4] or '???'
            print(f"  {row['first_name']} {row['last_name']:15s} {abbr:>4s}  "
                  f"FIP={row['fip']:.2f}  ERA={row['era']:.2f}  "
                  f"K-BB%={row['k_bb_pct']:.1%}  WHIP={row['whip']:.2f}")


if __name__ == "__main__":
    main()
