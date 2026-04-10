"""Per-player rating queries for reports and skills."""

from sqlalchemy import text

from config import (
    ARCHETYPE_CONTACT_K_MAX,
    ARCHETYPE_CONTACT_XBA_MIN,
    ARCHETYPE_CONTACT_XSLG_MAX,
    ARCHETYPE_EMPTY_BARREL_MAX,
    ARCHETYPE_EMPTY_XBA_MIN,
    ARCHETYPE_EMPTY_XSLG_MAX,
    ARCHETYPE_MASHER_BARREL_MIN,
    ARCHETYPE_MASHER_K_MIN,
    ARCHETYPE_MASHER_XSLG_MIN,
    ARCHETYPE_MIN_PA,
    ARCHETYPE_PATIENT_BB_MIN,
    ARCHETYPE_PATIENT_XSLG_MIN,
    ARCHETYPE_PATIENT_XWOBA_MIN,
    ARCHETYPE_SPEED_K_MAX,
    ARCHETYPE_SPEED_SB,
    ARCHETYPE_SPEED_XBA_MIN,
    ARCHETYPE_SPEED_XSLG_MAX,
    DEFENSE_BAT_FIRST_MULTIPLIER,
    DEFENSE_PREMIUM_MULTIPLIER,
    OOTP_RATING_SCALE_MIN,
    PITCHER_WEIGHT_CLUBHOUSE,
    PITCHER_WEIGHT_COMMAND,
    PITCHER_WEIGHT_CONTACT_SUPPRESSION,
    PITCHER_WEIGHT_DOMINANCE,
    PITCHER_WEIGHT_DURABILITY,
    PITCHER_WEIGHT_POTENTIAL,
    PITCHER_WEIGHT_ROLE_VALUE,
    PITCHER_WEIGHT_RUN_PREVENTION,
)
from ootp_db_constants import (
    MLB_LEAGUE_ID,
    MLB_LEVEL_ID,
    POS_CATCHER,
    POS_FIRST_BASE as POS_1B,
    POS_SECOND_BASE as POS_2B,
    POS_THIRD_BASE as POS_3B,
    POS_SHORTSTOP as POS_SS,
    POS_LEFT_FIELD as POS_LF,
    POS_CENTER_FIELD as POS_CF,
    POS_RIGHT_FIELD as POS_RF,
    SPLIT_CAREER_OVERALL,
)
from shared_css import get_engine

from .constants import (
    BATTER_WEIGHTS,
    LOW_DEFENSE_POS,
    POS_FIELD_COL,
    PREMIUM_DEFENSE_POS,
    SCALE_RANGE,
)


