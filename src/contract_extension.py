#!/usr/bin/env python3
"""Contract extension advisor report generator for OOTP Baseball."""

import html as html_mod
from datetime import datetime
from pathlib import Path

from config import (
    GRADE_A_PLUS, GRADE_A, GRADE_B_PLUS, GRADE_B, GRADE_C_PLUS, GRADE_C, GRADE_D,
    INJURY_IRON_MAN_MAX, INJURY_DURABLE_MAX, INJURY_NORMAL_MAX, INJURY_FRAGILE_MAX,
    TRAIT_POOR_MAX, TRAIT_BELOW_AVG_MAX, TRAIT_AVERAGE_MAX, TRAIT_GOOD_MAX,
)
from ootp_db_constants import (
    MLB_LEAGUE_ID, MLB_LEVEL_ID,
    POS_MAP, BATS_MAP, THROWS_MAP,
    SPLIT_CAREER_OVERALL, SPLIT_TEAM_BATTING_OVERALL, SPLIT_TEAM_PITCHING_OVERALL,
)
from report_write import write_report_html, report_filename
from shared_css import db_name_from_save, get_engine, get_report_css, get_reports_dir, load_saves_registry
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAST_IMPORT_PATH = PROJECT_ROOT / ".last_import"

_PLAYER_KEYS = [
    "player_id", "first_name", "last_name", "position",
    "age", "oa", "pot", "player_type",
    "rating_overall", "wrc_plus", "war",
    "rating_offense", "rating_defense", "rating_potential",
    "rating_durability", "rating_development", "rating_clubhouse",
    "rating_baserunning",
    "flag_injury_risk", "flag_leader", "flag_high_ceiling",
    "prone_overall", "work_ethic", "intelligence", "greed", "loyalty",
    "play_for_winner",
    "local_pop", "national_pop",
    "bats", "throws",
    "team_abbr",
    "years", "current_year", "no_trade",
    "salary0", "salary1", "salary2", "salary3", "salary4",
    "salary5", "salary6", "salary7", "salary8", "salary9",
    "mlb_service_years",
]


def get_last_import_time():
    if LAST_IMPORT_PATH.exists():
        return LAST_IMPORT_PATH.read_text().strip()
    return None


def letter_grade(score):
    if score >= GRADE_A_PLUS:
        return "A+"
    if score >= GRADE_A:
        return "A"
    if score >= GRADE_B_PLUS:
        return "B+"
    if score >= GRADE_B:
        return "B"
    if score >= GRADE_C_PLUS:
        return "C+"
    if score >= GRADE_C:
        return "C"
    if score >= GRADE_D:
        return "D"
    return "F"


def grade_badge(score):
    grade = letter_grade(score)
    if grade in ("A+", "A"):
        bg = "#1a7a1a"
    elif grade in ("B+", "B"):
        bg = "#2266cc"
    elif grade in ("C+", "C"):
        bg = "#cc7700"
    else:
        bg = "#cc2222"
    return (
        f'<span style="background:{bg};color:white;border-radius:4px;'
        f'font-weight:bold;font-size:12px;padding:2px 6px">{grade} {score:.1f}</span>'
    )


def fmt_salary(val):
    if val is None or val == 0:
        return "—"
    v = int(val)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v}"


def injury_label(val):
    if val is None:
        return "—"
    v = int(val)
    if v <= INJURY_IRON_MAN_MAX:
        return "Iron Man"
    if v <= INJURY_DURABLE_MAX:
        return "Durable"
    if v <= INJURY_NORMAL_MAX:
        return "Normal"
    if v <= INJURY_FRAGILE_MAX:
        return "Fragile"
    return "Wrecked"


def injury_color(val):
    if val is None:
        return "#888"
    v = int(val)
    if v <= INJURY_DURABLE_MAX:
        return "#1a7a1a"
    if v <= INJURY_NORMAL_MAX:
        return "#cc7700"
    return "#cc2222"


def trait_label(val):
    if val is None:
        return "—"
    v = int(val)
    if v <= TRAIT_POOR_MAX:
        return "Very Low"
    if v <= TRAIT_BELOW_AVG_MAX:
        return "Low"
    if v <= TRAIT_AVERAGE_MAX:
        return "Average"
    if v <= TRAIT_GOOD_MAX:
        return "High"
    return "Elite"


def trait_color(val, invert=False):
    """Green=high by default; invert=True means green=low (e.g. greed)."""
    if val is None:
        return "#888"
    v = int(val)
    if invert:
        if v <= INJURY_DURABLE_MAX:
            return "#1a7a1a"
        if v <= INJURY_NORMAL_MAX:
            return "#cc7700"
        return "#cc2222"
    else:
        if v >= TRAIT_GOOD_MAX:
            return "#1a7a1a"
        if v >= TRAIT_BELOW_AVG_MAX:
            return "#cc7700"
        return "#cc2222"


def pop_label(val):
    if val is None:
        return "—"
    v = max(0, min(6, int(val)))
    labels = (
        "None",
        "Below Avg",
        "Average",
        "Notable",
        "Popular",
        "Star",
        "Icon",
    )
    return labels[v]


def pop_color(val):
    if val is None:
        return "#888"
    v = int(val)
    if v >= 5:
        return "#1a7a1a"
    if v >= 3:
        return "#f0c040"
    return "#888"


def arb_status_label(service_years):
    if service_years is None:
        return "Unknown"
    sy = float(service_years)
    if sy < 3:
        return "Pre-Arbitration"
    if sy < 6:
        arb_num = min(int(sy) - 2, 3)
        return f"Arbitration Yr {arb_num}"
    return "FA Eligible (Under Contract)"


