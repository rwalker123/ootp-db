#!/usr/bin/env python3
"""Draft prospect rating system for OOTP Baseball.

Computes composite 0-100 ratings for all draft-eligible prospects using:
- Ceiling (POT from players_value)
- Tools (batting or pitching talent ratings)
- Development (work ethic + intelligence)
- Defense (fielding potential at primary position)
- Proximity (college vs HS, age)

Run after import.py:
    python src/draft_ratings.py My-Save-2026
"""

import sys
import time
from pathlib import Path

import pandas as pd
from shared_css import db_name_from_save, get_engine
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def clamp(val, lo=0.0, hi=100.0):
    if val is None:
        return 50.0
    try:
        v = float(val)
        if v != v:  # NaN check
            return 50.0
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return 50.0


def norm(r, default=40):
    """Normalize a 20-80 scouting rating to 0-100."""
    v = r if r is not None else default
    if v == 0:
        v = default
    return clamp((v - 20) / 60 * 100)


def load_prospect_data(engine):
    """Load all draft-eligible prospects with ratings joined in."""
    sql = """
        SELECT
            p.player_id, p.first_name, p.last_name, p.position,
            p.age, p.bats, p.throws, p.college, p.nation_id,
            p.personality_work_ethic, p.personality_intelligence,
            p.personality_leader, p.personality_greed,
            pv.oa, pv.pot, pv.talent_value,
            pb.batting_ratings_talent_contact,
            pb.batting_ratings_talent_gap,
            pb.batting_ratings_talent_eye,
            pb.batting_ratings_talent_strikeouts,
            pb.batting_ratings_talent_power,
            pp.pitching_ratings_talent_stuff,
            pp.pitching_ratings_talent_movement,
            pp.pitching_ratings_talent_control,
            pf.fielding_rating_pos2_pot,
            pf.fielding_rating_pos3_pot,
            pf.fielding_rating_pos4_pot,
            pf.fielding_rating_pos5_pot,
            pf.fielding_rating_pos6_pot,
            pf.fielding_rating_pos7_pot,
            pf.fielding_rating_pos8_pot,
            pf.fielding_rating_pos9_pot
        FROM players p
        LEFT JOIN players_value pv
            ON pv.player_id = p.player_id AND pv.league_id = 0
        LEFT JOIN players_batting pb
            ON pb.player_id = p.player_id
        LEFT JOIN players_pitching pp
            ON pp.player_id = p.player_id
        LEFT JOIN players_fielding pf
            ON pf.player_id = p.player_id
        WHERE p.draft_eligible = 1 AND p.retired = 0
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()

    cols = [
        "player_id", "first_name", "last_name", "position",
        "age", "bats", "throws", "college", "nation_id",
        "personality_work_ethic", "personality_intelligence",
        "personality_leader", "personality_greed",
        "oa", "pot", "talent_value",
        "batting_ratings_talent_contact",
        "batting_ratings_talent_gap",
        "batting_ratings_talent_eye",
        "batting_ratings_talent_strikeouts",
        "batting_ratings_talent_power",
        "pitching_ratings_talent_stuff",
        "pitching_ratings_talent_movement",
        "pitching_ratings_talent_control",
        "fielding_rating_pos2_pot",
        "fielding_rating_pos3_pot",
        "fielding_rating_pos4_pot",
        "fielding_rating_pos5_pot",
        "fielding_rating_pos6_pot",
        "fielding_rating_pos7_pot",
        "fielding_rating_pos8_pot",
        "fielding_rating_pos9_pot",
    ]
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Sub-score functions
# ---------------------------------------------------------------------------

def score_ceiling(row):
    pot = row.get("pot") or 30
    return clamp((pot - 20) / 60 * 100)


def score_development(row):
    we = row.get("personality_work_ethic") or 100
    iq = row.get("personality_intelligence") or 100
    return clamp(we / 2) * 0.50 + clamp(iq / 2) * 0.50


def score_proximity(row):
    college = row.get("college") or 0
    age = row.get("age") or 20
    base = 65 if college else 45
    if college:
        age_adj = (23 - age) * 3
    else:
        age_adj = (18 - age) * 3
    return clamp(base + age_adj)


POS_FIELD_COL = {
    2: "fielding_rating_pos2_pot",
    3: "fielding_rating_pos3_pot",
    4: "fielding_rating_pos4_pot",
    5: "fielding_rating_pos5_pot",
    6: "fielding_rating_pos6_pot",
    7: "fielding_rating_pos7_pot",
    8: "fielding_rating_pos8_pot",
    9: "fielding_rating_pos9_pot",
}
PREMIUM_POS = {2, 6, 4, 8}
LOW_POS = {3, 7, 9}


def score_defense(row, pos):
    col = POS_FIELD_COL.get(pos)
    if col:
        val = row.get(col) or 40
        base = norm(val)
    else:
        base = 50.0
    mult = 1.3 if pos in PREMIUM_POS else (0.7 if pos in LOW_POS else 1.0)
    return clamp(base * mult)


def score_tools_batter(row):
    cols = [
        "batting_ratings_talent_contact",
        "batting_ratings_talent_gap",
        "batting_ratings_talent_power",
        "batting_ratings_talent_eye",
        "batting_ratings_talent_strikeouts",
    ]
    scores = [norm(row.get(c) or 40) for c in cols]
    return sum(scores) / len(scores)


def score_tools_pitcher(row):
    stuff = row.get("pitching_ratings_talent_stuff") or 40
    movement = row.get("pitching_ratings_talent_movement") or 40
    control = row.get("pitching_ratings_talent_control") or 40
    return (
        norm(stuff) * 0.40
        + norm(movement) * 0.35
        + norm(control) * 0.25
    )


# ---------------------------------------------------------------------------
# Compute ratings
# ---------------------------------------------------------------------------

BATTER_WEIGHTS = dict(ceiling=0.35, tools=0.30, development=0.20, defense=0.10, proximity=0.05)
PITCHER_WEIGHTS = dict(ceiling=0.35, stuff=0.30, development=0.20, command=0.10, proximity=0.05)


def compute_batter_prospects(df):
    batters = df[df["position"] != 1].copy()
    records = []
    for _, row in batters.iterrows():
        row = row.to_dict()
        pos = int(row.get("position") or 0)
        s_ceiling = score_ceiling(row)
        s_tools = score_tools_batter(row)
        s_dev = score_development(row)
        s_def = score_defense(row, pos)
        s_prox = score_proximity(row)

        overall = (
            s_ceiling * BATTER_WEIGHTS["ceiling"]
            + s_tools * BATTER_WEIGHTS["tools"]
            + s_dev * BATTER_WEIGHTS["development"]
            + s_def * BATTER_WEIGHTS["defense"]
            + s_prox * BATTER_WEIGHTS["proximity"]
        )

        pot = row.get("pot") or 30
        we = row.get("personality_work_ethic") or 100
        iq = row.get("personality_intelligence") or 100
        greed = row.get("personality_greed") or 100

        records.append(dict(
            player_id=row["player_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            position=pos,
            age=row.get("age"),
            player_type="batter",
            bats=row.get("bats"),
            throws=row.get("throws"),
            college=int(row.get("college") or 0),
            domestic=int((row.get("nation_id") or 0) == 206),
            oa=row.get("oa"),
            pot=pot,
            talent_value=row.get("talent_value"),
            rating_overall=round(overall, 2),
            rating_ceiling=round(s_ceiling, 2),
            rating_tools=round(s_tools, 2),
            rating_development=round(s_dev, 2),
            rating_defense=round(s_def, 2),
            rating_proximity=round(s_prox, 2),
            flag_elite_ceiling=int(pot >= 65),
            flag_high_ceiling=int(pot >= 55),
            flag_elite_we=int(we > 160),
            flag_elite_iq=int(iq > 160),
            flag_demanding=int(greed > 160),
            flag_international=int((row.get("nation_id") or 0) != 206),
            flag_hs=int(int(row.get("college") or 0) == 0),
            work_ethic=we,
            intelligence=iq,
            greed=greed,
        ))
    return pd.DataFrame(records)


def compute_pitcher_prospects(df):
    pitchers = df[df["position"] == 1].copy()
    records = []
    for _, row in pitchers.iterrows():
        row = row.to_dict()
        pos = 1
        s_ceiling = score_ceiling(row)
        s_stuff = score_tools_pitcher(row)
        s_dev = score_development(row)
        control = row.get("pitching_ratings_talent_control") or 40
        s_command = norm(control)
        s_prox = score_proximity(row)

        overall = (
            s_ceiling * PITCHER_WEIGHTS["ceiling"]
            + s_stuff * PITCHER_WEIGHTS["stuff"]
            + s_dev * PITCHER_WEIGHTS["development"]
            + s_command * PITCHER_WEIGHTS["command"]
            + s_prox * PITCHER_WEIGHTS["proximity"]
        )

        pot = row.get("pot") or 30
        we = row.get("personality_work_ethic") or 100
        iq = row.get("personality_intelligence") or 100
        greed = row.get("personality_greed") or 100

        records.append(dict(
            player_id=row["player_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            position=pos,
            age=row.get("age"),
            player_type="pitcher",
            bats=row.get("bats"),
            throws=row.get("throws"),
            college=int(row.get("college") or 0),
            domestic=int((row.get("nation_id") or 0) == 206),
            oa=row.get("oa"),
            pot=pot,
            talent_value=row.get("talent_value"),
            rating_overall=round(overall, 2),
            rating_ceiling=round(s_ceiling, 2),
            rating_tools=round(s_stuff, 2),
            rating_development=round(s_dev, 2),
            rating_defense=round(s_command, 2),
            rating_proximity=round(s_prox, 2),
            flag_elite_ceiling=int(pot >= 65),
            flag_high_ceiling=int(pot >= 55),
            flag_elite_we=int(we > 160),
            flag_elite_iq=int(iq > 160),
            flag_demanding=int(greed > 160),
            flag_international=int((row.get("nation_id") or 0) != 206),
            flag_hs=int(int(row.get("college") or 0) == 0),
            work_ethic=we,
            intelligence=iq,
            greed=greed,
        ))
    return pd.DataFrame(records)


def main():
    if len(sys.argv) < 2:
        print("Usage: python src/draft_ratings.py <save_name>")
        sys.exit(1)

    save_name = sys.argv[1]
    start = time.time()

    print(f"Loading prospect data for {save_name}...")
    engine = get_engine(save_name)
    df = load_prospect_data(engine)
    print(f"  {len(df)} draft-eligible prospects loaded")

    batters_df = compute_batter_prospects(df)
    pitchers_df = compute_pitcher_prospects(df)

    combined = pd.concat([batters_df, pitchers_df], ignore_index=True)
    combined = combined.sort_values("rating_overall", ascending=False)
    combined = combined.drop_duplicates(subset="player_id", keep="first")

    combined.to_sql("draft_ratings", engine, if_exists="replace", index=False)

    elapsed = time.time() - start
    print(f"\n✓ draft_ratings ({len(combined)} rows) written in {elapsed:.1f}s")

    POS_MAP = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
    BATS_MAP = {1: "R", 2: "L", 3: "S"}

    def show_top(subset, label, n=20):
        top = subset.sort_values("rating_overall", ascending=False).head(n)
        print(f"\n--- Top {n} {label} ---")
        print(f"{'#':>3}  {'Name':<22}  {'Pos':>4}  {'Age':>3}  {'OA/POT':>7}  {'Rating':>7}  {'Bats':>4}  {'Type':>4}  {'Tools':>6}  {'Dev':>5}")
        for i, row in enumerate(top.itertuples(), 1):
            pos = POS_MAP.get(int(row.position), str(row.position))
            oa = int(row.oa) if row.oa and row.oa == row.oa else 0
            pot = int(row.pot) if row.pot and row.pot == row.pot else 0
            bats = BATS_MAP.get(int(row.bats) if row.bats else 0, "?")
            typ = "COL" if row.college else "HS"
            print(
                f"{i:>3}  {row.first_name + ' ' + row.last_name:<22}  {pos:>4}  "
                f"{int(row.age) if row.age else 0:>3}  {oa:>3}/{pot:<3}  "
                f"{row.rating_overall:>7.2f}  {bats:>4}  {typ:>4}  "
                f"{row.rating_tools:>6.1f}  {row.rating_development:>5.1f}"
            )

    b_df = combined[combined["player_type"] == "batter"]
    p_df = combined[combined["player_type"] == "pitcher"]
    show_top(b_df, "Batters")
    show_top(p_df, "Pitchers")


if __name__ == "__main__":
    main()
