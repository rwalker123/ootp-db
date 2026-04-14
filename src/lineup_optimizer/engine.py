"""Lineup computation and algorithm functions."""

import math

from config import (
    REGRESSION_EXPONENT, PA_REGRESSION_THRESHOLD,
    WRC_CAP_HEADROOM, WOBA_BB, WOBA_1B, WOBA_2B, WOBA_3B, WOBA_HR,
)
from ootp_db_constants import BATS_MAP, POS_MAP

from .constants import WOBA_HP

# ── PA regression credibility threshold ──────────────────────────────────────
# At 300 PA: 50/50 blend of observed vs ratings anchor
# At 13 PA: ~4% observed (matches Tango reliability threshold)
WOBA_REG_PA = 300

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
_RATING_TO_WOBA_SLOPE = 0.002   # each rating_offense point above/below 50 ≈ .002 wOBA

# ── Positional eligibility floors ────────────────────────────────────────────
MIN_FIELDING_RATING = 40          # floor for corner positions (1B, 3B, LF, RF)
MIN_FIELDING_RATING_PREMIUM = 50  # floor for premium defensive spots (C, 2B, SS, CF)
MIN_POS_GAMES = 5                 # minimum career games at position

FIELD_POSITIONS = (2, 3, 4, 5, 6, 7, 8, 9)  # C, 1B, 2B, 3B, SS, LF, CF, RF

PREMIUM_DEFENSE_POSITIONS = frozenset([2, 4, 6, 8])  # C, 2B, SS, CF
CORNER_POSITIONS = frozenset([5, 7, 9])               # 3B, LF, RF
BATTER_POSITIONS = frozenset([3, 5, 7, 9])            # 1B, 3B, LF, RF — bat-first spots

# Defense bonus scales per position class (fielding_rating / 100 * scale = sort_score bonus).
_DEFENSE_BONUS_SCALE_PREMIUM  = 4.0    # C/2B/SS/CF: 70 rating → +2.8 pts
_DEFENSE_BONUS_SCALE_CORNER   = 2.0    # 3B/LF/RF:   70 rating → +1.4 pts
_DEFENSE_BONUS_SCALE_1B       = 1.5    # 1B:         70 rating → +1.05 pts
_FAVOR_OFFENSE_DIVISOR        = 2      # favor_offense halves each scale above

_PRIMARY_POS_BONUS_MAX = 1.0           # max primary-position bonus (at 100% usage)


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
                         avg_rating_offense=50.0, reg_pa=None):
    """Regress raw wOBA toward a ratings-derived expectation.

    Protects against small-sample call-ups with inflated wOBA while still
    allowing genuinely talented rookies (high rating_offense) to rank well.

      • At 0 PA  → 100% ratings-based (star prospect earns the spot on talent)
      • At 300 PA → 50/50 observed vs expected
      • At 600 PA → 67% observed (established starters mostly judged by results)
    """
    if reg_pa is None:
        reg_pa = WOBA_REG_PA
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


def rank_players(players, philosophy, hand):
    """Sort all eligible players by the philosophy's primary metric (best first)."""
    if philosophy == "platoon":
        key = lambda p: platoon_score(p, hand)
    elif philosophy == "hot-hand":
        key = lambda p: hot_hand_sort_score(p)
    else:  # modern and traditional both sort by sort_score; slot mapping differs
        key = lambda p: p.get("sort_score") or 0.0
    return sorted(players, key=key, reverse=True)


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
    favor_offense:     reduces defense bonus weight at premium positions.

    Returns a list of player dicts, each with an added 'assigned_pos' key.
    'forced' flag is set True on pre-assigned players for HTML badge display.
    """
    forced_pos = forced_pos or {}
    forced_start_ids = forced_start_ids or set()

    selected: dict = {}   # pos_code -> player dict
    used_ids: set = set()

    # ── Step 1: Pre-assign position-forced players ────────────────────────────
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
    by_pos: dict = {pos: [] for pos in FIELD_POSITIONS}
    secondary_pos: dict = {pos: [] for pos in FIELD_POSITIONS}
    emergency_pos: dict = {pos: [] for pos in FIELD_POSITIONS}
    for p in ranked:
        if p["player_id"] in used_ids:
            continue
        primary = p.get("position")
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
                floor = MIN_FIELDING_RATING_PREMIUM if pos_code in PREMIUM_DEFENSE_POSITIONS \
                        else MIN_FIELDING_RATING
                if rating >= floor and games >= MIN_POS_GAMES:
                    if pos_code in PREMIUM_DEFENSE_POSITIONS and primary in BATTER_POSITIONS:
                        secondary_pos[pos_code].append(p)
                    else:
                        by_pos[pos_code].append(p)

    # ── Step 3: Fill remaining positions in scarcity order ───────────────────
    def _scarcity_key(pos):
        if pos in selected:
            return (999, 0)
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
            secondary_candidates = [p for p in secondary_pos[pos_code] if p["player_id"] not in used_ids]
            if secondary_candidates:
                candidates = secondary_candidates
            else:
                candidates = [p for p in emergency_pos[pos_code] if p["player_id"] not in used_ids]
                emergency_used = bool(candidates)
        if not candidates:
            continue
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
            extras = [p for p in ranked if p["player_id"] not in used_ids
                      and p.get("position") in FIELD_POSITIONS]
            if extras:
                dh = dict(extras[0])
                dh["assigned_pos"] = "DH"
                result.append(dh)
                used_ids.add(extras[0]["player_id"])

    # ── Step 4b: Defensive swap pass ─────────────────────────────────────────
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
                new_fielder = dict(dh_player)
                label = POS_MAP[best_swap_pos]
                if dh_player.get("position") != best_swap_pos:
                    label += "*"
                new_fielder["assigned_pos"] = label
                new_fielder.pop("forced", None)
                new_dh = dict(old_fielder)
                new_dh["assigned_pos"] = "DH"
                new_dh.pop("forced", None)
                selected[best_swap_pos] = new_fielder
                result = [selected[k] for k in FIELD_POSITIONS if k in selected]
                result.append(new_dh)

    # ── Step 5: Guarantee forced_start_ids are in the lineup ─────────────────
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

    selected_ids = {p["player_id"] for p in selected}
    re_ranked = [p for p in ranked if p["player_id"] in selected_ids]

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
