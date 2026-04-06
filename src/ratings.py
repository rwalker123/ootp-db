#!/usr/bin/env python3
"""Player rating system for OOTP Baseball.

Computes composite 0-100 ratings for all MLB players by combining:
- Advanced stats (from batter/pitcher_advanced_stats tables)
- OOTP ratings (potential, fielding, running)
- Personality traits (work ethic, intelligence, leadership)
- Injury proneness
- Career trajectory trends

Run after analytics.py:
    python src/ratings.py My-Save-2026
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from config import (
    CATCHER_MIN_CS_ATTEMPTS,
    CEILING_GAP_THRESHOLD,
    DEFENSE_BAT_FIRST_MULTIPLIER,
    DEFENSE_PREMIUM_MULTIPLIER,
    FIELDING_MIN_GAMES,
    INJURY_OVERALL_DEDUCTION,
    INJURY_PRONE_THRESHOLD,
    IP_REGRESSION_THRESHOLD,
    LEADER_OVERALL_BONUS,
    LEADER_THRESHOLD,
    OFFENSE_WRC_WEIGHT,
    OFFENSE_XWOBA_WEIGHT,
    OOTP_MAX_BLEND_WEIGHT,
    PA_REGRESSION_THRESHOLD,
    REGRESSION_EXPONENT,
    RELIEVER_G_TARGET,
    STARTER_IP_TARGET,
    STARTER_MIN_GS,
    WRC_CAP_HEADROOM,
)
from ootp_db_constants import (
    MLB_LEAGUE_ID, MLB_LEVEL_ID,
    POS_PITCHER, POS_CATCHER,
    POS_FIRST_BASE as POS_1B,
    POS_SECOND_BASE as POS_2B,
    POS_THIRD_BASE as POS_3B,
    POS_SHORTSTOP as POS_SS,
    POS_LEFT_FIELD as POS_LF,
    POS_CENTER_FIELD as POS_CF,
    POS_RIGHT_FIELD as POS_RF,
    SPLIT_CAREER_OVERALL, SPLIT_TEAM_PITCHING_OVERALL,
)
from report_write import write_report_html, report_filename
from shared_css import db_name_from_save, get_engine, get_report_css, get_reports_dir
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAST_IMPORT_PATH = PROJECT_ROOT / ".last_import"


def _rating_slug(first_name, last_name, player_id, focus_modifiers=None):
    slug = f"{first_name.lower()}_{last_name.lower()}_{player_id}"
    if focus_modifiers:
        mod_str = "_".join(sorted(m.lower().strip(",") for m in focus_modifiers))
        slug = f"{slug}_{mod_str}"
    return slug


def find_existing_rating_report(save_name, first_name, last_name, engine, focus_modifiers=None):
    """Return the report path if it exists and is newer than the last import.

    Returns the path string if the report is current, or None if it needs
    to be (re)generated.
    """
    from sqlalchemy import text as sa_text

    with engine.connect() as conn:
        row = conn.execute(
            sa_text("SELECT player_id FROM players WHERE first_name = :f AND last_name = :l"),
            dict(f=first_name, l=last_name),
        ).fetchone()
        if not row:
            return None
        player_id = row[0]

    args_key = {"focus": sorted(m.lower().strip(",") for m in focus_modifiers) if focus_modifiers else []}
    report_path = PROJECT_ROOT / "reports" / save_name / "ratings" / report_filename(f"rating_{player_id}", args_key)

    if not report_path.exists():
        return None

    if not LAST_IMPORT_PATH.exists():
        return str(report_path)

    report_mtime = datetime.fromtimestamp(report_path.stat().st_mtime)
    import_time = datetime.fromisoformat(LAST_IMPORT_PATH.read_text().strip())

    if report_mtime >= import_time:
        return str(report_path)

    return None


def get_last_import_time():
    if LAST_IMPORT_PATH.exists():
        return LAST_IMPORT_PATH.read_text().strip()
    return None


def query_player_rating(save_name, first_name, last_name, focus_modifiers=None):
    """Query and compute all data needed for a player rating report.

    Returns a complete dict with all values needed by generate_rating_report
    and MCP tools, or None if the player is not found.
    Does NOT perform a cache check.
    """
    engine = get_engine(save_name)

    with engine.connect() as conn:
        from sqlalchemy import text as sa_text

        row = conn.execute(sa_text(
            "SELECT pr.player_id, pr.first_name, pr.last_name, pr.team_abbr, pr.position, "
            "pr.age, pr.oa, pr.pot, pr.player_type, pr.rating_overall, "
            "pr.rating_offense, pr.rating_contact_quality, pr.rating_discipline, "
            "pr.rating_defense, pr.rating_potential, pr.rating_durability, "
            "pr.rating_development, pr.rating_clubhouse, pr.rating_baserunning, "
            "pr.flag_injury_risk, pr.flag_leader, pr.flag_high_ceiling, "
            "pr.wrc_plus, pr.war, pr.prone_overall, "
            "p.bats, p.throws, "
            "p.prone_leg, p.prone_back, p.prone_arm, "
            "p.personality_work_ethic, p.personality_intelligence, p.personality_leader, "
            "p.personality_greed, p.personality_loyalty, p.personality_play_for_winner "
            "FROM player_ratings pr "
            "JOIN players p ON p.player_id = pr.player_id "
            "WHERE pr.first_name = :first AND pr.last_name = :last"
        ), dict(first=first_name, last=last_name)).fetchone()

        if not row:
            return None

        (player_id, first, last, team_abbr, position, age, oa, pot, player_type,
         rating_overall, r_offense, r_contact, r_discipline, r_defense, r_potential,
         r_durability, r_development, r_clubhouse, r_baserunning,
         flag_injury, flag_leader_val, flag_ceiling,
         wrc_plus_or_fip, war, prone_overall,
         bats, throws, prone_leg, prone_back, prone_arm,
         work_ethic, intelligence, leader, greed, loyalty, play_for_winner) = row

        # Position rank
        rank_row = conn.execute(sa_text(
            "SELECT COUNT(*)+1 FROM player_ratings WHERE position = :pos AND rating_overall > :r"
        ), dict(pos=position, r=rating_overall)).fetchone()
        total_row = conn.execute(sa_text(
            "SELECT COUNT(*) FROM player_ratings WHERE position = :pos"
        ), dict(pos=position)).fetchone()
        rank = int(rank_row[0])
        rank_total = int(total_row[0])

    # Determine weights
    pos_map = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
    bats_map = {1: "R", 2: "L", 3: "S"}
    throws_map = {1: "R", 2: "L"}
    pos_name = pos_map.get(position, str(position))
    bats_str = bats_map.get(bats, "?")
    throws_str = throws_map.get(throws, "?")

    is_pitcher = (player_type == "pitcher")

    if is_pitcher:
        base_weights = dict(
            offense=0.30, contact_quality=0.15, discipline=0.15,
            defense=0.10, potential=0.15, durability=0.05,
            development=0.03, clubhouse=0.02, baserunning=0.05,
        )
        component_labels = [
            ("offense", "Run Prevention"),
            ("contact_quality", "Contact Suppression"),
            ("discipline", "Dominance"),
            ("defense", "Command"),
            ("potential", "Potential"),
            ("durability", "Durability"),
            ("development", "Development"),
            ("clubhouse", "Clubhouse"),
            ("baserunning", "Role Value"),
        ]
    else:
        base_weights = dict(
            offense=0.30, contact_quality=0.15, discipline=0.10,
            defense=0.15, potential=0.15, durability=0.05,
            development=0.03, clubhouse=0.02, baserunning=0.05,
        )
        component_labels = [
            ("offense", "Offense"),
            ("contact_quality", "Contact Quality"),
            ("discipline", "Discipline"),
            ("defense", "Defense"),
            ("potential", "Potential"),
            ("durability", "Durability"),
            ("development", "Development"),
            ("clubhouse", "Clubhouse"),
            ("baserunning", "Baserunning"),
        ]

    scores = dict(
        offense=r_offense, contact_quality=r_contact, discipline=r_discipline,
        defense=r_defense, potential=r_potential, durability=r_durability,
        development=r_development, clubhouse=r_clubhouse, baserunning=r_baserunning,
    )

    # Map position keywords to position numbers so we can recompute defense
    # at the correct position when a position modifier is given.
    POS_KEYWORD_MAP = {
        "first": POS_1B, "1b": POS_1B,
        "second": POS_2B, "2b": POS_2B,
        "third": POS_3B, "3b": POS_3B,
        "shortstop": POS_SS, "ss": POS_SS,
        "catcher": POS_CATCHER, "catching": POS_CATCHER,
        "left": POS_LF, "lf": POS_LF,
        "center": POS_CF, "cf": POS_CF,
        "right": POS_RF, "rf": POS_RF,
    }

    if focus_modifiers and not is_pitcher:
        target_pos = next(
            (POS_KEYWORD_MAP[m.lower().strip(",")] for m in focus_modifiers
             if m.lower().strip(",") in POS_KEYWORD_MAP),
            None
        )
        if target_pos is not None:
            # Recompute defense for the target position.
            # Show the RAW fielding score (no positional multiplier) in the breakdown
            # so users see actual fielding quality at that position.
            # Move the multiplier into base_weights["defense"] instead so the
            # composite rating calculation is unchanged.
            with engine.connect() as conn:
                from sqlalchemy import text as sa_text
                field_row = conn.execute(sa_text(
                    "SELECT * FROM players_fielding WHERE player_id = :pid"
                ), dict(pid=player_id)).fetchone()
                if field_row:
                    field_dict = dict(zip(field_row._mapping.keys(), field_row))
                    pos_col = POS_FIELD_COL.get(target_pos)
                    if pos_col and pos_col in field_dict:
                        field_rating = field_dict.get(pos_col) or 0
                        raw_score = min(100.0, max(0.0, (field_rating - 20) / 60 * 100)) if field_rating > 0 else 50.0
                        scores["defense"] = raw_score
                        # Shift positional multiplier into the weight
                        if target_pos in PREMIUM_DEFENSE_POS:
                            base_weights["defense"] = min(base_weights["defense"] * DEFENSE_PREMIUM_MULTIPLIER, 0.95)
                        elif target_pos in LOW_DEFENSE_POS:
                            base_weights["defense"] *= DEFENSE_BAT_FIRST_MULTIPLIER

    # Focus modifier keywords → (component, boost_amount)
    # Standard boost: 0.15 | Heavier bat-first positions: 0.22 | DH (pure hitter): 0.35
    focus_map = {
        "defense": ("defense", 0.15), "fielding": ("defense", 0.15),
        "power": ("contact_quality", 0.15), "contact": ("contact_quality", 0.15),
        "upside": ("potential", 0.15), "potential": ("potential", 0.15),
        "durability": ("durability", 0.15),
        "discipline": ("discipline", 0.15),
        "offense": ("offense", 0.15), "hitting": ("offense", 0.15),
        "speed": ("baserunning", 0.15), "baserunning": ("baserunning", 0.15),
        "development": ("development", 0.15), "work": ("development", 0.15), "ethic": ("development", 0.15),
        "clubhouse": ("clubhouse", 0.15), "leadership": ("clubhouse", 0.15),
        "dominance": ("discipline", 0.15), "strikeouts": ("discipline", 0.15),
        "command": ("defense", 0.15), "control": ("defense", 0.15),
        # Position names — boost reflects positional value tiers
        # Heavy bat emphasis: 1B, LF
        "first": ("offense", 0.22), "1b": ("offense", 0.22),
        "left": ("offense", 0.22), "lf": ("offense", 0.22),
        # Standard bat-first: 3B, RF, generic OF
        "third": ("offense", 0.15), "3b": ("offense", 0.15),
        "right": ("offense", 0.15), "rf": ("offense", 0.15),
        "outfield": ("offense", 0.15), "of": ("offense", 0.15),
        # DH: pure hitter, defense not a factor
        "dh": ("offense", 0.35), "designated": ("offense", 0.35),
        # Defense-first: SS, C
        "shortstop": ("defense", 0.15), "ss": ("defense", 0.15),
        "catcher": ("defense", 0.15), "catching": ("defense", 0.15),
        # Balanced, defense slightly favored: 2B, CF
        "second": ("defense", 0.15), "2b": ("defense", 0.15),
        "center": ("defense", 0.15), "cf": ("defense", 0.15),
        # "base", "field", "hitter" are filler words — not mapped
    }

    weights = dict(base_weights)
    adjusted = False
    adj_rating = rating_overall

    if focus_modifiers:
        for mod in focus_modifiers:
            mod_lower = mod.lower().strip(",")
            entry = focus_map.get(mod_lower)
            if entry:
                component, boost = entry
                if component in weights:
                    adjusted = True
                    others = [k for k in weights if k != component]
                    total_others = sum(weights[k] for k in others)
                    if total_others > 0:
                        for k in others:
                            weights[k] -= boost * (weights[k] / total_others)
                    weights[component] += boost

        if adjusted:
            adj_rating = sum(scores[k] * weights[k] for k in weights)
            adj_rating = float(max(0, min(100, adj_rating)))

    def lg(score):
        return letter_grade(score)

    final_rating = adj_rating if adjusted else rating_overall

    # Durability labels
    def injury_label(val):
        if val is None:
            return "Unknown"
        v = int(val)
        if v <= 25:
            return "Iron Man"
        if v <= 75:
            return "Durable"
        if v <= 125:
            return "Normal"
        if v <= 174:
            return "Fragile"
        return "Wrecked"

    def injury_color(val):
        if val is None:
            return "#888"
        v = int(val)
        if v <= 75:
            return "#1a7a1a"
        if v <= 125:
            return "#cc7700"
        return "#cc2222"

    # Personality labels
    def trait_label(val):
        if val is None:
            return "Unknown"
        v = int(val)
        if v <= 50:
            return "Poor"
        if v <= 100:
            return "Below Avg"
        if v <= 130:
            return "Average"
        if v <= 160:
            return "Good"
        return "Elite"

    def trait_color(val, invert=False):
        if val is None:
            return "#888"
        v = int(val)
        if invert:
            if v >= 161:
                return "#cc2222"
            if v >= 131:
                return "#cc7700"
            return "#1a7a1a"
        if v >= 161:
            return "#1a7a1a"
        if v >= 131:
            return "#4a9a2a"
        if v >= 101:
            return "#888"
        return "#cc7700"

    def bar_html(score):
        w = int(max(0, min(100, score)))
        cls = "bar-green" if score >= 70 else "bar-yellow" if score >= 40 else "bar-red"
        return f'<div class="bar-bg"><div class="bar-fill {cls}" style="width:{w}%"></div></div>'

    def _rating_bg(score):
        grade = lg(score)
        if grade in ("A+", "A"):
            return "#1a7a1a"
        if grade in ("B+", "B"):
            return "#2266cc"
        if grade in ("C+", "C"):
            return "#cc7700"
        return "#cc2222"

    def grade_badge(score):
        grade = lg(score)
        bg = _rating_bg(score)
        return (f'<span style="background:{bg};color:white;border-radius:4px;'
                f'font-weight:bold;font-size:13px;padding:2px 8px">{grade} {score:.1f}</span>')

    oa_disp = int(oa) if oa is not None else 0
    pot_disp = int(pot) if pot is not None else 0
    age_disp = int(age) if age is not None else 0
    prone_overall_v = int(prone_overall) if prone_overall is not None else 100
    prone_leg_v = int(prone_leg) if prone_leg is not None else 100
    prone_back_v = int(prone_back) if prone_back is not None else 100
    prone_arm_v = int(prone_arm) if prone_arm is not None else 100
    we_v = int(work_ethic) if work_ethic is not None else 100
    iq_v = int(intelligence) if intelligence is not None else 100
    leader_v = int(leader) if leader is not None else 100
    greed_v = int(greed) if greed is not None else 100
    loyalty_v = int(loyalty) if loyalty is not None else 100
    pfw_v = int(play_for_winner) if play_for_winner is not None else 100

    key_stat_label = "FIP" if is_pitcher else "wRC+"
    key_stat_val = f"{wrc_plus_or_fip:.2f}" if is_pitcher else str(int(wrc_plus_or_fip)) if wrc_plus_or_fip is not None else "—"
    war_val = f"{float(war):.1f}" if war is not None else "—"

    return dict(
        player_id=player_id,
        first_name=first,
        last_name=last,
        team_abbr=team_abbr,
        position=position,
        pos_name=pos_name,
        age=age_disp,
        oa=oa_disp,
        pot=pot_disp,
        player_type=player_type,
        is_pitcher=is_pitcher,
        rating_overall=rating_overall,
        scores=scores,
        weights=weights,
        component_labels=component_labels,
        adjusted=adjusted,
        adj_rating=adj_rating,
        final_rating=final_rating,
        rank=rank,
        rank_total=rank_total,
        bats_str=bats_str,
        throws_str=throws_str,
        oa_disp=oa_disp,
        pot_disp=pot_disp,
        age_disp=age_disp,
        prone_overall_v=prone_overall_v,
        prone_leg_v=prone_leg_v,
        prone_back_v=prone_back_v,
        prone_arm_v=prone_arm_v,
        we_v=we_v,
        iq_v=iq_v,
        leader_v=leader_v,
        greed_v=greed_v,
        loyalty_v=loyalty_v,
        pfw_v=pfw_v,
        flag_injury_risk=bool(flag_injury),
        flag_leader=bool(flag_leader_val),
        flag_high_ceiling=bool(flag_ceiling),
        key_stat_label=key_stat_label,
        key_stat_val=key_stat_val,
        war_val=war_val,
        wrc_plus=None if is_pitcher else wrc_plus_or_fip,
        fip=wrc_plus_or_fip if is_pitcher else None,
        war=war,
        focus_modifiers=focus_modifiers,
    )


def generate_rating_report(save_name, first_name, last_name, focus_modifiers=None):
    """Generate (or return cached) a player rating HTML report.

    focus_modifiers: list of strings like ["defense", "power"] or None.

    Returns (path_str, data_dict) where data_dict is None on a cache hit.
    """
    engine = get_engine(save_name)

    existing = find_existing_rating_report(save_name, first_name, last_name, engine, focus_modifiers)
    if existing:
        return existing, None

    last_import = get_last_import_time()
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    data = query_player_rating(save_name, first_name, last_name, focus_modifiers)
    if data is None:
        print(f"Player not found: {first_name} {last_name}")
        sys.exit(1)

    # Extract all values from data dict for HTML generation
    player_id = data["player_id"]
    first = data["first_name"]
    last = data["last_name"]
    team_abbr = data["team_abbr"]
    pos_name = data["pos_name"]
    age_disp = data["age_disp"]
    oa_disp = data["oa_disp"]
    pot_disp = data["pot_disp"]
    player_type = data["player_type"]
    is_pitcher = data["is_pitcher"]
    rating_overall = data["rating_overall"]
    scores = data["scores"]
    weights = data["weights"]
    component_labels = data["component_labels"]
    adjusted = data["adjusted"]
    adj_rating = data["adj_rating"]
    final_rating = data["final_rating"]
    rank = data["rank"]
    rank_total = data["rank_total"]
    bats_str = data["bats_str"]
    throws_str = data["throws_str"]
    prone_overall_v = data["prone_overall_v"]
    prone_leg_v = data["prone_leg_v"]
    prone_back_v = data["prone_back_v"]
    prone_arm_v = data["prone_arm_v"]
    we_v = data["we_v"]
    iq_v = data["iq_v"]
    leader_v = data["leader_v"]
    greed_v = data["greed_v"]
    loyalty_v = data["loyalty_v"]
    pfw_v = data["pfw_v"]
    flag_injury = data["flag_injury_risk"]
    flag_leader_val = data["flag_leader"]
    flag_ceiling = data["flag_high_ceiling"]
    key_stat_label = data["key_stat_label"]
    key_stat_val = data["key_stat_val"]
    war_val = data["war_val"]

    def lg(score):
        return letter_grade(score)

    def bar_html(score):
        w = int(max(0, min(100, score)))
        cls = "bar-green" if score >= 70 else "bar-yellow" if score >= 40 else "bar-red"
        return f'<div class="bar-bg"><div class="bar-fill {cls}" style="width:{w}%"></div></div>'

    def injury_label(val):
        if val is None:
            return "Unknown"
        v = int(val)
        if v <= 25:
            return "Iron Man"
        if v <= 75:
            return "Durable"
        if v <= 125:
            return "Normal"
        if v <= 174:
            return "Fragile"
        return "Wrecked"

    def injury_color(val):
        if val is None:
            return "#888"
        v = int(val)
        if v <= 75:
            return "#1a7a1a"
        if v <= 125:
            return "#cc7700"
        return "#cc2222"

    def trait_label(val):
        if val is None:
            return "Unknown"
        v = int(val)
        if v <= 50:
            return "Poor"
        if v <= 100:
            return "Below Avg"
        if v <= 130:
            return "Average"
        if v <= 160:
            return "Good"
        return "Elite"

    def trait_color(val, invert=False):
        if val is None:
            return "#888"
        v = int(val)
        if invert:
            if v >= 161:
                return "#cc2222"
            if v >= 131:
                return "#cc7700"
            return "#1a7a1a"
        if v >= 161:
            return "#1a7a1a"
        if v >= 131:
            return "#4a9a2a"
        if v >= 101:
            return "#888"
        return "#cc7700"

    adj_note = ""
    if adjusted:
        adj_note = (f'<div class="section"><div class="callout">'
                    f'Focus: <b>{", ".join(focus_modifiers)}</b> — '
                    f'Default: {rating_overall:.1f} ({lg(rating_overall)}) &rarr; '
                    f'Adjusted: {adj_rating:.1f} ({lg(adj_rating)})</div></div>')

    flag_pills = ""
    if flag_injury:
        flag_pills += '<span class="flag flag-red">⚠ Injury Risk</span>'
    if flag_leader_val:
        flag_pills += '<span class="flag flag-yellow">🏆 Leader</span>'
    if flag_ceiling:
        flag_pills += '<span class="flag flag-blue">📈 High Ceiling</span>'
    flags_html = f'<div class="flags">{flag_pills}</div>' if flag_pills else ""

    # Sub-score table rows
    sub_rows = ""
    for key, label in component_labels:
        sc = scores[key]
        w_pct = weights[key] * 100
        sub_rows += (f'<tr><td class="left">{label}</td>'
                     f'<td>{w_pct:.0f}%</td>'
                     f'<td class="score-num">{sc:.1f}</td>'
                     f'<td>{bar_html(sc)}</td></tr>')

    # Personality table rows
    inj_rows = (
        f'<tr><td class="left">Overall</td><td>{prone_overall_v}</td>'
        f'<td style="color:{injury_color(prone_overall_v)};font-weight:bold">{injury_label(prone_overall_v)}</td></tr>'
        f'<tr><td class="left">Leg</td><td>{prone_leg_v}</td>'
        f'<td style="color:{injury_color(prone_leg_v)};font-weight:bold">{injury_label(prone_leg_v)}</td></tr>'
        f'<tr><td class="left">Back</td><td>{prone_back_v}</td>'
        f'<td style="color:{injury_color(prone_back_v)};font-weight:bold">{injury_label(prone_back_v)}</td></tr>'
        f'<tr><td class="left">Arm</td><td>{prone_arm_v}</td>'
        f'<td style="color:{injury_color(prone_arm_v)};font-weight:bold">{injury_label(prone_arm_v)}</td></tr>'
    )
    dev_rows = (
        f'<tr><td class="left">Work Ethic</td><td>{we_v}</td>'
        f'<td style="color:{trait_color(we_v)};font-weight:bold">{trait_label(we_v)}</td></tr>'
        f'<tr><td class="left">Intelligence</td><td>{iq_v}</td>'
        f'<td style="color:{trait_color(iq_v)};font-weight:bold">{trait_label(iq_v)}</td></tr>'
    )
    club_rows = (
        f'<tr><td class="left">Leadership</td><td>{leader_v}</td>'
        f'<td style="color:{trait_color(leader_v)};font-weight:bold">{trait_label(leader_v)}</td></tr>'
        f'<tr><td class="left">Greed</td><td>{greed_v}</td>'
        f'<td style="color:{trait_color(greed_v, invert=True)};font-weight:bold">{trait_label(greed_v)}</td></tr>'
        f'<tr><td class="left">Loyalty</td><td>{loyalty_v}</td>'
        f'<td style="color:{trait_color(loyalty_v)};font-weight:bold">{trait_label(loyalty_v)}</td></tr>'
        f'<tr><td class="left">Play for Winner</td><td>{pfw_v}</td>'
        f'<td style="color:{trait_color(pfw_v)};font-weight:bold">{trait_label(pfw_v)}</td></tr>'
    )

    _focus_str = (' ' + ' '.join(focus_modifiers)) if focus_modifiers else ''
    _focus_display = ("Focus: " + ", ".join(focus_modifiers)) if focus_modifiers else ""
    _ootp_kwargs_esc = json.dumps(dict(first=first_name, last=last_name, focus_modifiers=focus_modifiers)).replace('"', '&quot;')
    _ootp_meta = (
        '<meta name="ootp-skill" content="player-rating">'
        f'<meta name="ootp-args" content="{first_name} {last_name}{_focus_str}">'
        f'<meta name="ootp-args-display" content="{_focus_display}">'
        f'<meta name="ootp-save" content="{save_name}">'
        f'<meta name="ootp-kwargs" content="{_ootp_kwargs_esc}">'
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{first} {last} - Rating Report</title>
{_ootp_meta}
<style>{get_report_css()}</style></head><body>
<div class="container">

<div class="page-header">
  <div class="header-top">
    <div>
      <div class="player-name">{first} {last}</div>
      <div class="player-meta">{team_abbr} &bull; {pos_name} &bull; Age {age_disp} &bull; B/T: {bats_str}/{throws_str}</div>
      <div style="margin-top:6px">
        <span class="badge badge-oa">OA {oa_disp}</span>
        <span class="badge badge-pot">POT {pot_disp}</span>
      </div>
      {flags_html}
    </div>
    <div class="grade-badge">{lg(final_rating)}</div>
  </div>
  <div class="rating-bar-wrap">
    <span class="rating-label">Overall Rating</span>
    <span class="rating-val">{final_rating:.1f}</span>
    <span class="oa-pot">&nbsp;&bull;&nbsp;#{rank} of {rank_total} {pos_name}</span>
  </div>
  <div class="import-ts">Generated: {generated_at} &bull; Last DB import: {last_import or "unknown"}</div>
</div>

{adj_note}

<div class="section">
  <div class="section-title">Analysis</div>
<!-- ANALYSIS:START --><!-- RATING_SUMMARY --><!-- ANALYSIS:END -->
</div>

<div class="section">
  <div class="section-title">Rating Breakdown</div>
  <table>
  <tr><th class="left">Component</th><th>Weight</th><th>Score</th><th>Bar</th></tr>
  {sub_rows}
  <tr style="border-top:2px solid #2c2c3e">
  <td class="left"><b>Overall</b></td><td></td>
  <td class="score-num">{final_rating:.1f}</td>
  <td>{bar_html(final_rating)}</td>
  </tr>
  </table>
</div>

<div class="section">
  <div class="section-title">Durability</div>
  <table>
  <tr><th class="left">Area</th><th>Value</th><th>Label</th></tr>
  {inj_rows}
  </table>
</div>

<div class="section">
  <div class="section-title">Development</div>
  <table>
  <tr><th class="left">Trait</th><th>Value</th><th>Label</th></tr>
  {dev_rows}
  </table>
</div>

<div class="section">
  <div class="section-title">Clubhouse</div>
  <table>
  <tr><th class="left">Trait</th><th>Value</th><th>Label</th></tr>
  {club_rows}
  </table>
</div>

<div class="section">
  <div class="section-title">Key Stats</div>
  <table>
  <tr><th>{key_stat_label}</th><th>WAR</th></tr>
  <tr><td>{key_stat_val}</td><td>{war_val}</td></tr>
  </table>
</div>

</div>
</body></html>"""

    args_key = {"focus": sorted(m.lower().strip(",") for m in focus_modifiers) if focus_modifiers else []}
    report_path = get_reports_dir(save_name, "ratings") / report_filename(f"rating_{player_id}", args_key)
    write_report_html(report_path, html)

    return str(report_path), dict(
        player_name=f"{first} {last}",
        team_abbr=team_abbr,
        position=pos_name,
        age=age_disp,
        oa=oa_disp,
        pot=pot_disp,
        player_type=player_type,
        rating_overall=round(final_rating, 1),
        grade=lg(final_rating),
        rank=rank,
        rank_total=rank_total,
        wrc_plus=data["wrc_plus"],
        fip=data["fip"],
        war=data["war"],
        flag_injury_risk=bool(flag_injury),
        flag_leader=bool(flag_leader_val),
        flag_high_ceiling=bool(flag_ceiling),
        adjusted=adjusted,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Positions where defense matters most (get 1.3x defense weight)
PREMIUM_DEFENSE_POS = {POS_CATCHER, POS_SS, POS_2B, POS_CF}
# Positions where defense matters least (get 0.7x)
LOW_DEFENSE_POS = {POS_1B, POS_LF, POS_RF}

# ZR scoring: score = clamp(50 + zr / half_range * 50)
# half_range calibrated from empirical p10/p90 spread in the DB
ZR_HALF_RANGE = {
    POS_CATCHER: 1.5, POS_1B: 2.5, POS_2B: 4.5, POS_3B: 5.0,
    POS_SS: 5.5, POS_LF: 6.0, POS_CF: 9.0, POS_RF: 6.5,
}

# DP per 150G scoring: clamp((dp_per_150 - dp_min) / (dp_max - dp_min) * 100)
# Calibrated from empirical min/max in the DB
DP_SCALE = {
    POS_1B: (19, 134),
    POS_2B: (43, 116),
    POS_3B: (11, 40),
    POS_SS: (27, 111),
}

# Position field rating column mapping
POS_FIELD_COL = {
    POS_CATCHER: "fielding_rating_pos2",
    POS_1B: "fielding_rating_pos3",
    POS_2B: "fielding_rating_pos4",
    POS_3B: "fielding_rating_pos5",
    POS_SS: "fielding_rating_pos6",
    POS_LF: "fielding_rating_pos7",
    POS_CF: "fielding_rating_pos8",
    POS_RF: "fielding_rating_pos9",
}

# Default weights for position players
BATTER_WEIGHTS = {
    "offense": 0.30,
    "contact_quality": 0.15,
    "discipline": 0.10,
    "defense": 0.15,
    "potential": 0.15,
    "durability": 0.05,   # injury risk only (was 0.10)
    "development": 0.03,  # work ethic + intelligence
    "clubhouse": 0.02,    # leadership + greed(inv) + loyalty
    "baserunning": 0.05,
}

# Default weights for pitchers
PITCHER_WEIGHTS = {
    "run_prevention": 0.30,
    "dominance": 0.15,
    "contact_suppression": 0.15,
    "command": 0.10,
    "potential": 0.15,
    "durability": 0.05,   # injury risk only (was 0.10)
    "development": 0.03,  # work ethic + intelligence
    "clubhouse": 0.02,    # leadership + greed(inv) + loyalty
    "role_value": 0.05,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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

    players = pd.read_sql(f"""
        SELECT player_id, age, position, prone_overall,
               personality_work_ethic, personality_intelligence, personality_leader,
               personality_greed, personality_loyalty
        FROM players
        WHERE player_id IN (SELECT player_id FROM batter_advanced_stats)
    """, engine)

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

    players = pd.read_sql(f"""
        SELECT player_id, age, position, prone_overall,
               personality_work_ethic, personality_intelligence, personality_leader,
               personality_greed, personality_loyalty
        FROM players
        WHERE player_id IN (SELECT player_id FROM pitcher_advanced_stats)
    """, engine)

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
def score_offense(row, xwoba_pctile, ootp_bat_score=None, career_pa=0):
    """Offensive production score from wRC+ and xwOBA.

    Blends in an OOTP-based talent anchor for players with thin MLB career
    stats using a sqrt ramp: anchor=100% at 0 PA, stats=100% at 300+ PA.
    Sqrt matches how statistical confidence actually builds (consistent with
    the platoon score convention in this codebase).

    Anchor priority:
      1. players_scouted_ratings (scouting_team_id=0) — ground-truth current ratings.
         Only available when "Additional complete scouted ratings" is enabled in OOTP.
      2. batting_ratings_talent_* — potential/ceiling ratings, always exported.
         Batting-specific: a pitcher's talent ratings are 20s, a hitter's are meaningful.
         This ensures pitchers with thin PA samples anchor near 0, not at their pitching oa.

    Without this anchor, a player with 13 PA and an inflated wOBA would get a
    near-perfect rating_offense, corrupting the blended_woba talent anchor.
    """
    wrc = row.get("wrc_plus", 100)
    if career_pa < PA_REGRESSION_THRESHOLD:
        pa_trust = min((career_pa / PA_REGRESSION_THRESHOLD) ** REGRESSION_EXPONENT, 1.0)
        wrc_cap = 100 + pa_trust * WRC_CAP_HEADROOM
        wrc = min(wrc, wrc_cap) if wrc is not None else 100
    wrc_score = clamp((wrc - 50) * (100 / 120))
    xwoba_score = xwoba_pctile if not pd.isna(xwoba_pctile) else 50
    stats_score = wrc_score * OFFENSE_WRC_WEIGHT + xwoba_score * OFFENSE_XWOBA_WEIGHT

    if career_pa < PA_REGRESSION_THRESHOLD:
        anchor = ootp_bat_score if ootp_bat_score is not None else 50.0
        return stats_score * pa_trust + anchor * (1.0 - pa_trust)

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
    # ── Component 1: OOTP talent rating ─────────────────────────────────────
    pos_col = POS_FIELD_COL.get(position)
    if pos_col and fielding_row is not None and pos_col in fielding_row:
        field_rating = fielding_row[pos_col]
        if pd.notna(field_rating) and field_rating > 0:
            rating_score = clamp((field_rating - 20) / 60 * 100)
        else:
            rating_score = 50.0
    else:
        rating_score = 50.0

    # ── Component 2: Actual fielding stats ───────────────────────────────────
    fld_g = row.get("fld_g") if hasattr(row, "get") else None
    if fld_g is None or pd.isna(fld_g):
        fld_g = 0
    fld_g = int(fld_g)

    if fld_g < FIELDING_MIN_GAMES:
        # Not enough data — fall back to rating only
        score = rating_score
    else:
        components = []   # list of (score_0_100, weight)

        def _fval(key, default=0.0):
            """Safely extract a float from row, returning default for NaN/None."""
            v = row.get(key)
            return float(v) if (v is not None and not pd.isna(v)) else default

        # ZR — position-specific scaling so ±half_range maps to 0/100
        half_range = ZR_HALF_RANGE.get(position, 5.0)
        zr_score = clamp(50.0 + _fval("fld_zr") / half_range * 50.0)

        # FPct — (tc-e)/tc; good ≥.985, poor ≤.960
        tc = _fval("fld_tc")
        e  = _fval("fld_e")
        fpct_score = clamp((((tc - e) / tc) - 0.950) / 0.035 * 100) if tc > 0 else 50.0

        if position == POS_CATCHER:
            sba = _fval("fld_sba")
            rto = _fval("fld_rto")
            total_att = sba + rto
            cs_score = clamp(rto / total_att / 0.35 * 100) if total_att >= CATCHER_MIN_CS_ATTEMPTS else 50.0

            framing = _fval("fld_framing")
            framing_score = clamp(50.0 + framing / 12.0 * 50.0)

            components = [(zr_score, 0.30), (fpct_score, 0.15),
                          (cs_score, 0.30), (framing_score, 0.25)]

        elif position in (POS_2B, POS_SS):
            dp_per_150 = _fval("fld_dp") / fld_g * 150
            dp_min, dp_max = DP_SCALE[position]
            dp_score = clamp((dp_per_150 - dp_min) / (dp_max - dp_min) * 100)
            components = [(zr_score, 0.40), (fpct_score, 0.20), (dp_score, 0.40)]

        elif position in (POS_3B, POS_1B):
            dp_per_150 = _fval("fld_dp") / fld_g * 150
            dp_min, dp_max = DP_SCALE[position]
            dp_score = clamp((dp_per_150 - dp_min) / (dp_max - dp_min) * 100)
            components = [(zr_score, 0.40), (fpct_score, 0.30), (dp_score, 0.30)]

        elif position == POS_CF:
            arm_score = clamp(50.0 + _fval("fld_arm") * 10.0)
            po_score  = clamp((_fval("fld_po") / fld_g - 0.9) / 2.0 * 100)
            components = [(zr_score, 0.40), (fpct_score, 0.10), (arm_score, 0.20), (po_score, 0.30)]

        else:  # LF, RF
            arm_score = clamp(50.0 + _fval("fld_arm") * 10.0)
            components = [(zr_score, 0.40), (fpct_score, 0.20), (arm_score, 0.40)]

        total_w = sum(w for _, w in components)
        stats_score = sum(s * w for s, w in components) / total_w if total_w > 0 else 50.0

        score = rating_score * 0.50 + stats_score * 0.50

    # ── Position multiplier ──────────────────────────────────────────────────
    if position in PREMIUM_DEFENSE_POS:
        score = min(100, score * DEFENSE_PREMIUM_MULTIPLIER)
    elif position in LOW_DEFENSE_POS:
        score = score * DEFENSE_BAT_FIRST_MULTIPLIER

    return score


def score_baserunning(batting_row):
    """Baserunning score from OOTP running ratings."""
    if batting_row is None:
        return 50.0
    vals = []
    for col in ["running_ratings_speed", "running_ratings_stealing",
                "running_ratings_baserunning"]:
        v = batting_row.get(col)
        if pd.notna(v) and v > 0:
            vals.append(clamp((v - 20) / 60 * 100))
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
def score_potential(value_row, age, current_metric, prev_metric):
    """Potential & trajectory score."""
    # Ceiling gap
    oa = value_row.get("oa", 50) if value_row is not None else 50
    pot = value_row.get("pot", 50) if value_row is not None else 50
    if pd.isna(oa):
        oa = 50
    if pd.isna(pot):
        pot = 50
    gap = pot - oa
    score_ceiling = clamp(gap * 5)

    # Career trend
    if current_metric is not None and prev_metric is not None:
        diff = current_metric - prev_metric
        score_trend = clamp(50 + diff * 2)
    else:
        score_trend = 50.0

    # Age-based blending
    if pd.isna(age):
        age = 27
    age = int(age)
    if age < 26:
        return score_ceiling * 0.7 + score_trend * 0.3
    elif age > 32:
        return score_ceiling * 0.3 + score_trend * 0.7
    else:
        return score_ceiling * 0.5 + score_trend * 0.5


def score_durability(player_row):
    """Injury risk score (proneness only). Iron Man (0) → 100, Wrecked (200) → 0."""
    prone = player_row.get("prone_overall", 100)
    if pd.isna(prone):
        prone = 100
    return clamp(100 - prone / 2)


def score_development(player_row):
    """Development score from Work Ethic and Intelligence.
    Drives development speed, ceiling achievement, slump resistance, and longevity.
    Age-flat — score_potential() already weights ceiling gap more for young players.
    """
    we = player_row.get("personality_work_ethic", 100)
    iq = player_row.get("personality_intelligence", 100)
    if pd.isna(we):
        we = 100
    if pd.isna(iq):
        iq = 100
    return clamp(we / 2) * 0.50 + clamp(iq / 2) * 0.50


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
        for col in contact_pctile_cols:
            if col in pctiles:
                player_pctiles[col] = pctiles[col].iloc[idx]

        # Trend
        trend_current, trend_prev = trend_data.get(pid, (None, None))

        # OOTP batting anchor for thin-stat blend (20-80 → 0-100).
        # Priority: scouted current ratings (ground-truth, only when export enabled)
        #           → talent ratings (always exported, batting-specific, reflects ceiling)
        # Never falls back to players_value.oa, which for pitchers reflects pitching skill.
        sr_vals = [row.get(c) for c in ("sr_contact", "sr_power", "sr_eye", "sr_gap")]
        sr_vals = [v for v in sr_vals if v is not None and not pd.isna(v) and v > 0]
        if sr_vals:
            ootp_bat_score = clamp((sum(sr_vals) / len(sr_vals) - 20) / 60 * 100)
        else:
            talent_vals = [row.get(c) for c in ("talent_contact", "talent_power", "talent_eye", "talent_gap")]
            talent_vals = [v for v in talent_vals if v is not None and not pd.isna(v) and v > 0]
            ootp_bat_score = clamp((sum(talent_vals) / len(talent_vals) - 20) / 60 * 100) if talent_vals else None
        career_pa = int(career_pa_totals.get(pid, 0))

        # Sub-scores
        s_offense = score_offense(row, player_pctiles.get("xwoba", 50), ootp_bat_score, career_pa)
        s_contact = score_contact_quality(row, player_pctiles, career_pa)
        s_discipline = score_discipline(row, career_pa)
        s_defense = score_defense(row, row, pos)
        s_baserunning = score_baserunning(row)
        s_potential = score_potential(row, age, trend_current, trend_prev)
        s_durability = score_durability(row)
        s_development = score_development(row)
        s_clubhouse = score_clubhouse(row)

        # Weighted composite
        overall = (
            s_offense * BATTER_WEIGHTS["offense"] +
            s_contact * BATTER_WEIGHTS["contact_quality"] +
            s_discipline * BATTER_WEIGHTS["discipline"] +
            s_defense * BATTER_WEIGHTS["defense"] +
            s_potential * BATTER_WEIGHTS["potential"] +
            s_durability * BATTER_WEIGHTS["durability"] +
            s_development * BATTER_WEIGHTS["development"] +
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
            rating_offense=round(s_offense, 1),
            rating_contact_quality=round(s_contact, 1),
            rating_discipline=round(s_discipline, 1),
            rating_defense=round(s_defense, 1),
            rating_potential=round(s_potential, 1),
            rating_durability=round(s_durability, 1),
            rating_development=round(s_development, 1),
            rating_clubhouse=round(s_clubhouse, 1),
            rating_baserunning=round(s_baserunning, 1),
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

    # Get league FIP constant
    with engine.connect() as conn:
        r = conn.execute(text(f"""
            SELECT SUM(er)*9.0/SUM(ip) as era,
                   (SUM(er)*9.0/SUM(ip)) -
                   ((13.0*SUM(hra) + 3.0*(SUM(bb)+SUM(hp)) - 2.0*SUM(k)) / SUM(ip)) as cfip
            FROM team_pitching_stats
            WHERE league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID} AND split_id = {SPLIT_TEAM_PITCHING_OVERALL}
        """)).fetchone()
        cfip = float(r[1])

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
        if sr_pit_vals:
            ootp_pit_score = clamp((sum(sr_pit_vals) / len(sr_pit_vals) - 20) / 60 * 100)
            career_ip = float(career_ip_totals.get(pid, 0))
            if career_ip < IP_REGRESSION_THRESHOLD:
                ip_trust = min(career_ip / IP_REGRESSION_THRESHOLD, 1.0) ** REGRESSION_EXPONENT
                ootp_weight = (1.0 - ip_trust) * OOTP_MAX_BLEND_WEIGHT
                s_run_prev = s_run_prev * (1 - ootp_weight) + ootp_pit_score * ootp_weight

        s_dominance = score_dominance(row)
        s_suppress = score_contact_suppression(player_pctiles)
        s_command = score_command(row)
        s_potential = score_potential(row, age, pot_current, pot_prev)
        s_durability = score_durability(row)
        s_development = score_development(row)
        s_clubhouse = score_clubhouse(row)
        s_role = score_role_value(row)

        overall = (
            s_run_prev * PITCHER_WEIGHTS["run_prevention"] +
            s_dominance * PITCHER_WEIGHTS["dominance"] +
            s_suppress * PITCHER_WEIGHTS["contact_suppression"] +
            s_command * PITCHER_WEIGHTS["command"] +
            s_potential * PITCHER_WEIGHTS["potential"] +
            s_durability * PITCHER_WEIGHTS["durability"] +
            s_development * PITCHER_WEIGHTS["development"] +
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
            rating_offense=round(s_run_prev, 1),  # reuse column, means "run prevention"
            rating_contact_quality=round(s_suppress, 1),  # means "contact suppression"
            rating_discipline=round(s_dominance, 1),  # means "dominance"
            rating_defense=round(s_command, 1),  # means "command"
            rating_potential=round(s_potential, 1),
            rating_durability=round(s_durability, 1),
            rating_development=round(s_development, 1),
            rating_clubhouse=round(s_clubhouse, 1),
            rating_baserunning=round(s_role, 1),  # means "role value"
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


# ---------------------------------------------------------------------------
# Letter grade
# ---------------------------------------------------------------------------
def letter_grade(score):
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B+"
    elif score >= 60:
        return "B"
    elif score >= 50:
        return "C+"
    elif score >= 40:
        return "C"
    elif score >= 30:
        return "D"
    else:
        return "F"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <save_name>")
        print("Example: python src/ratings.py My-Save-2026")
        sys.exit(1)

    save_name = sys.argv[1]
    engine = get_engine(save_name)
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
        print(f"\nTop 15 position players:")
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
        print(f"\nTop 15 pitchers:")
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


if __name__ == "__main__":
    main()
