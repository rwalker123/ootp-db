"""query_lineup — data assembly without HTML generation or cache check."""

import json

from ootp_db_constants import BATS_MAP, POS_MAP
from shared_css import get_engine
from sqlalchemy import text

from .constants import PHILOSOPHIES, PHIL_LABELS
from .engine import (
    temperature_flag, rank_players, build_lineup, score_alternation,
    is_star, _resolve_player_name,
)
from .loaders import (
    resolve_team, get_dh_used, load_roster_batters, load_fielding_ratings,
    load_position_games, load_batter_stats, load_30day_stats,
)

from ootp_db_constants import MLB_LEAGUE_ID


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