def classify_batter_archetype(adv):
    """Classify a batter into one of five archetypes based on advanced stats.

    Returns (label, color, description) or (None, None, None) if insufficient data.

    Priority order (first match wins):
      1. Speedster    — speed-first profile
      2. Patient Slugger  — walks + real power
      3. All-or-Nothing   — big power, high strikeouts
      4. Contact Hitter   — contact-first, low K
      5. Empty Average Bat — average without damage
    """
    if not adv:
        return None, None, None
    pa = adv.get("pa") or 0
    if pa < ARCHETYPE_MIN_PA:
        return None, None, None

    xwoba = adv.get("xwoba") or 0
    xslg = adv.get("xslg") or 0
    xba = adv.get("xba") or 0
    barrel = adv.get("barrel_pct") or 0
    bb_pct = adv.get("bb_pct") or 0
    k_pct = adv.get("k_pct") or 0
    sb = adv.get("sb") or 0

    if (sb >= ARCHETYPE_SPEED_SB
            and xslg < ARCHETYPE_SPEED_XSLG_MAX
            and (xba >= ARCHETYPE_SPEED_XBA_MIN or k_pct < ARCHETYPE_SPEED_K_MAX)):
        return ("Speedster", "#1a6b8a",
                f"Speed-first profile: {int(sb)} SB, low power (xSLG {xslg:.3f})")

    if (bb_pct >= ARCHETYPE_PATIENT_BB_MIN
            and xwoba >= ARCHETYPE_PATIENT_XWOBA_MIN
            and xslg >= ARCHETYPE_PATIENT_XSLG_MIN):
        return ("Patient Slugger", "#1a7a1a",
                f"High BB% ({bb_pct*100:.1f}%), elite xwOBA ({xwoba:.3f}), strong xSLG ({xslg:.3f})")

    if (barrel >= ARCHETYPE_MASHER_BARREL_MIN
            and xslg >= ARCHETYPE_MASHER_XSLG_MIN
            and k_pct >= ARCHETYPE_MASHER_K_MIN):
        return ("All-or-Nothing", "#8a4a1a",
                f"Big power (Barrel {barrel*100:.1f}%, xSLG {xslg:.3f}) but high K% ({k_pct*100:.1f}%)")

    if (k_pct < ARCHETYPE_CONTACT_K_MAX
            and xba >= ARCHETYPE_CONTACT_XBA_MIN
            and xslg < ARCHETYPE_CONTACT_XSLG_MAX):
        return ("Contact Hitter", "#2266cc",
                f"Low K% ({k_pct*100:.1f}%), strong xBA ({xba:.3f}), contact-first approach")

    if (xba >= ARCHETYPE_EMPTY_XBA_MIN
            and xslg < ARCHETYPE_EMPTY_XSLG_MAX
            and barrel < ARCHETYPE_EMPTY_BARREL_MAX):
        return ("Empty Average", "#888888",
                f"Decent xBA ({xba:.3f}) but weak xSLG ({xslg:.3f}), little damage on contact")

    return None, None, None


