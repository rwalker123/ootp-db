"""DB loaders, scoring engine, and query_rotation() for /rotation-analysis."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ootp_db_constants import (
    MLB_LEAGUE_ID,
    MLB_LEVEL_ID,
    ROLE_SP,
    ROLE_RP,
    ROLE_CL,
    THROWS_MAP,
    SPLIT_CAREER_OVERALL,
)
from config import CAREER_STATS_LOOKBACK_YEARS
from shared_css import get_engine

from .constants import (
    CAREER_GS_TARGET,
    DEPTH_MIN_GS,
    FIP_ELITE,
    FIP_POOR,
    FIVE_MAN_SLOTS,
    INJURY_LOOKBACK_YEARS,
    LOW_CAREER_GS_NON_ACE,
    LOW_SAMPLE_IP,
    MIN_DEPTH_STAMINA,
    MIN_SP_GS_CURRENT,
    MIN_SP_GS_PRIOR,
    MIN_SWING_MAN_STAMINA,
    MODE_WEIGHTS,
    OPENER_FIP_GOOD,
    OPENER_FIP_POOR,
    OPENER_K_PCT_GOOD,
    OPENER_K_PCT_POOR,
    OPENER_MIN_IP,
    OPENER_OPPOSITE_HAND_BONUS,
    OPENER_SHORT_IP_LABEL,
    OPENER_SLOT_LUCK_THRESHOLD,
    OPENER_WHIP_GOOD,
    OPENER_WHIP_POOR,
    SIX_MAN_SLOTS,
    STAMINA_FULL,
    STAMINA_POOR,
    THROWS_LABEL,
    XFIP_ELITE,
    XFIP_POOR,
    FIP_XFIP_LUCK_THRESHOLD,
)

# ---------------------------------------------------------------------------
# Team resolution
# ---------------------------------------------------------------------------

def resolve_team(conn, team_query):
    """Return (team_id, full_name, abbr) or (None, None, None).

    If team_query is None/empty, falls back to the human manager's team.
    Raises ValueError on ambiguous match.
    """
    if team_query:
        rows = conn.execute(text(
            "SELECT team_id, name, nickname, abbr FROM teams "
            "WHERE (nickname LIKE :q OR name LIKE :q OR abbr LIKE :q) "
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


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_starter_pool(conn, team_id):
    """Load MLB starting pitcher candidates from the team's active roster.

    Includes:
      - Players with role=ROLE_SP (11), regardless of stamina (game already tagged them as SP)
      - Players with role=ROLE_RP/CL who have >= MIN_SP_GS_CURRENT career GS AND
        stamina >= MIN_SWING_MAN_STAMINA — swing-man/bulk-inning candidates only;
        low-stamina relievers (closers, specialists) are excluded.

    Excludes players on IL or DFA via players_roster_status.
    Returns list of dicts including stamina.
    """
    rows = conn.execute(text(f"""
        SELECT DISTINCT p.player_id, p.first_name, p.last_name,
               p.position, p.role, p.throws, p.age,
               COALESCE(pp.pitching_ratings_misc_stamina, 50) AS stamina
        FROM players p
        JOIN team_roster tr ON tr.player_id = p.player_id
            AND tr.team_id = :tid AND tr.list_id = 1
        LEFT JOIN players_roster_status prs ON prs.player_id = p.player_id
        LEFT JOIN pitcher_advanced_stats pas ON pas.player_id = p.player_id
        LEFT JOIN players_pitching pp ON pp.player_id = p.player_id
        WHERE p.league_id = {MLB_LEAGUE_ID}
          AND (prs.player_id IS NULL
               OR (prs.is_on_waivers = 0
                   AND COALESCE(prs.designated_for_assignment, 0) = 0
                   AND COALESCE(prs.is_on_dl, 0) = 0
                   AND COALESCE(prs.is_on_dl60, 0) = 0))
          AND (
            p.role = {ROLE_SP}
            OR (
              p.role IN ({ROLE_RP}, {ROLE_CL})
              AND COALESCE(pas.gs, 0) >= {MIN_SP_GS_CURRENT}
              AND COALESCE(pp.pitching_ratings_misc_stamina, 0) >= {MIN_SWING_MAN_STAMINA}
            )
          )
        ORDER BY p.last_name, p.first_name
    """), dict(tid=team_id)).fetchall()
    return [dict(r._mapping) for r in rows]


def load_relief_corps(conn, team_id):
    """Load relievers from the team's active roster (opener candidates).

    Returns relievers and closers only (role=RP or CL), not on IL/DFA.
    """
    rows = conn.execute(text(f"""
        SELECT DISTINCT p.player_id, p.first_name, p.last_name,
               p.position, p.role, p.throws, p.age
        FROM players p
        JOIN team_roster tr ON tr.player_id = p.player_id
            AND tr.team_id = :tid AND tr.list_id = 1
        LEFT JOIN players_roster_status prs ON prs.player_id = p.player_id
        WHERE p.league_id = {MLB_LEAGUE_ID}
          AND (prs.player_id IS NULL
               OR (prs.is_on_waivers = 0
                   AND COALESCE(prs.designated_for_assignment, 0) = 0
                   AND COALESCE(prs.is_on_dl, 0) = 0
                   AND COALESCE(prs.is_on_dl60, 0) = 0))
          AND p.role IN ({ROLE_RP}, {ROLE_CL})
        ORDER BY p.last_name, p.first_name
    """), dict(tid=team_id)).fetchall()
    return [dict(r._mapping) for r in rows]


def load_pitcher_stats(conn, player_ids):
    """Load pitcher_advanced_stats for the given player_ids.

    Returns dict keyed by player_id.
    """
    if not player_ids:
        return {}
    clause = ",".join(str(i) for i in player_ids)
    rows = conn.execute(text(f"""
        SELECT player_id,
               g, gs, w, l, s, hld, ip, bf,
               era, fip, xfip, k_pct, bb_pct, k_bb_pct,
               whip, k_9, bb_9, hr_9, babip, gb_pct, war, wpa,
               bf_vs_lhb, era_vs_lhb, fip_vs_lhb,
               k_pct_vs_lhb, bb_pct_vs_lhb, k_bb_pct_vs_lhb,
               whip_vs_lhb, babip_vs_lhb,
               bf_vs_rhb, era_vs_rhb, fip_vs_rhb,
               k_pct_vs_rhb, bb_pct_vs_rhb, k_bb_pct_vs_rhb,
               whip_vs_rhb, babip_vs_rhb
        FROM pitcher_advanced_stats
        WHERE player_id IN ({clause})
    """)).fetchall()
    return {r.player_id: dict(r._mapping) for r in rows}


def load_pitcher_ratings(conn, player_ids):
    """Load player_ratings rows for the given pitcher player_ids.

    Returns dict keyed by player_id. Some pitchers (minor-league-only, recently called up)
    may not have rows — callers should use .get() with defaults.
    """
    if not player_ids:
        return {}
    clause = ",".join(str(i) for i in player_ids)
    rows = conn.execute(text(f"""
        SELECT player_id,
               rating_overall, rating_now, rating_potential, rating_durability,
               flag_injury_risk, confidence, prone_overall, oa, pot
        FROM player_ratings
        WHERE player_id IN ({clause})
          AND player_type = 'pitcher'
    """)).fetchall()
    return {r.player_id: dict(r._mapping) for r in rows}


def load_career_stats(conn, player_ids):
    """Load MLB pitching stats for workload/experience context.

    Returns dict keyed by player_id:
      - recent_gs / recent_ip: last CAREER_STATS_LOOKBACK_YEARS seasons (used for scoring)
      - career_gs_total: all-time GS count (used for inexperienced-starter flag only)
    """
    if not player_ids:
        return {}
    clause = ",".join(str(i) for i in player_ids)

    # Determine current year from the pitching stats table
    year_row = conn.execute(text(
        "SELECT MAX(year) FROM players_career_pitching_stats"
    )).fetchone()
    current_year = int(year_row[0]) if year_row and year_row[0] else 9999
    lookback_year = current_year - CAREER_STATS_LOOKBACK_YEARS

    rows = conn.execute(text(f"""
        SELECT player_id,
               SUM(CASE WHEN year >= {lookback_year} THEN gs ELSE 0 END) AS recent_gs,
               SUM(CASE WHEN year >= {lookback_year} THEN ip ELSE 0 END) AS recent_ip,
               SUM(gs) AS career_gs_total
        FROM players_career_pitching_stats
        WHERE player_id IN ({clause})
          AND split_id = {SPLIT_CAREER_OVERALL}
          AND level_id = {MLB_LEVEL_ID}
          AND league_id = {MLB_LEAGUE_ID}
        GROUP BY player_id
    """)).fetchall()
    return {
        r.player_id: dict(
            recent_gs=int(r.recent_gs or 0),
            recent_ip=float(r.recent_ip or 0.0),
            career_gs_total=int(r.career_gs_total or 0),
        )
        for r in rows
    }


def load_projected_rotation(conn, team_id):
    """Load OOTP's projected starting rotation for the team.

    Returns list of player_ids in slot order (starter_0 is the #1 starter).
    """
    row = conn.execute(text("""
        SELECT starter_0, starter_1, starter_2, starter_3, starter_4,
               starter_5, starter_6, starter_7
        FROM projected_starting_pitchers
        WHERE team_id = :tid
        LIMIT 1
    """), dict(tid=team_id)).fetchone()
    if not row:
        return []
    return [pid for pid in (
        row.starter_0, row.starter_1, row.starter_2, row.starter_3,
        row.starter_4, row.starter_5, row.starter_6, row.starter_7
    ) if pid is not None and pid > 0]


def load_injury_history(conn, player_ids):
    """Load recent IL stint counts from players_injury_history.

    Returns dict keyed by player_id: {il_stints, il_days}.
    Only counts stints from the last INJURY_LOOKBACK_YEARS seasons.
    """
    if not player_ids:
        return {}
    clause = ",".join(str(i) for i in player_ids)
    # players_injury_history has player_id and injury date fields
    # We use approximate season filtering by checking if start_date year is recent.
    # The table may use various date formats; fall back gracefully on error.
    try:
        rows = conn.execute(text(f"""
            SELECT player_id,
                   COUNT(*) AS il_stints,
                   SUM(COALESCE(days, 0)) AS il_days
            FROM players_injury_history
            WHERE player_id IN ({clause})
            GROUP BY player_id
        """)).fetchall()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return {}
    return {r.player_id: dict(il_stints=int(r.il_stints or 0), il_days=int(r.il_days or 0))
            for r in rows}


def load_player_names(conn, player_ids):
    """Load first_name + last_name for a set of player_ids (for OOTP diff labeling)."""
    if not player_ids:
        return {}
    clause = ",".join(str(i) for i in player_ids)
    rows = conn.execute(text(f"""
        SELECT player_id, first_name, last_name
        FROM players WHERE player_id IN ({clause})
    """)).fetchall()
    return {r.player_id: f"{r.first_name} {r.last_name}" for r in rows}


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


def _fip_score(fip):
    """Convert FIP to 0-100 score (lower FIP = higher score)."""
    if fip is None:
        return 50.0
    return _clamp((FIP_POOR - fip) / (FIP_POOR - FIP_ELITE) * 100, 0, 100)


def _xfip_score(xfip):
    """Convert xFIP to 0-100 score (lower xFIP = higher score)."""
    if xfip is None:
        return 50.0
    return _clamp((XFIP_POOR - xfip) / (XFIP_POOR - XFIP_ELITE) * 100, 0, 100)


def _career_gs_score(career_gs):
    """Convert career GS to 0-100 workload score."""
    return _clamp(career_gs / CAREER_GS_TARGET * 100, 0, 100)


def _stamina_score(stamina):
    """Convert stamina (20-80 scale) to 0-100 innings-durability score.

    Stamina >= STAMINA_FULL (70) → 100; <= STAMINA_POOR (35) → 0.
    """
    if stamina is None:
        return 50.0
    return _clamp((stamina - STAMINA_POOR) / (STAMINA_FULL - STAMINA_POOR) * 100, 0, 100)


def score_starter(pitcher, mode, stats, ratings, career):
    """Compute a 0-100 composite score for a starter under the given mode.

    pitcher: base dict from load_starter_pool
    mode: one of MODES
    stats: pitcher_advanced_stats dict (may be empty)
    ratings: player_ratings dict (may be empty)
    career: career stats dict (may be empty)
    """
    weights = MODE_WEIGHTS.get(mode, MODE_WEIGHTS["balanced"])

    fip  = stats.get("fip")
    xfip = stats.get("xfip")
    rating_now  = ratings.get("rating_now") or 50.0
    durability  = ratings.get("rating_durability") or 50.0
    potential   = ratings.get("rating_potential") or 50.0
    recent_gs   = career.get("recent_gs") or 0
    stamina     = pitcher.get("stamina")   # from players_pitching, loaded in pool query

    components = {
        "rating_now":      rating_now,
        "fip_score":       _fip_score(fip),
        "xfip_score":      _xfip_score(xfip),
        "durability":      durability,
        "stamina_score":   _stamina_score(stamina),
        "potential":       potential,
        "career_gs_score": _career_gs_score(recent_gs),
    }

    score = sum(weights.get(k, 0.0) * v for k, v in components.items())
    return round(score, 2)


def score_opener(reliever, bulk_throws, stats, ratings):
    """Compute a 0-100 score for a reliever as an opener candidate.

    Favors high K%, low WHIP/FIP, and opposite hand to the bulk pitcher.
    """
    k_pct  = stats.get("k_pct")
    whip   = stats.get("whip")
    fip    = stats.get("fip")
    ip     = float(stats.get("ip") or 0.0)

    if ip < OPENER_MIN_IP:
        return 0.0   # not enough work to evaluate

    # K% component (0-100)
    if k_pct is not None:
        k_score = _clamp((k_pct - OPENER_K_PCT_POOR) / (OPENER_K_PCT_GOOD - OPENER_K_PCT_POOR) * 100, 0, 100)
    else:
        k_score = 50.0

    # WHIP component (0-100, lower WHIP = higher score)
    if whip is not None:
        whip_score = _clamp((OPENER_WHIP_POOR - whip) / (OPENER_WHIP_POOR - OPENER_WHIP_GOOD) * 100, 0, 100)
    else:
        whip_score = 50.0

    # FIP component
    fip_score = _fip_score(fip)

    # Base score
    base = 0.40 * k_score + 0.30 * whip_score + 0.30 * fip_score

    # rating_now enrichment (optional)
    rating_now = ratings.get("rating_now")
    if rating_now is not None:
        base = base * 0.7 + rating_now * 0.3

    # Opposite-hand bonus
    opener_throws = reliever.get("throws")
    if opener_throws and bulk_throws and opener_throws != bulk_throws:
        base += OPENER_OPPOSITE_HAND_BONUS

    return round(_clamp(base, 0, 100), 2)


# ---------------------------------------------------------------------------
# Rotation building
# ---------------------------------------------------------------------------

def _match_name(name_query, pitchers):
    """Return the first pitcher whose full name contains name_query (case-insensitive).

    Tries exact full-name match first, then last-name-only, then substring.
    Returns the matching pitcher dict or None.
    """
    q = name_query.strip().lower()
    for p in pitchers:
        full = f"{p.get('first_name','')} {p.get('last_name','')}".strip().lower()
        if full == q:
            return p
    for p in pitchers:
        if p.get("last_name", "").lower() == q:
            return p
    for p in pitchers:
        full = f"{p.get('first_name','')} {p.get('last_name','')}".strip().lower()
        if q in full:
            return p
    return None


def build_rotation(starters, n_slots, forced_names=None):
    """Return the top n_slots starters by composite score, with the rest as depth.

    forced_names: list of name strings — these pitchers are guaranteed a rotation slot
    regardless of score. Forced pitchers still occupy the slot order they'd earn by score
    among themselves; remaining slots are filled from the rest of the pool.
    """
    forced_names = [n.strip().lower() for n in (forced_names or []) if n.strip()]

    forced, free = [], []
    for p in starters:
        full = f"{p.get('first_name','')} {p.get('last_name','')}".strip().lower()
        if any(fn in full or full in fn for fn in forced_names):
            p = dict(p, _forced=True)
            forced.append(p)
        else:
            free.append(p)

    forced.sort(key=lambda s: s["score"], reverse=True)
    free.sort(key=lambda s: s["score"], reverse=True)

    # Forced pitchers are guaranteed a slot; displace the lowest-scoring free pitchers.
    n_forced = min(len(forced), n_slots)
    n_free   = n_slots - n_forced

    # Combine forced + top-free and re-sort by score so slot order reflects quality.
    rotation = sorted(forced[:n_forced] + free[:n_free], key=lambda s: s["score"], reverse=True)
    depth    = free[n_free:] + forced[n_forced:]
    return rotation, depth


def pick_opener_slots(rotation, n):
    """Choose which N rotation slots (0-indexed) should use opener coverage.

    Heuristic priority (from SKILLS_ROADMAP):
    1. Slots with the worst FIP (biggest need for an opening-inning advantage)
    2. Slots with largest FIP-xFIP gap (luck regression risk)
    3. Slots with the best platoon-flip opportunity (bulk RHP → LHP opener, or reverse)

    Returns a list of slot indices (0-indexed into rotation list).
    """
    if n <= 0 or not rotation:
        return []
    n = min(n, len(rotation))

    def slot_priority(item):
        idx, starter = item
        stats = starter.get("_stats") or {}
        fip  = stats.get("fip") or 4.5
        xfip = stats.get("xfip") or fip
        fip_gap = fip - xfip   # positive = FIP < xFIP (pitcher may be better than FIP says → less benefit)
                                # negative = FIP > xFIP (regression risk → more benefit from opener)
        # Primary: worst FIP (highest = most room to benefit)
        # Secondary: largest FIP-xFIP regression gap (FIP > xFIP → regression risk → prioritize)
        return (fip, max(0, -(fip_gap)))   # highest FIP first; regression gap as tiebreaker

    candidates = sorted(enumerate(rotation), key=slot_priority, reverse=True)
    return sorted(idx for idx, _ in candidates[:n])


def pair_openers(opener_slot_indices, rotation, relief_corps, all_relief_stats, all_relief_ratings):
    """For each chosen slot, score all relief candidates and pick the best opener.

    Returns list of dicts: {slot, bulk, opener, reason}
    bulk and opener are pitcher dicts with added _stats/_ratings.

    Tries to avoid reusing the same opener on back-to-back days.
    """
    pairings = []
    used_opener_ids = set()

    for slot_idx in opener_slot_indices:
        bulk = rotation[slot_idx]
        bulk_throws = bulk.get("throws")

        # Score all relievers for this slot
        scored = []
        for rel in relief_corps:
            pid = rel["player_id"]
            rel_stats   = all_relief_stats.get(pid) or {}
            rel_ratings = all_relief_ratings.get(pid) or {}
            s = score_opener(rel, bulk_throws, rel_stats, rel_ratings)
            scored.append((s, pid, rel, rel_stats))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Prefer not to reuse the same opener back-to-back if alternatives exist
        viable = [(s, pid, rel, rel_stats) for s, pid, rel, rel_stats in scored
                  if s > 0 and pid not in used_opener_ids]
        if not viable:
            viable = [(s, pid, rel, rel_stats) for s, pid, rel, rel_stats in scored if s > 0]

        if not viable:
            pairings.append(dict(slot=slot_idx, bulk=bulk, opener=None, reason="No viable opener found"))
            continue

        best_score, best_pid, best_opener, best_stats = viable[0]
        used_opener_ids.add(best_pid)

        # Build reason string
        bulk_name    = f"{bulk.get('first_name','')} {bulk.get('last_name','')}".strip()
        opener_name  = f"{best_opener.get('first_name','')} {best_opener.get('last_name','')}".strip()
        opener_hand  = THROWS_LABEL.get(best_opener.get("throws"), "?")
        bulk_hand    = THROWS_LABEL.get(bulk_throws, "?")
        reason_parts = []
        if opener_hand != bulk_hand:
            reason_parts.append(f"{opener_hand}HP opener flips matchup vs {bulk_hand}HP bulk")
        fip = best_stats.get("fip")
        if fip is not None:
            reason_parts.append(f"FIP {fip:.2f}")
        k_pct = best_stats.get("k_pct")
        if k_pct is not None:
            reason_parts.append(f"K% {k_pct:.1%}")
        reason = "; ".join(reason_parts) if reason_parts else "Best available opener"

        pairings.append(dict(
            slot=slot_idx,
            bulk=bulk,
            opener=dict(**best_opener, _stats=best_stats),
            reason=reason,
            opener_score=best_score,
        ))

    return pairings


# ---------------------------------------------------------------------------
# Vulnerability flags
# ---------------------------------------------------------------------------

def vulnerability_flags(pitcher, stats, ratings, career, slot_idx):
    """Return a list of human-readable warning strings for a starter.

    slot_idx is 0-based (0 = ace slot).
    """
    flags = []

    fip  = stats.get("fip")
    xfip = stats.get("xfip")
    ip   = float(stats.get("ip") or 0.0)
    career_gs_total = career.get("career_gs_total") or 0

    flag_injury  = ratings.get("flag_injury_risk")
    confidence   = ratings.get("confidence")
    stamina      = pitcher.get("stamina")

    # Low stamina warning for SP-role pitchers
    if stamina is not None and stamina < 50:
        flags.append(f"Low stamina ({stamina}) — may struggle to go deep into games")

    # FIP luck / regression risk
    if fip is not None and xfip is not None:
        gap = xfip - fip
        if gap >= FIP_XFIP_LUCK_THRESHOLD:
            flags.append(f"Regression risk: FIP {fip:.2f} is {gap:.2f} below xFIP {xfip:.2f}")

    # Low current-season sample
    if ip < LOW_SAMPLE_IP:
        flags.append(f"Low sample: only {ip:.0f} IP this season")

    # Injury risk flag
    if flag_injury:
        flags.append("Injury risk flag (player_ratings)")

    # Low career GS at non-ace slots (all-time count — intentionally not windowed)
    if slot_idx >= 2 and career_gs_total < LOW_CAREER_GS_NON_ACE:
        flags.append(f"Inexperienced starter: only {career_gs_total} career MLB GS at #{slot_idx + 1} slot")

    # Low confidence (stats-only rating — no scouted current ratings)
    if confidence is not None and confidence < 0.5:
        flags.append(f"Low confidence rating ({confidence:.2f}) — stats-only, no scouted current ratings")

    return flags


# ---------------------------------------------------------------------------
# OOTP projection diff
# ---------------------------------------------------------------------------

def diff_ootp_projection(rotation, ootp_projected_ids, all_names):
    """Compare recommended rotation order vs OOTP's projected_starting_pitchers.

    Returns list of dicts: {slot, model_name, ootp_name, move_str, same}
    slot is 1-based for display.
    """
    result = []
    for slot_idx, pitcher in enumerate(rotation):
        slot_display = slot_idx + 1
        model_pid  = pitcher["player_id"]
        model_name = all_names.get(model_pid, f"#{model_pid}")

        if slot_idx < len(ootp_projected_ids):
            ootp_pid  = ootp_projected_ids[slot_idx]
            ootp_name = all_names.get(ootp_pid, f"#{ootp_pid}")
            same      = model_pid == ootp_pid
            if same:
                move_str = "—"
            else:
                # Find where OOTP has the model pitcher
                try:
                    ootp_slot = ootp_projected_ids.index(model_pid) + 1
                    if ootp_slot < slot_display:
                        move_str = f"↓ OOTP has {model_name} at #{ootp_slot}"
                    else:
                        move_str = f"↑ OOTP has {model_name} at #{ootp_slot}"
                except ValueError:
                    move_str = f"{model_name} not in OOTP rotation"
        else:
            ootp_name = "—"
            same      = False
            move_str  = "Extra slot (six-man)"

        result.append(dict(
            slot=slot_display,
            model_name=model_name,
            ootp_name=ootp_name,
            move_str=move_str,
            same=same,
        ))
    return result


# ---------------------------------------------------------------------------
# Main query orchestrator
# ---------------------------------------------------------------------------

def query_rotation(save_name, team_query=None, mode="balanced",
                   n_openers=0, six_man=False, excluded_names=None,
                   forced_names=None):
    """Assemble all rotation data and return a data_dict, or None on error.

    Does not touch HTML or the cache — pure data assembly.

    Returns dict with keys:
      _team_id, _team_name, _team_abbr, _mode, _n_starters,
      _rotation, _depth, _opener_pairings, _ootp_diff,
      _ootp_projected_ids, _six_man, _n_openers
    """
    if mode not in ("balanced", "ace-first", "innings", "six-man"):
        mode = "balanced"

    excluded_names = excluded_names or []
    n_starters = SIX_MAN_SLOTS if six_man or mode == "six-man" else FIVE_MAN_SLOTS

    engine = get_engine(save_name)
    with engine.connect() as conn:
        team_id, team_name, team_abbr = resolve_team(conn, team_query)
        if not team_id:
            return None

        starters_raw  = load_starter_pool(conn, team_id)
        relievers_raw = load_relief_corps(conn, team_id)

        # Apply exclusions — use _match_name so "without Skubal" matches "Tarik Skubal"
        excluded_ids = set()
        for excl_query in (excluded_names or []):
            match = _match_name(excl_query, starters_raw)
            if match:
                excluded_ids.add(match["player_id"])
        starters_raw = [p for p in starters_raw if p["player_id"] not in excluded_ids]
        if not starters_raw:
            return None

        all_pitcher_ids = list({p["player_id"] for p in starters_raw + relievers_raw})
        starter_ids     = [p["player_id"] for p in starters_raw]
        reliever_ids    = [p["player_id"] for p in relievers_raw]

        all_stats   = load_pitcher_stats(conn, all_pitcher_ids)
        all_ratings = load_pitcher_ratings(conn, all_pitcher_ids)
        all_career  = load_career_stats(conn, all_pitcher_ids)
        ootp_proj   = load_projected_rotation(conn, team_id)

        # For OOTP diff name lookup, include projected ids not already in pool
        extra_ids = [pid for pid in ootp_proj if pid not in {p["player_id"] for p in starters_raw}]
        extra_names = load_player_names(conn, extra_ids) if extra_ids else {}
        all_names   = load_player_names(conn, all_pitcher_ids)
        all_names.update(extra_names)

    # Enrich starters with stats, ratings, career, score
    for p in starters_raw:
        pid = p["player_id"]
        p["_stats"]   = all_stats.get(pid) or {}
        p["_ratings"] = all_ratings.get(pid) or {}
        p["_career"]  = all_career.get(pid) or {}
        p["score"]    = score_starter(p, mode, p["_stats"], p["_ratings"], p["_career"])
        p["throws_label"] = THROWS_LABEL.get(p.get("throws"), "?")

    # Build rotation and depth
    rotation, depth = build_rotation(starters_raw, n_starters, forced_names=forced_names)

    # Filter depth to only those with at least DEPTH_MIN_GS career GS (all-time) or current GS
    depth = [
        p for p in depth
        if (p["_career"].get("career_gs_total") or 0) >= DEPTH_MIN_GS
           or (p["_stats"].get("gs") or 0) >= DEPTH_MIN_GS
    ]

    # Attach vulnerability flags to each rotation slot
    for slot_idx, pitcher in enumerate(rotation):
        pitcher["_flags"] = vulnerability_flags(
            pitcher, pitcher["_stats"], pitcher["_ratings"],
            pitcher["_career"], slot_idx
        )

    # Opener pairings
    opener_pairings = []
    if n_openers > 0 and relievers_raw:
        opener_slot_indices = pick_opener_slots(rotation, n_openers)
        relief_stats   = {pid: all_stats.get(pid) or {} for pid in reliever_ids}
        relief_ratings = {pid: all_ratings.get(pid) or {} for pid in reliever_ids}
        opener_pairings = pair_openers(
            opener_slot_indices, rotation, relievers_raw, relief_stats, relief_ratings
        )

    # OOTP diff
    ootp_diff = diff_ootp_projection(rotation, ootp_proj, all_names)

    return dict(
        _team_id=team_id,
        _team_name=team_name,
        _team_abbr=team_abbr,
        _mode=mode,
        _n_starters=n_starters,
        _rotation=rotation,
        _depth=depth,
        _opener_pairings=opener_pairings,
        _ootp_diff=ootp_diff,
        _ootp_projected_ids=ootp_proj,
        _six_man=six_man or mode == "six-man",
        _n_openers=n_openers,
        _all_names=all_names,
    )