def safe_div(n, d):
    return n / d if d and float(d) != 0 else None


def get_current_salary(d):
    cy = int(d.get("current_year") or 0)
    key = f"salary{min(cy, 9)}"
    return d.get(key)


def get_years_remaining(d):
    years = int(d.get("years") or 0)
    current_year = int(d.get("current_year") or 0)
    return max(0, years - current_year)


def _fmt_score_cell(val):
    if val is None:
        return "<td>—</td>"
    v = float(val)
    color = "#1a7a1a" if v >= 70 else "#cc7700" if v >= 40 else "#cc2222"
    return f'<td style="font-weight:bold;color:{color}">{v:.1f}</td>'


def build_war_table_batter(war_rows):
    """Build HTML table rows for batter WAR trend."""
    rows_html = ""
    war_vals = []
    for r in war_rows:
        year, g, pa, ab, h, d, t, hr, bb, k, hp, sf, war = r
        singles = (h or 0) - (d or 0) - (t or 0) - (hr or 0)
        avg = safe_div(h, ab)
        obp = safe_div(
            (h or 0) + (bb or 0) + (hp or 0),
            (ab or 0) + (bb or 0) + (hp or 0) + (sf or 0),
        )
        slg = safe_div(singles + 2 * (d or 0) + 3 * (t or 0) + 4 * (hr or 0), ab)
        ops = (obp + slg) if obp is not None and slg is not None else None
        war_f = float(war) if war is not None else None
        if war_f is not None:
            war_vals.append((int(year), war_f))

        def f3(v):
            return f"{v:.3f}" if v is not None else "—"

        def fw(v):
            return f"{float(v):.1f}" if v is not None else "—"

        war_color = (
            "#1a7a1a" if war_f and war_f >= 3 else "#cc7700" if war_f and war_f >= 1 else "#cc2222"
        )
        rows_html += (
            f"<tr><td>{year}</td><td>{g or 0}</td><td>{pa or 0}</td>"
            f"<td>{hr or 0}</td><td>{f3(avg)}</td><td>{f3(obp)}</td>"
            f"<td>{f3(slg)}</td><td>{f3(ops)}</td>"
            f'<td style="font-weight:bold;color:{war_color}">{fw(war_f)}</td></tr>\n'
        )
    return rows_html, war_vals


def build_war_table_pitcher(war_rows):
    """Build HTML table rows for pitcher WAR trend."""
    rows_html = ""
    war_vals = []
    for r in war_rows:
        year, g, gs, ip, ha, bb, k, er, hra, war = r
        ip_f = float(ip) if ip else 0
        era = safe_div((er or 0) * 9, ip_f)
        whip = safe_div((ha or 0) + (bb or 0), ip_f)
        k9 = safe_div((k or 0) * 9, ip_f)
        war_f = float(war) if war is not None else None
        if war_f is not None:
            war_vals.append((int(year), war_f))

        def f2(v):
            return f"{v:.2f}" if v is not None else "—"

        def f1(v):
            return f"{float(v):.1f}" if v is not None else "—"

        war_color = (
            "#1a7a1a" if war_f and war_f >= 3 else "#cc7700" if war_f and war_f >= 1 else "#cc2222"
        )
        rows_html += (
            f"<tr><td>{year}</td><td>{g or 0}</td><td>{gs or 0}</td>"
            f"<td>{f1(ip_f)}</td><td>{f2(era)}</td><td>{f2(whip)}</td>"
            f"<td>{f1(k9)}</td>"
            f'<td style="font-weight:bold;color:{war_color}">{f1(war_f)}</td></tr>\n'
        )
    return rows_html, war_vals


def _pct(val):
    """Format a 0–1 float as a percentage string, or '—'."""
    if val is None:
        return "—"
    return f"{float(val) * 100:.1f}%"


def _f3(val):
    return f"{float(val):.3f}" if val is not None else "—"


def _f1(val):
    return f"{float(val):.1f}" if val is not None else "—"


def _ev_color(val, pitcher=False):
    """Color for exit velocity — green=good, red=bad. Inverted for pitcher (low EV allowed = good)."""
    if val is None:
        return "#888"
    v = float(val)
    if pitcher:
        return "#1a7a1a" if v < 88 else "#cc7700" if v < 91 else "#cc2222"
    return "#1a7a1a" if v >= 92 else "#cc7700" if v >= 88 else "#cc2222"


def _pct_color(val, good_high=True, good_thresh=0.45, avg_thresh=0.32):
    """Color for percentage metrics. good_high=True means higher is better."""
    if val is None:
        return "#888"
    v = float(val)
    if good_high:
        return "#1a7a1a" if v >= good_thresh else "#cc7700" if v >= avg_thresh else "#cc2222"
    # lower is better (e.g. hard_hit% allowed)
    return "#1a7a1a" if v <= avg_thresh else "#cc7700" if v <= good_thresh else "#cc2222"


def _xwoba_color(val, pitcher=False):
    if val is None:
        return "#888"
    v = float(val)
    if pitcher:
        return "#1a7a1a" if v < 0.290 else "#cc7700" if v < 0.340 else "#cc2222"
    return "#1a7a1a" if v >= 0.360 else "#cc7700" if v >= 0.300 else "#cc2222"