def query_player_rating(save_name, first_name, last_name, focus_modifiers=None):
    """Query and compute all data needed for a player rating report.

    Returns a complete dict with all values needed by generate_rating_report
    and MCP tools, or None if the player is not found.
    Does NOT perform a cache check.
    """
    engine = get_engine(save_name)

    with engine.connect() as conn:
        from sqlalchemy import text as sa_text

        _rating_sql = (
            "SELECT pr.player_id, pr.first_name, pr.last_name, pr.team_abbr, pr.position, "
            "pr.age, pr.oa, pr.pot, pr.player_type, pr.rating_overall, "
            "pr.rating_offense, pr.rating_contact_quality, pr.rating_discipline, "
            "pr.rating_defense, pr.rating_potential, pr.rating_durability, "
            "pr.rating_development, pr.rating_clubhouse, pr.rating_baserunning, "
            "pr.flag_injury_risk, pr.flag_leader, pr.flag_high_ceiling, "
            "pr.wrc_plus, pr.war, pr.prone_overall, "
            "pr.rating_now, pr.rating_ceiling, pr.confidence, "
            "p.bats, p.throws, "
            "p.prone_leg, p.prone_back, p.prone_arm, "
            "p.personality_work_ethic, p.personality_intelligence, p.personality_leader, "
            "p.personality_greed, p.personality_loyalty, p.personality_play_for_winner"
        )
        _rating_from = (
            " FROM player_ratings pr "
            "JOIN players p ON p.player_id = pr.player_id "
            "WHERE pr.first_name = :first AND pr.last_name = :last"
        )
        try:
            row = conn.execute(sa_text(
                _rating_sql + ", p.personality_adaptability " + _rating_from
            ), dict(first=first_name, last=last_name)).fetchone()
        except Exception:
            row = conn.execute(sa_text(_rating_sql + _rating_from), dict(first=first_name, last=last_name)).fetchone()

        if not row:
            return None

        vals = list(row._mapping.values()) if hasattr(row, "_mapping") else list(row)
        adaptability = None
        if len(vals) == 40:
            adaptability = vals.pop()
        (player_id, first, last, team_abbr, position, age, oa, pot, player_type,
         rating_overall, r_offense, r_contact, r_discipline, r_defense, r_potential,
         r_durability, r_development, r_clubhouse, r_baserunning,
         flag_injury, flag_leader_val, flag_ceiling,
         wrc_plus_or_fip, war, prone_overall,
         rating_now, rating_ceiling, confidence,
         bats, throws, prone_leg, prone_back, prone_arm,
         work_ethic, intelligence, leader, greed, loyalty, play_for_winner) = vals

        rank_row = conn.execute(sa_text(
            "SELECT COUNT(*)+1 FROM player_ratings WHERE position = :pos AND rating_now > :r"
        ), dict(pos=position, r=rating_now)).fetchone()
        total_row = conn.execute(sa_text(
            "SELECT COUNT(*) FROM player_ratings WHERE position = :pos"
        ), dict(pos=position)).fetchone()
        rank = int(rank_row[0])
        rank_total = int(total_row[0])

        adv_row = conn.execute(sa_text(
            "SELECT pa, xwoba, xslg, xba, xbacon, barrel_pct, bb_pct, k_pct, sb "
            "FROM batter_advanced_stats WHERE player_id = :pid"
        ), dict(pid=player_id)).fetchone()
        adv_for_archetype = dict(zip(
            ("pa", "xwoba", "xslg", "xba", "xbacon", "barrel_pct", "bb_pct", "k_pct", "sb"),
            adv_row
        )) if adv_row else None

    is_pitcher = (player_type == "pitcher")
    archetype_label, archetype_color, archetype_desc = (
        (None, None, None) if is_pitcher
        else classify_batter_archetype(adv_for_archetype)
    )

    pos_map = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
    bats_map = {1: "R", 2: "L", 3: "S"}
    throws_map = {1: "R", 2: "L"}
    pos_name = pos_map.get(position, str(position))
    bats_str = bats_map.get(bats, "?")
    throws_str = throws_map.get(throws, "?")

    if is_pitcher:
        base_weights = dict(
            offense=PITCHER_WEIGHT_RUN_PREVENTION,
            contact_quality=PITCHER_WEIGHT_CONTACT_SUPPRESSION,
            discipline=PITCHER_WEIGHT_DOMINANCE,
            defense=PITCHER_WEIGHT_COMMAND,
            potential=PITCHER_WEIGHT_POTENTIAL,
            durability=PITCHER_WEIGHT_DURABILITY,
            clubhouse=PITCHER_WEIGHT_CLUBHOUSE,
            baserunning=PITCHER_WEIGHT_ROLE_VALUE,
        )
        component_labels = [
            ("offense", "Run Prevention"),
            ("contact_quality", "Contact Suppression"),
            ("discipline", "Dominance"),
            ("defense", "Command"),
            ("durability", "Durability"),
            ("baserunning", "Role Value"),
            ("potential", "Potential"),
            ("clubhouse", "Clubhouse"),
        ]
    else:
        base_weights = dict(BATTER_WEIGHTS)
        component_labels = [
            ("offense", "Offense"),
            ("contact_quality", "Contact Quality"),
            ("discipline", "Discipline"),
            ("defense", "Defense"),
            ("durability", "Durability"),
            ("baserunning", "Baserunning"),
            ("potential", "Potential"),
            ("clubhouse", "Clubhouse"),
        ]

    scores = dict(
        offense=r_offense, contact_quality=r_contact, discipline=r_discipline,
        defense=r_defense, potential=r_potential, durability=r_durability,
        development=r_development, clubhouse=r_clubhouse, baserunning=r_baserunning,
    )

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
                        raw_score = (
                            min(100.0, max(0.0, (field_rating - OOTP_RATING_SCALE_MIN) / SCALE_RANGE * 100))
                            if field_rating > 0 else 50.0
                        )
                        scores["defense"] = raw_score
                        if target_pos in PREMIUM_DEFENSE_POS:
                            base_weights["defense"] = min(base_weights["defense"] * DEFENSE_PREMIUM_MULTIPLIER, 0.95)
                        elif target_pos in LOW_DEFENSE_POS:
                            base_weights["defense"] *= DEFENSE_BAT_FIRST_MULTIPLIER

    focus_map = {
        "defense": ("defense", 0.15), "fielding": ("defense", 0.15),
        "power": ("contact_quality", 0.15), "contact": ("contact_quality", 0.15),
        "upside": ("potential", 0.15), "potential": ("potential", 0.15),
        "durability": ("durability", 0.15),
        "discipline": ("discipline", 0.15),
        "offense": ("offense", 0.15), "hitting": ("offense", 0.15),
        "speed": ("baserunning", 0.15), "baserunning": ("baserunning", 0.15),
        "development": ("potential", 0.15), "work": ("potential", 0.15), "ethic": ("potential", 0.15),
        "adaptability": ("potential", 0.15), "iq": ("potential", 0.15),
        "clubhouse": ("clubhouse", 0.15), "leadership": ("clubhouse", 0.15),
        "dominance": ("discipline", 0.15), "strikeouts": ("discipline", 0.15),
        "command": ("defense", 0.15), "control": ("defense", 0.15),
        "first": ("offense", 0.22), "1b": ("offense", 0.22),
        "left": ("offense", 0.22), "lf": ("offense", 0.22),
        "third": ("offense", 0.15), "3b": ("offense", 0.15),
        "right": ("offense", 0.15), "rf": ("offense", 0.15),
        "outfield": ("offense", 0.15), "of": ("offense", 0.15),
        "dh": ("offense", 0.35), "designated": ("offense", 0.35),
        "shortstop": ("defense", 0.15), "ss": ("defense", 0.15),
        "catcher": ("defense", 0.15), "catching": ("defense", 0.15),
        "second": ("defense", 0.15), "2b": ("defense", 0.15),
        "center": ("defense", 0.15), "cf": ("defense", 0.15),
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

    final_rating = adj_rating if adjusted else rating_overall

    oa_disp = int(oa) if oa is not None else 0
    pot_disp = int(pot) if pot is not None else 0
    age_disp = int(age) if age is not None else 0
    prone_overall_v = int(prone_overall) if prone_overall is not None else 100
    prone_leg_v = int(prone_leg) if prone_leg is not None else 100
    prone_back_v = int(prone_back) if prone_back is not None else 100
    prone_arm_v = int(prone_arm) if prone_arm is not None else 100
    we_v = int(work_ethic) if work_ethic is not None else 100
    iq_v = int(intelligence) if intelligence is not None else 100
    adapt_v = int(adaptability) if adaptability is not None else 100
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
        rating_now=float(rating_now) if rating_now is not None else 0.0,
        rating_ceiling=float(rating_ceiling) if rating_ceiling is not None else 0.0,
        confidence=float(confidence) if confidence is not None else 0.0,
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
        adapt_v=adapt_v,
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
        archetype_label=archetype_label,
        archetype_color=archetype_color,
        archetype_desc=archetype_desc,
    )


