#!/usr/bin/env python3
"""IFA prospect rating system for OOTP Baseball.

Computes composite 0-100 ratings for all international amateur free agent prospects using:
- Ceiling (POT from players_value)
- Tools (batting or pitching talent ratings)
- Development (work ethic + intelligence)
- Defense (fielding potential at primary position)
- Age (16=prime, 20=late)

Run after import.py:
    python src/ifa_ratings.py My-Save-2026
"""

import sys
import time
from pathlib import Path

import pandas as pd
from ootp_db_constants import NATION_USA
from shared_css import db_name_from_save, get_write_engine
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


def load_ifa_data(engine):
    """Load all IFA-eligible prospects with ratings joined in."""
    sql = """
        SELECT
            p.player_id, p.first_name, p.last_name, p.position,
            p.age, p.bats, p.throws, p.nation_id,
            n.name as nation,
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
        JOIN nations n ON n.nation_id = p.nation_id
        LEFT JOIN players_value pv
            ON pv.player_id = p.player_id AND pv.league_id = 0
        LEFT JOIN players_batting pb
            ON pb.player_id = p.player_id
        LEFT JOIN players_pitching pp
            ON pp.player_id = p.player_id
        LEFT JOIN players_fielding pf
            ON pf.player_id = p.player_id
        WHERE p.draft_eligible = 0
          AND p.team_id = 0
          AND p.age <= 20
          AND p.nation_id != :nation_usa
          AND p.retired = 0
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), dict(nation_usa=NATION_USA)).fetchall()

    cols = [
        "player_id", "first_name", "last_name", "position",
        "age", "bats", "throws", "nation_id", "nation",
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


def score_age(age):
    """Score 0-100 based on signing age. 16=prime, 20=late."""
    age_scores = {16: 80, 17: 60, 18: 40, 19: 20, 20: 0}
    return float(age_scores.get(int(age or 18), 40))


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

BATTER_WEIGHTS = dict(ceiling=0.35, tools=0.30, development=0.20, defense=0.10, age=0.05)
PITCHER_WEIGHTS = dict(ceiling=0.35, stuff=0.30, development=0.20, command=0.10, age=0.05)


def compute_batter_ifa(df):
    batters = df[df["position"] != 1].copy()
    records = []
    for _, row in batters.iterrows():
        row = row.to_dict()
        pos = int(row.get("position") or 0)
        s_ceiling = score_ceiling(row)
        s_tools = score_tools_batter(row)
        s_dev = score_development(row)
        s_def = score_defense(row, pos)
        s_age = score_age(row.get("age"))

        overall = (
            s_ceiling * BATTER_WEIGHTS["ceiling"]
            + s_tools * BATTER_WEIGHTS["tools"]
            + s_dev * BATTER_WEIGHTS["development"]
            + s_def * BATTER_WEIGHTS["defense"]
            + s_age * BATTER_WEIGHTS["age"]
        )

        pot = row.get("pot") or 30
        we = row.get("personality_work_ethic") or 100
        iq = row.get("personality_intelligence") or 100
        greed = row.get("personality_greed") or 100
        age = row.get("age") or 18

        records.append(dict(
            player_id=row["player_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            position=pos,
            age=age,
            player_type="batter",
            bats=row.get("bats"),
            throws=row.get("throws"),
            nation_id=row.get("nation_id"),
            nation=row.get("nation"),
            oa=row.get("oa"),
            pot=pot,
            talent_value=row.get("talent_value"),
            rating_overall=round(overall, 2),
            rating_ceiling=round(s_ceiling, 2),
            rating_tools=round(s_tools, 2),
            rating_development=round(s_dev, 2),
            rating_defense=round(s_def, 2),
            rating_age=round(s_age, 2),
            flag_elite_ceiling=int(pot >= 65),
            flag_high_ceiling=int(pot >= 55),
            flag_elite_we=int(we > 160),
            flag_elite_iq=int(iq > 160),
            flag_demanding=int(greed > 160),
            flag_international=1,
            flag_prime_age=int(int(age) == 16),
            work_ethic=we,
            intelligence=iq,
            greed=greed,
        ))
    return pd.DataFrame(records)


def compute_pitcher_ifa(df):
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
        s_age = score_age(row.get("age"))

        overall = (
            s_ceiling * PITCHER_WEIGHTS["ceiling"]
            + s_stuff * PITCHER_WEIGHTS["stuff"]
            + s_dev * PITCHER_WEIGHTS["development"]
            + s_command * PITCHER_WEIGHTS["command"]
            + s_age * PITCHER_WEIGHTS["age"]
        )

        pot = row.get("pot") or 30
        we = row.get("personality_work_ethic") or 100
        iq = row.get("personality_intelligence") or 100
        greed = row.get("personality_greed") or 100
        age = row.get("age") or 18

        records.append(dict(
            player_id=row["player_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            position=pos,
            age=age,
            player_type="pitcher",
            bats=row.get("bats"),
            throws=row.get("throws"),
            nation_id=row.get("nation_id"),
            nation=row.get("nation"),
            oa=row.get("oa"),
            pot=pot,
            talent_value=row.get("talent_value"),
            rating_overall=round(overall, 2),
            rating_ceiling=round(s_ceiling, 2),
            rating_tools=round(s_stuff, 2),
            rating_development=round(s_dev, 2),
            rating_defense=round(s_command, 2),
            rating_age=round(s_age, 2),
            flag_elite_ceiling=int(pot >= 65),
            flag_high_ceiling=int(pot >= 55),
            flag_elite_we=int(we > 160),
            flag_elite_iq=int(iq > 160),
            flag_demanding=int(greed > 160),
            flag_international=1,
            flag_prime_age=int(int(age) == 16),
            work_ethic=we,
            intelligence=iq,
            greed=greed,
        ))
    return pd.DataFrame(records)


def main():
    if len(sys.argv) < 2:
        print("Usage: python src/ifa_ratings.py <save_name>")
        sys.exit(1)

    save_name = sys.argv[1]
    start = time.time()

    print(f"Loading IFA prospect data for {save_name}...")
    engine = get_write_engine(save_name)
    df = load_ifa_data(engine)
    print(f"  {len(df)} IFA-eligible prospects loaded")

    batters_df = compute_batter_ifa(df)
    pitchers_df = compute_pitcher_ifa(df)

    combined = pd.concat([batters_df, pitchers_df], ignore_index=True)
    combined = combined.sort_values("rating_overall", ascending=False)
    combined = combined.drop_duplicates(subset="player_id", keep="first")

    combined.to_sql("ifa_ratings", engine, if_exists="replace", index=False)

    elapsed = time.time() - start
    print(f"\n✓ ifa_ratings ({len(combined)} rows) written in {elapsed:.1f}s")

    POS_MAP = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
    BATS_MAP = {1: "R", 2: "L", 3: "S"}

    def show_top(subset, label, n=20):
        top = subset.sort_values("rating_overall", ascending=False).head(n)
        print(f"\n--- Top {n} {label} ---")
        print(f"{'#':>3}  {'Name':<22}  {'Pos':>4}  {'Age':>3}  {'OA/POT':>7}  {'Rating':>7}  {'Bats':>4}  {'Nation':<20}  {'Tools':>6}  {'Dev':>5}")
        for i, row in enumerate(top.itertuples(), 1):
            pos = POS_MAP.get(int(row.position), str(row.position))
            oa = int(row.oa) if row.oa and row.oa == row.oa else 0
            pot = int(row.pot) if row.pot and row.pot == row.pot else 0
            bats = BATS_MAP.get(int(row.bats) if row.bats else 0, "?")
            nation = (row.nation or "Unknown")[:18]
            print(
                f"{i:>3}  {row.first_name + ' ' + row.last_name:<22}  {pos:>4}  "
                f"{int(row.age) if row.age else 0:>3}  {oa:>3}/{pot:<3}  "
                f"{row.rating_overall:>7.2f}  {bats:>4}  {nation:<20}  "
                f"{row.rating_tools:>6.1f}  {row.rating_development:>5.1f}"
            )

    b_df = combined[combined["player_type"] == "batter"]
    p_df = combined[combined["player_type"] == "pitcher"]
    show_top(b_df, "IFA Batters")
    show_top(p_df, "IFA Pitchers")


if __name__ == "__main__":
    main()