def build_adv_stats_batter_table(rows):
    """Build HTML table rows for batter contact quality trend. Returns (rows_html, most_recent_dict)."""
    if not rows:
        return None, None
    rows_html = ""
    most_recent = None
    for r in rows:
        year, batted_balls, avg_ev, hard_hit_pct, barrel_pct, sweet_spot_pct, xba, xslg, xwoba, wrc_plus, war = r
        if most_recent is None:
            most_recent = dict(
                avg_ev=avg_ev, hard_hit_pct=hard_hit_pct,
                barrel_pct=barrel_pct, xwoba=xwoba,
            )
        ev_color = _ev_color(avg_ev)
        hh_color = _pct_color(hard_hit_pct, good_thresh=0.45, avg_thresh=0.32)
        bar_color = _pct_color(barrel_pct, good_thresh=0.10, avg_thresh=0.04)
        xw_color = _xwoba_color(xwoba)
        rows_html += (
            f"<tr>"
            f"<td>{year}</td>"
            f"<td>{int(batted_balls) if batted_balls else '—'}</td>"
            f'<td style="font-weight:bold;color:{ev_color}">{_f1(avg_ev)}</td>'
            f'<td style="font-weight:bold;color:{hh_color}">{_pct(hard_hit_pct)}</td>'
            f'<td style="font-weight:bold;color:{bar_color}">{_pct(barrel_pct)}</td>'
            f"<td>{_pct(sweet_spot_pct)}</td>"
            f"<td>{_f3(xba)}</td>"
            f"<td>{_f3(xslg)}</td>"
            f'<td style="font-weight:bold;color:{xw_color}">{_f3(xwoba)}</td>'
            f"</tr>\n"
        )
    return rows_html, most_recent


def build_adv_stats_pitcher_table(rows):
    """Build HTML table rows for pitcher contact quality allowed trend. Returns (rows_html, most_recent_dict)."""
    if not rows:
        return None, None
    rows_html = ""
    most_recent = None
    for r in rows:
        year, avg_ev_against, hard_hit_pct_against, barrel_pct_against, xba_against, xwoba_against, fip, xfip, k_pct, bb_pct, war = r
        if most_recent is None:
            most_recent = dict(
                avg_ev_against=avg_ev_against,
                hard_hit_pct_against=hard_hit_pct_against,
                barrel_pct_against=barrel_pct_against,
                xwoba_against=xwoba_against,
            )
        ev_color = _ev_color(avg_ev_against, pitcher=True)
        hh_color = _pct_color(hard_hit_pct_against, good_high=False, good_thresh=0.42, avg_thresh=0.34)
        bar_color = _pct_color(barrel_pct_against, good_high=False, good_thresh=0.10, avg_thresh=0.06)
        xw_color = _xwoba_color(xwoba_against, pitcher=True)
        fip_color = "#1a7a1a" if fip and float(fip) < 3.50 else "#cc7700" if fip and float(fip) < 4.50 else "#cc2222"
        rows_html += (
            f"<tr>"
            f"<td>{year}</td>"
            f'<td style="font-weight:bold;color:{ev_color}">{_f1(avg_ev_against)}</td>'
            f'<td style="font-weight:bold;color:{hh_color}">{_pct(hard_hit_pct_against)}</td>'
            f'<td style="font-weight:bold;color:{bar_color}">{_pct(barrel_pct_against)}</td>'
            f"<td>{_f3(xba_against)}</td>"
            f'<td style="font-weight:bold;color:{xw_color}">{_f3(xwoba_against)}</td>'
            f'<td style="font-weight:bold;color:{fip_color}">{_f2(fip)}</td>'
            f"<td>{_f2(xfip)}</td>"
            f"</tr>\n"
        )
    return rows_html, most_recent


def _f2(val):
    return f"{float(val):.2f}" if val is not None else "—"