def fetch_career_trend_stats(engine, first_name, last_name):
    """Fetch last 4 MLB seasons of career rate stats for a player.

    Returns a list of printable strings (TYPE: and YEAR: lines) for the agent.
    """
    def fmt_v(v, d=3):
        return f"{v:.{d}f}" if v is not None else "--"

    def fmt_pct(v):
        return f"{v:.1f}%" if v is not None else "--"

    def safe_div(n, d):
        return n / d if d and d > 0 else None

    with engine.connect() as conn:
        pid_row = conn.execute(
            text("SELECT player_id FROM players WHERE first_name=:f AND last_name=:l"),
            dict(f=first_name, l=last_name),
        ).fetchone()
        if not pid_row:
            return ["PLAYER_NOT_FOUND"]
        pid = pid_row[0]

        rows = conn.execute(text(
            "SELECT year, g, pa, ab, h, d, t, hr, bb, k, hp, sf, war "
            "FROM players_career_batting_stats "
            "WHERE player_id=:pid AND split_id=:split_id AND league_id=:league_id AND level_id=:level_id "
            "ORDER BY year DESC LIMIT 4"
        ), dict(pid=pid, split_id=SPLIT_CAREER_OVERALL, league_id=MLB_LEAGUE_ID, level_id=MLB_LEVEL_ID)).fetchall()

        if rows:
            lines = ["TYPE:batter"]
            for r in rows:
                yr, g, pa, ab, h, d, t, hr, bb, k, hp, sf, war = r
                singles = h - (d or 0) - (t or 0) - (hr or 0)
                avg = safe_div(h, ab)
                obp = safe_div((h or 0) + (bb or 0) + (hp or 0),
                               (ab or 0) + (bb or 0) + (hp or 0) + (sf or 0))
                slg = safe_div(singles + 2*(d or 0) + 3*(t or 0) + 4*(hr or 0), ab)
                iso = (slg - avg) if slg is not None and avg is not None else None
                babip = safe_div((h or 0) - (hr or 0),
                                 (ab or 0) - (k or 0) - (hr or 0) + (sf or 0))
                k_pct = safe_div((k or 0) * 100, pa)
                bb_pct = safe_div((bb or 0) * 100, pa)
                ops = (obp + slg) if obp is not None and slg is not None else None
                war_str = fmt_v(float(war), 1) if war is not None else "--"
                lines.append(
                    f"YEAR:{yr} G:{g} PA:{pa} HR:{hr} "
                    f"AVG:{fmt_v(avg)} OBP:{fmt_v(obp)} SLG:{fmt_v(slg)} OPS:{fmt_v(ops)} "
                    f"ISO:{fmt_v(iso)} BABIP:{fmt_v(babip)} "
                    f"K%:{fmt_pct(k_pct)} BB%:{fmt_pct(bb_pct)} WAR:{war_str}"
                )
            return lines

        rows = conn.execute(text(
            "SELECT year, g, gs, ip, ha, hra, bb, k, er, bf, hp, gb, fb, war "
            "FROM players_career_pitching_stats "
            "WHERE player_id=:pid AND split_id=:split_id AND league_id=:league_id AND level_id=:level_id "
            "ORDER BY year DESC LIMIT 4"
        ), dict(pid=pid, split_id=SPLIT_CAREER_OVERALL, league_id=MLB_LEAGUE_ID, level_id=MLB_LEVEL_ID)).fetchall()
        if rows:
            lines = ["TYPE:pitcher"]
            for r in rows:
                yr, g, gs, ip, ha, hra, bb, k, er, bf, hp, gb, fb, war = r
                ip_f = float(ip) if ip else 0
                era = safe_div((er or 0) * 9, ip_f)
                whip = safe_div((ha or 0) + (bb or 0), ip_f)
                k_pct = safe_div((k or 0) * 100, bf)
                bb_pct = safe_div((bb or 0) * 100, bf)
                kbb = (k_pct - bb_pct) if k_pct is not None and bb_pct is not None else None
                hr9 = safe_div((hra or 0) * 9, ip_f)
                total_bf = (gb or 0) + (fb or 0)
                gb_pct = safe_div((gb or 0) * 100, total_bf)
                war_str = fmt_v(float(war), 1) if war is not None else "--"
                lines.append(
                    f"YEAR:{yr} G:{g} GS:{gs} IP:{fmt_v(ip_f, 1)} ERA:{fmt_v(era)} "
                    f"WHIP:{fmt_v(whip)} K%:{fmt_pct(k_pct)} BB%:{fmt_pct(bb_pct)} "
                    f"K-BB%:{fmt_pct(kbb)} HR/9:{fmt_v(hr9)} GB%:{fmt_pct(gb_pct)} WAR:{war_str}"
                )
            return lines

        return ["NO_CAREER_DATA"]