def build_comps_table(comp_rows):
    """Build HTML table rows for market comparables."""
    rows_html = ""
    salaries = []
    for r in comp_rows:
        (
            first, last, age, oa, pot, rating, team_abbr,
            years, current_year, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9,
            service_years,
        ) = r
        d = dict(
            years=years, current_year=current_year,
            salary0=s0, salary1=s1, salary2=s2, salary3=s3, salary4=s4,
            salary5=s5, salary6=s6, salary7=s7, salary8=s8, salary9=s9,
        )
        cur_sal = get_current_salary(d)
        yrs_left = get_years_remaining(d)
        rating_f = float(rating or 0)

        if cur_sal and cur_sal > 0:
            salaries.append(int(cur_sal))

        rows_html += (
            f"<tr>"
            f'<td class="left"><b>{first} {last}</b></td>'
            f"<td>{team_abbr or '—'}</td>"
            f"<td>{int(age) if age else '?'}</td>"
            f"<td>{int(oa) if oa else '—'}</td>"
            f"<td>{grade_badge(rating_f)}</td>"
            f"<td>{fmt_salary(cur_sal)}</td>"
            f"<td>{yrs_left}y</td>"
            f"<td>{arb_status_label(service_years)}</td>"
            f"</tr>\n"
        )
    median_sal = sorted(salaries)[len(salaries) // 2] if salaries else None
    return rows_html, median_sal


def _adv_data_dict(most_recent, player_type):
    """Build the adv_* keys for data_dict from the most recent advanced stats row."""
    if most_recent is None:
        if player_type == "pitcher":
            return dict(
                adv_avg_ev_against="—", adv_hard_hit_pct_against="—",
                adv_barrel_pct_against="—", adv_xwoba_against="—",
            )
        return dict(
            adv_avg_ev="—", adv_hard_hit_pct="—",
            adv_barrel_pct="—", adv_xwoba="—",
        )
    if player_type == "pitcher":
        return dict(
            adv_avg_ev_against=_f1(most_recent.get("avg_ev_against")),
            adv_hard_hit_pct_against=_pct(most_recent.get("hard_hit_pct_against")),
            adv_barrel_pct_against=_pct(most_recent.get("barrel_pct_against")),
            adv_xwoba_against=_f3(most_recent.get("xwoba_against")),
        )
    return dict(
        adv_avg_ev=_f1(most_recent.get("avg_ev")),
        adv_hard_hit_pct=_pct(most_recent.get("hard_hit_pct")),
        adv_barrel_pct=_pct(most_recent.get("barrel_pct")),
        adv_xwoba=_f3(most_recent.get("xwoba")),
    )


def _compute_war_vals_batter(war_rows):
    """Extract war_vals list from batter WAR rows without generating HTML."""
    war_vals = []
    for r in war_rows:
        year, g, pa, ab, h, d, t, hr, bb, k, hp, sf, war = r
        war_f = float(war) if war is not None else None
        if war_f is not None:
            war_vals.append((int(year), war_f))
    return war_vals


def _compute_war_vals_pitcher(war_rows):
    """Extract war_vals list from pitcher WAR rows without generating HTML."""
    war_vals = []
    for r in war_rows:
        year, g, gs, ip, ha, bb, k, er, hra, war = r
        war_f = float(war) if war is not None else None
        if war_f is not None:
            war_vals.append((int(year), war_f))
    return war_vals


def _compute_adv_most_recent_batter(rows):
    """Return most-recent batter contact quality dict without generating HTML."""
    if not rows:
        return None
    year, batted_balls, avg_ev, hard_hit_pct, barrel_pct, sweet_spot_pct, xba, xslg, xwoba, wrc_plus, war = rows[0]
    return dict(avg_ev=avg_ev, hard_hit_pct=hard_hit_pct, barrel_pct=barrel_pct, xwoba=xwoba)


def _compute_adv_most_recent_pitcher(rows):
    """Return most-recent pitcher contact quality dict without generating HTML."""
    if not rows:
        return None
    year, avg_ev_against, hard_hit_pct_against, barrel_pct_against, xba_against, xwoba_against, fip, xfip, k_pct, bb_pct, war = rows[0]
    return dict(
        avg_ev_against=avg_ev_against,
        hard_hit_pct_against=hard_hit_pct_against,
        barrel_pct_against=barrel_pct_against,
        xwoba_against=xwoba_against,
    )


def _compute_comp_scalars(comp_rows):
    """Return (median_comp_salary, comp_names) from comp rows without generating HTML."""
    salaries = []
    comp_parts = []
    for r in comp_rows[:5]:
        comp_d = dict(
            years=r[7], current_year=r[8],
            salary0=r[9], salary1=r[10], salary2=r[11], salary3=r[12], salary4=r[13],
            salary5=r[14], salary6=r[15], salary7=r[16], salary8=r[17], salary9=r[18],
        )
        cur_sal = get_current_salary(comp_d)
        sal_str = fmt_salary(cur_sal)
        comp_parts.append(f"{r[0]} {r[1]} (OA:{int(r[3] or 0)}, {sal_str})")
        if cur_sal and cur_sal > 0:
            salaries.append(int(cur_sal))
    median_sal = sorted(salaries)[len(salaries) // 2] if salaries else None
    comp_names = "; ".join(comp_parts)
    return median_sal, comp_names


def _lookup_player_id(conn, first_name, last_name):
    """Lightweight lookup: return player_id for a non-retired, non-free-agent player, or None."""
    row = conn.execute(
        text(
            "SELECT p.player_id FROM players p"
            " JOIN player_ratings pr ON pr.player_id = p.player_id"
            " WHERE p.first_name = :f AND p.last_name = :l"
            " AND p.retired = 0 AND p.free_agent = 0 LIMIT 1"
        ),
        dict(f=first_name, l=last_name),
    ).fetchone()
    return row[0] if row else None


def query_contract_extension(save_name, first_name, last_name):
    """Query all data needed for a contract extension recommendation.

    Returns the complete data dict (with private _* keys for HTML generation),
    or None if the player is not found. Does NOT perform a cache check.
    """
    saves = load_saves_registry()
    save_data = saves.get("saves", {}).get(save_name, {})
    my_team_abbr = save_data.get("my_team_abbr") or "your team"
    my_team_id = int(save_data.get("my_team_id") or 0)

    engine = get_engine(save_name)

    # ── 1. Main player query ────────────────────────────────────────────
    with engine.connect() as conn:
        if my_team_id:
            _row = conn.execute(text(
                "SELECT name, nickname FROM teams WHERE team_id = :tid LIMIT 1"
            ), dict(tid=my_team_id)).mappings().fetchone()
            my_team_name = f"{_row['name']} {_row['nickname']}" if _row else my_team_abbr
        else:
            my_team_name = my_team_abbr

        player_row = conn.execute(
            text("""
            SELECT pr.player_id, pr.first_name, pr.last_name, pr.position,
                   pr.age, pr.oa, pr.pot, pr.player_type,
                   pr.rating_overall, pr.wrc_plus, pr.war,
                   pr.rating_offense, pr.rating_defense, pr.rating_potential,
                   pr.rating_durability, pr.rating_development, pr.rating_clubhouse,
                   pr.rating_baserunning,
                   pr.flag_injury_risk, pr.flag_leader, pr.flag_high_ceiling,
                   pr.prone_overall, pr.work_ethic, pr.intelligence, pr.greed, pr.loyalty,
                   COALESCE(p.personality_play_for_winner, 100) AS play_for_winner,
                   COALESCE(p.local_pop, 0) AS local_pop,
                   COALESCE(p.national_pop, 0) AS national_pop,
                   p.bats, p.throws,
                   t.abbr AS team_abbr,
                   pc.years, pc.current_year, pc.no_trade,
                   pc.salary0, pc.salary1, pc.salary2, pc.salary3, pc.salary4,
                   pc.salary5, pc.salary6, pc.salary7, pc.salary8, pc.salary9,
                   prs.mlb_service_years
            FROM player_ratings pr
            JOIN players p ON p.player_id = pr.player_id
            LEFT JOIN teams t ON t.team_id = p.team_id
            LEFT JOIN players_contract pc ON pc.player_id = pr.player_id
            LEFT JOIN players_roster_status prs ON prs.player_id = pr.player_id
            WHERE p.first_name = :f AND p.last_name = :l
              AND p.retired = 0 AND p.free_agent = 0
            LIMIT 1
            """),
            dict(f=first_name, l=last_name),
        ).fetchone()

    if player_row is None:
        return None

    d = dict(zip(_PLAYER_KEYS, player_row))
    player_id = d["player_id"]
    player_type = d["player_type"]

    # ── 2. WAR trend (last 5 MLB seasons) ───────────────────────────────
    with engine.connect() as conn:
        if player_type == "pitcher":
            war_rows = conn.execute(
                text(f"""
                SELECT year, g, gs, ip, ha, bb, k, er, hra, war
                FROM players_career_pitching_stats
                WHERE player_id = :pid AND split_id = {SPLIT_CAREER_OVERALL}
                  AND league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID}
                ORDER BY year DESC LIMIT 5
                """),
                dict(pid=player_id),
            ).fetchall()
        else:
            war_rows = conn.execute(
                text(f"""
                SELECT year, g, pa, ab, h, d, t, hr, bb, k, hp, sf, war
                FROM players_career_batting_stats
                WHERE player_id = :pid AND split_id = {SPLIT_CAREER_OVERALL}
                  AND league_id = {MLB_LEAGUE_ID} AND level_id = {MLB_LEVEL_ID}
                ORDER BY year DESC LIMIT 5
                """),
                dict(pid=player_id),
            ).fetchall()

    # ── 3. Advanced stats (contact quality) — last 3 years ──────────────
    with engine.connect() as conn:
        try:
            if player_type == "pitcher":
                adv_rows = conn.execute(
                    text("""
                    SELECT year, avg_ev_against, hard_hit_pct_against, barrel_pct_against,
                           xba_against, xwoba_against, fip, xfip, k_pct, bb_pct, war
                    FROM pitcher_advanced_stats_history
                    WHERE player_id = :pid
                    ORDER BY year DESC LIMIT 3
                    """),
                    dict(pid=player_id),
                ).fetchall()
            else:
                adv_rows = conn.execute(
                    text("""
                    SELECT year, batted_balls, avg_ev, hard_hit_pct, barrel_pct,
                           sweet_spot_pct, xba, xslg, xwoba, wrc_plus, war
                    FROM batter_advanced_stats_history
                    WHERE player_id = :pid
                    ORDER BY year DESC LIMIT 3
                    """),
                    dict(pid=player_id),
                ).fetchall()
        except Exception:
            adv_rows = []

    # ── 4. Market comparables ────────────────────────────────────────────
    oa_val = int(d["oa"] or 0)
    position_val = int(d["position"])
    with engine.connect() as conn:
        comp_rows = conn.execute(
            text("""
            SELECT pr.first_name, pr.last_name, pr.age, pr.oa, pr.pot,
                   pr.rating_overall, t.abbr AS team_abbr,
                   pc.years, pc.current_year,
                   pc.salary0, pc.salary1, pc.salary2, pc.salary3, pc.salary4,
                   pc.salary5, pc.salary6, pc.salary7, pc.salary8, pc.salary9,
                   prs.mlb_service_years
            FROM player_ratings pr
            JOIN players p ON p.player_id = pr.player_id
            LEFT JOIN teams t ON t.team_id = p.team_id
            LEFT JOIN players_contract pc ON pc.player_id = pr.player_id
            LEFT JOIN players_roster_status prs ON prs.player_id = pr.player_id
            WHERE pr.player_type = :ptype
              AND pr.position = :pos
              AND pr.oa BETWEEN :oa_lo AND :oa_hi
              AND p.free_agent = 0 AND p.retired = 0
              AND pr.player_id != :pid
            ORDER BY pr.oa DESC, pr.rating_overall DESC
            LIMIT 10
            """),
            dict(
                ptype=player_type,
                pos=position_val,
                oa_lo=oa_val - 5,
                oa_hi=oa_val + 5,
                pid=player_id,
            ),
        ).fetchall()

    # ── Compute scalars ────────────────────────────────────────────────────
    if player_type == "pitcher":
        war_vals = _compute_war_vals_pitcher(war_rows)
        adv_most_recent = _compute_adv_most_recent_pitcher(adv_rows)
    else:
        war_vals = _compute_war_vals_batter(war_rows)
        adv_most_recent = _compute_adv_most_recent_batter(adv_rows)

    median_comp_salary, comp_names = _compute_comp_scalars(comp_rows)

    # Contract details
    years_remaining = get_years_remaining(d)
    current_salary = get_current_salary(d)
    service_years = d.get("mlb_service_years")

    pos_str = POS_MAP.get(d["position"], str(d["position"]))
    avg_war = (
        sum(v for _, v in war_vals) / len(war_vals) if war_vals else None
    )
    war_trend_str = "|".join(f"{yr}:{v:.1f}" for yr, v in war_vals)

    oa_v = int(d.get("oa") or 0)
    pot_v = int(d.get("pot") or 0)
    age_v = int(d.get("age") or 0)
    team_abbr = d.get("team_abbr") or "—"
    rating_overall = float(d.get("rating_overall") or 0)
    wrc_fip = d.get("wrc_plus")
    is_pitcher = player_type == "pitcher"
    key_stat_label = "FIP" if is_pitcher else "wRC+"
    key_stat_str = (
        f"{float(wrc_fip):.2f}" if wrc_fip is not None and is_pitcher
        else str(int(wrc_fip)) if wrc_fip is not None
        else "—"
    )
    war_str = f"{float(d.get('war')):.1f}" if d.get("war") is not None else "—"
    status_label = arb_status_label(service_years)

    greed_v = int(d.get("greed") or 100)
    loyalty_v = int(d.get("loyalty") or 100)
    pfw_v = int(d.get("play_for_winner") or 100)
    local_pop_v = int(d.get("local_pop") or 0)
    national_pop_v = int(d.get("national_pop") or 0)
    prone_v = d.get("prone_overall")

    if age_v < 26:
        age_phase = "Pre-Peak"
    elif age_v <= 30:
        age_phase = "Peak Years"
    elif age_v <= 33:
        age_phase = "Late Peak"
    else:
        age_phase = "Decline Phase"

    data_dict = dict(
        player_name=f"{first_name} {last_name}",
        player_type=player_type,
        position=pos_str,
        team_abbr=team_abbr,
        age=age_v,
        oa=oa_v,
        pot=pot_v,
        oa_pot_gap=pot_v - oa_v,
        age_phase=age_phase,
        rating_overall=round(rating_overall, 1),
        key_stat_label=key_stat_label,
        key_stat=key_stat_str,
        war_current_season=war_str,
        war_trend=war_trend_str,
        avg_war_last_seasons=f"{avg_war:.2f}" if avg_war is not None else "—",
        current_salary=fmt_salary(current_salary),
        years_remaining=years_remaining,
        mlb_service_years=f"{float(service_years):.1f}" if service_years is not None else "—",
        arb_status=status_label,
        greed=greed_v,
        loyalty=loyalty_v,
        play_for_winner=pfw_v,
        local_pop=local_pop_v,
        national_pop=national_pop_v,
        prone_overall=injury_label(prone_v),
        flag_injury_risk=bool(d.get("flag_injury_risk")),
        flag_high_ceiling=bool(d.get("flag_high_ceiling")),
        rating_development=round(float(d.get("rating_development") or 0), 1),
        rating_potential=round(float(d.get("rating_potential") or 0), 1),
        rating_durability=round(float(d.get("rating_durability") or 0), 1),
        median_comp_salary=fmt_salary(median_comp_salary),
        top_comps=comp_names,
        adv_years_available=len(adv_rows),
        my_team_abbr=my_team_abbr,
        my_team_name=my_team_name,
        **_adv_data_dict(adv_most_recent, player_type),
        # Private keys for HTML generation
        _war_rows=war_rows,
        _adv_rows=adv_rows,
        _comp_rows=comp_rows,
        _player_row_d=d,
        _player_id=player_id,
    )

    return data_dict


def generate_contract_extension_report(save_name, first_name, last_name, raw_args=""):
    """Generate a contract extension advisor HTML report.

    Returns (path_str, data_dict) on generation, or (path_str, None) on cache hit.
    Returns (None, None) if the player is not found.
    """
    last_import = get_last_import_time()
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # ── Lightweight player lookup for cache key ──────────────────────────
    engine = get_engine(save_name)
    with engine.connect() as conn:
        player_id = _lookup_player_id(conn, first_name, last_name)
    if player_id is None:
        return None, None

    # ── Cache check ──────────────────────────────────────────────────────
    report_dir = get_reports_dir(save_name, "contract_extensions")
    report_path = report_dir / report_filename(f"contract_{player_id}", dict(raw_args=raw_args.strip().lower()))

    if report_path.exists() and last_import:
        import_dt = datetime.fromisoformat(last_import)
        report_mtime = datetime.fromtimestamp(report_path.stat().st_mtime)
        if report_mtime >= import_dt:
            return str(report_path), None

    # ── Cache miss — run full queries ────────────────────────────────────
    data_dict = query_contract_extension(save_name, first_name, last_name)
    if data_dict is None:
        return None, None

    # Extract private keys for HTML generation
    war_rows = data_dict.pop("_war_rows")
    adv_rows = data_dict.pop("_adv_rows")
    comp_rows = data_dict.pop("_comp_rows")
    d = data_dict.pop("_player_row_d")
    player_id = data_dict.pop("_player_id")

    player_type = d["player_type"]
    pos_str = POS_MAP.get(d["position"], str(d["position"]))

    # ── Build data components ─────────────────────────────────────────────
    if player_type == "pitcher":
        war_rows_html, war_vals = build_war_table_pitcher(war_rows)
        war_thead = (
            "<tr><th>Year</th><th>G</th><th>GS</th><th>IP</th>"
            "<th>ERA</th><th>WHIP</th><th>K/9</th><th>WAR</th></tr>"
        )
        adv_rows_html, adv_most_recent = build_adv_stats_pitcher_table(adv_rows)
        adv_thead = (
            "<tr><th>Year</th><th>Avg EV Against</th><th>Hard Hit%</th>"
            "<th>Barrel%</th><th>xBA Against</th><th>xwOBA Against</th>"
            "<th>FIP</th><th>xFIP</th></tr>"
        )
    else:
        war_rows_html, war_vals = build_war_table_batter(war_rows)
        war_thead = (
            "<tr><th>Year</th><th>G</th><th>PA</th><th>HR</th>"
            "<th>AVG</th><th>OBP</th><th>SLG</th><th>OPS</th><th>WAR</th></tr>"
        )
        adv_rows_html, adv_most_recent = build_adv_stats_batter_table(adv_rows)
        adv_thead = (
            "<tr><th>Year</th><th>Batted Balls</th><th>Avg EV</th>"
            "<th>Hard Hit%</th><th>Barrel%</th><th>Sweet Spot%</th>"
            "<th>xBA</th><th>xSLG</th><th>xwOBA</th></tr>"
        )

    comps_rows_html, median_comp_salary = build_comps_table(comp_rows)

    # Contract details (from player row d)
    years_remaining = get_years_remaining(d)
    current_salary = get_current_salary(d)
    total_years = int(d.get("years") or 0)
    current_year_idx = int(d.get("current_year") or 0)
    service_years = d.get("mlb_service_years")

    # Salary timeline (remaining years of current contract)
    salary_timeline_rows = ""
    for i in range(current_year_idx, min(total_years, 10)):
        yr_label = f"Year {i + 1}"
        sal = d.get(f"salary{i}")
        salary_timeline_rows += f"<tr><td>{yr_label}</td><td>{fmt_salary(sal)}</td></tr>\n"

    # Extract display values from data_dict (already computed by query_contract_extension)
    oa_v = data_dict["oa"]
    pot_v = data_dict["pot"]
    age_v = data_dict["age"]
    team_abbr = data_dict["team_abbr"]
    rating_overall = data_dict["rating_overall"]
    key_stat_label = data_dict["key_stat_label"]
    key_stat_str = data_dict["key_stat"]
    war_str = data_dict["war_current_season"]
    status_label = data_dict["arb_status"]
    age_phase = data_dict["age_phase"]
    greed_v = data_dict["greed"]
    loyalty_v = data_dict["loyalty"]
    pfw_v = data_dict["play_for_winner"]
    local_pop_v = data_dict["local_pop"]
    national_pop_v = data_dict["national_pop"]
    we_v = int(d.get("work_ethic") or 100)
    iq_v = int(d.get("intelligence") or 100)
    prone_v = d.get("prone_overall")

    age_phase_color = (
        "#1a7a1a" if age_v < 26 else
        "#2266cc" if age_v <= 30 else
        "#cc7700" if age_v <= 33 else
        "#cc2222"
    )

    personality_rows = (
        f'<tr><td class="left">Greed</td><td>{greed_v}</td>'
        f'<td style="color:{trait_color(greed_v, invert=True)};font-weight:bold">'
        f"{trait_label(greed_v)}</td></tr>\n"
        f'<tr><td class="left">Loyalty</td><td>{loyalty_v}</td>'
        f'<td style="color:{trait_color(loyalty_v)};font-weight:bold">'
        f"{trait_label(loyalty_v)}</td></tr>\n"
        f'<tr><td class="left">Play for Winner</td><td>{pfw_v}</td>'
        f'<td style="color:{trait_color(pfw_v)};font-weight:bold">'
        f"{trait_label(pfw_v)}</td></tr>\n"
        f'<tr><td class="left">Local Popularity</td>'
        f"<td>{local_pop_v}/6</td>"
        f'<td style="color:{pop_color(local_pop_v)};font-weight:bold">'
        f"{pop_label(local_pop_v)}</td></tr>\n"
        f'<tr><td class="left">National Popularity</td>'
        f"<td>{national_pop_v}/6</td>"
        f'<td style="color:{pop_color(national_pop_v)};font-weight:bold">'
        f"{pop_label(national_pop_v)}</td></tr>\n"
        f'<tr><td class="left">Work Ethic</td><td>{we_v}</td>'
        f'<td style="color:{trait_color(we_v)};font-weight:bold">'
        f"{trait_label(we_v)}</td></tr>\n"
        f'<tr><td class="left">Intelligence</td><td>{iq_v}</td>'
        f'<td style="color:{trait_color(iq_v)};font-weight:bold">'
        f"{trait_label(iq_v)}</td></tr>\n"
        f'<tr><td class="left">Injury Prone</td>'
        f'<td style="color:{injury_color(prone_v)};font-weight:bold" colspan="2">'
        f"{injury_label(prone_v)}</td></tr>\n"
    )

    flags_html = ""
    if d.get("flag_injury_risk"):
        flags_html += '<span class="flag flag-red">⚕ Injury Risk</span> '
    if d.get("flag_high_ceiling"):
        flags_html += '<span class="flag flag-green">📈 High Ceiling</span> '
    if d.get("flag_leader"):
        flags_html += '<span class="flag flag-blue">🏆 Leader</span> '
    if greed_v > 160:
        flags_html += '<span class="flag flag-yellow">💰 High Greed</span> '
    if loyalty_v > 160:
        flags_html += '<span class="flag flag-green">❤ Loyal</span> '
    if we_v > 160:
        flags_html += '<span class="flag flag-blue">⚡ Elite Work Ethic</span> '
    if iq_v > 160:
        flags_html += '<span class="flag flag-blue">🧠 High IQ</span> '
    if d.get("no_trade"):
        flags_html += '<span class="flag flag-yellow">🔒 No-Trade Clause</span> '

    player_name_esc = html_mod.escape(f"{first_name} {last_name}")

    _ootp_meta = (
        '<meta name="ootp-skill" content="contract-extension">'
        f'<meta name="ootp-args" content="{html_mod.escape(first_name)} {html_mod.escape(last_name)}">'
        '<meta name="ootp-args-display" content="">'
        f'<meta name="ootp-save" content="{html_mod.escape(save_name)}">'
    )

    # ── Assemble HTML ─────────────────────────────────────────────────────
    html_doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Contract Extension — {player_name_esc}</title>
{_ootp_meta}
<style>{get_report_css("980px")}</style>
</head><body>
<div class="container">

<div class="page-header">
  <div class="header-top">
    <div>
      <div class="player-name">{player_name_esc}</div>
      <div class="player-meta">
        {pos_str} &bull; {team_abbr} &bull; Age {age_v}
        &bull; <span class="badge badge-oa">OA {oa_v}</span>
        &nbsp;<span class="badge badge-pot">POT {pot_v}</span>
        &bull; <span style="color:#f0c040;font-weight:bold">{status_label}</span>
      </div>
      <div class="player-meta" style="margin-top:6px">
        {key_stat_label}: <b style="color:#f0c040">{key_stat_str}</b>
        &bull; WAR: <b style="color:#f0c040">{war_str}</b>
        &bull; Age Phase: <span style="color:{age_phase_color};font-weight:bold">{age_phase}</span>
      </div>
      <div class="flags" style="margin-top:8px">{flags_html if flags_html else '<span style="color:#888;font-size:12px">No flags</span>'}</div>
    </div>
    <div style="text-align:right">
      <div class="grade-badge">{letter_grade(rating_overall)}</div>
      <div style="font-size:14px;color:#f0c040;font-weight:bold">{rating_overall:.1f}</div>
    </div>
  </div>
  <div class="import-ts">Last DB import: {last_import or 'unknown'} &bull; Generated: {generated_at}</div>
</div>

<!-- ── Analysis ─────────────────────────────────────── -->
<div class="section">
  <div class="section-title">Extension Recommendation</div>
  <!-- CONTRACT_EXTENSION_SUMMARY -->
</div>

<!-- ── Contract Status ──────────────────────────────── -->
<div class="section">
  <div class="section-title">Current Contract</div>
  <div style="display:flex;gap:32px;flex-wrap:wrap">
    <table style="width:auto;min-width:240px">
      <tr><th class="left" colspan="2">Contract Details</th></tr>
      <tr><td class="left">Current Salary</td><td><b>{fmt_salary(current_salary)}</b></td></tr>
      <tr><td class="left">Years Remaining</td><td><b>{years_remaining}</b></td></tr>
      <tr><td class="left">Service Time</td><td><b>{f"{float(service_years):.1f} yrs" if service_years is not None else "—"}</b></td></tr>
      <tr><td class="left">Status</td><td><b>{status_label}</b></td></tr>
      <tr><td class="left">No-Trade Clause</td><td><b>{"Yes" if d.get("no_trade") else "No"}</b></td></tr>
    </table>
    <table style="width:auto;min-width:180px">
      <tr><th class="left" colspan="2">Salary Timeline</th></tr>
      {salary_timeline_rows if salary_timeline_rows else '<tr><td colspan="2" style="color:#888">No contract data</td></tr>'}
    </table>
  </div>
</div>

<!-- ── Performance History ───────────────────────────── -->
<div class="section">
  <div class="section-title">Performance History (Last 5 MLB Seasons)</div>
  {f'<table>{war_thead}{war_rows_html}</table>' if war_rows_html else '<p style="color:#888;font-size:13px">No MLB career data yet.</p>'}
</div>

<!-- ── Contact Quality ──────────────────────────────── -->
<div class="section">
  <div class="section-title">Contact Quality (Year-over-Year)</div>
  {f'<table>{adv_thead}{adv_rows_html}</table>' if adv_rows_html else '<p style="color:#888;font-size:13px">Contact quality data builds year-over-year as the sim progresses.</p>'}
</div>

<!-- ── Market Comparables ───────────────────────────── -->
<div class="section">
  <div class="section-title">Market Comparables (OA {oa_v - 5}–{oa_v + 5}, {pos_str})</div>
  {f"""<table>
  <tr><th class="left">Name</th><th>Team</th><th>Age</th><th>OA</th>
      <th>Rating</th><th>Salary</th><th>Yrs Left</th><th>Status</th></tr>
  {comps_rows_html}
  </table>
  <div style="font-size:12px;color:#888;margin-top:6px">
    Median comparable salary: <b>{fmt_salary(median_comp_salary)}</b>
  </div>""" if comps_rows_html else '<p style="color:#888;font-size:13px">No comparable contracts found.</p>'}
</div>

<!-- ── Personality & Risk ────────────────────────────── -->
<div class="section">
  <div class="section-title">Personality &amp; Risk Profile</div>
  <table style="width:auto;min-width:280px">
    <tr><th class="left">Trait</th><th>Score</th><th>Assessment</th></tr>
    {personality_rows}
  </table>
</div>

</div>
</body></html>"""

    write_report_html(report_path, html_doc)

    return str(report_path), data_dict
