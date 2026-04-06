#!/usr/bin/env python3
"""MCP server for OOTP Baseball — exposes OOTP data tools to Claude Desktop."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mcp.server.fastmcp import FastMCP
from mcp_cache import cache_get, cache_put
from queries import (
    POS_MAP, BATS_MAP, THROWS_MAP, POS_CODE,
    _fmt, _pct,
    _active_save, _load_saves,
    query_standings, query_player, query_draft_prospects,
    query_waiver_claim, query_contract_extension,
    query_lineup, query_trade_targets,
    query_free_agents, query_player_rating,
)

mcp = FastMCP("OOTP Baseball")


# ── Shared helpers ────────────────────────────────────────────────────────────

def _get_import_time(save_name: str) -> str:
    saves = _load_saves()
    return saves.get("saves", {}).get(save_name, {}).get("last_import", "")


# ── Formatters ────────────────────────────────────────────────────────────────

def _format_standings(rows: list) -> str:
    if not rows:
        return "No standings data found."
    divs = {}
    for r in rows:
        key = (r["sub_league_id"], r["division_id"], r["division"])
        if key not in divs:
            divs[key] = []
        gb_raw = r.get("gb")
        gb = f"+{float(gb_raw):.1f}" if gb_raw and float(gb_raw) > 0 else "—"
        pct = _fmt(r["pct"], ".3f")
        divs[key].append(
            f"  {int(r['pos'])}.  {r['name']} {r['nickname']:<16} {r['w']}-{r['l']}  .{pct[2:]}  {gb}"
        )
    lines = []
    for (sl, _, div_name), teams in sorted(divs.items()):
        label = "American League" if sl == 0 else "National League"
        lines.append(f"\n{label} — {div_name}")
        lines.extend(teams)
    return "\n".join(lines)


def _format_player_stats(data: dict) -> str:
    pos = POS_MAP.get(data["position"], "?")
    bats = BATS_MAP.get(data["bats"], "R")
    throws = THROWS_MAP.get(data["throws"], "R")
    fa_label = " [FREE AGENT]" if data.get("free_agent") else ""
    ptype = data["player_type"]

    flags = []
    if data.get("flag_injury_risk"):
        flags.append("Injury Risk")
    if data.get("flag_leader"):
        flags.append("Leader")
    if data.get("flag_high_ceiling"):
        flags.append("High Ceiling")

    lines = [
        f"{data['first_name']} {data['last_name']} | {pos} | {data['team_abbr']}{fa_label} | Age {data['age']} | B/T:{bats}/{throws}",
        f"OA:{data['oa']}  POT:{data['pot']}  Rating:{_fmt(data['rating_overall'])}/100",
        "",
        "Composite Ratings (0–100):",
    ]

    if ptype == "pitcher":
        lines.append(
            f"  Defense:{_fmt(data['rating_defense'], '.0f')}  "
            f"Potential:{_fmt(data['rating_potential'], '.0f')}  "
            f"Durability:{_fmt(data['rating_durability'], '.0f')}  "
            f"Clubhouse:{_fmt(data['rating_clubhouse'], '.0f')}  "
            f"Development:{_fmt(data['rating_development'], '.0f')}"
        )
    else:
        lines.append(
            f"  Offense:{_fmt(data['rating_offense'], '.0f')}  "
            f"Contact:{_fmt(data['rating_contact_quality'], '.0f')}  "
            f"Discipline:{_fmt(data['rating_discipline'], '.0f')}  "
            f"Defense:{_fmt(data['rating_defense'], '.0f')}  "
            f"Baserunning:{_fmt(data['rating_baserunning'], '.0f')}"
        )
        lines.append(
            f"  Potential:{_fmt(data['rating_potential'], '.0f')}  "
            f"Durability:{_fmt(data['rating_durability'], '.0f')}  "
            f"Clubhouse:{_fmt(data['rating_clubhouse'], '.0f')}  "
            f"Development:{_fmt(data['rating_development'], '.0f')}"
        )

    adv = data.get("adv")
    if adv:
        lines.append("")
        if ptype == "pitcher":
            lines.append(
                f"Pitching: ERA:{_fmt(adv.get('era'), '.2f')}  FIP:{_fmt(adv.get('fip'), '.2f')}  "
                f"xFIP:{_fmt(adv.get('xfip'), '.2f')}  WHIP:{_fmt(adv.get('whip'), '.2f')}  WAR:{_fmt(adv.get('war'))}"
            )
            lines.append(
                f"  K%:{_pct(adv.get('k_pct'))}  BB%:{_pct(adv.get('bb_pct'))}  K-BB%:{_pct(adv.get('k_bb_pct'))}"
            )
            lines.append(
                f"  K/9:{_fmt(adv.get('k_9'))}  BB/9:{_fmt(adv.get('bb_9'))}  HR/9:{_fmt(adv.get('hr_9'), '.2f')}  "
                f"GB%:{_pct(adv.get('gb_pct'))}"
            )
            lines.append(
                f"  G:{adv.get('g')}  GS:{adv.get('gs')}  IP:{_fmt(adv.get('ip'))}  "
                f"HH%:{_pct(adv.get('hard_hit_pct_against'))}  Brl%:{_pct(adv.get('barrel_pct_against'))}  "
                f"xwOBA-against:{_fmt(adv.get('xwoba_against'), '.3f')}"
            )
        else:
            lines.append(
                f"Batting: BA:{_fmt(adv.get('ba'), '.3f')}  OBP:{_fmt(adv.get('obp'), '.3f')}  "
                f"SLG:{_fmt(adv.get('slg'), '.3f')}  OPS:{_fmt(adv.get('ops'), '.3f')}  "
                f"wRC+:{_fmt(adv.get('wrc_plus'), '.0f')}  OPS+:{_fmt(adv.get('ops_plus'), '.0f')}  WAR:{_fmt(adv.get('war'))}"
            )
            lines.append(
                f"  K%:{_pct(adv.get('k_pct'))}  BB%:{_pct(adv.get('bb_pct'))}  "
                f"ISO:{_fmt(adv.get('iso'), '.3f')}  BABIP:{_fmt(adv.get('babip'), '.3f')}"
            )
            lines.append(
                f"  AvgEV:{_fmt(adv.get('avg_ev'))}  HH%:{_pct(adv.get('hard_hit_pct'))}  "
                f"Brl%:{_pct(adv.get('barrel_pct'))}  xwOBA:{_fmt(adv.get('xwoba'), '.3f')}"
            )
            lines.append(
                f"  G:{adv.get('g')}  PA:{adv.get('pa')}  HR:{adv.get('hr')}  SB:{adv.get('sb')}"
            )

    if flags:
        lines.append(f"\nFlags: {', '.join(flags)}")
    return "\n".join(lines)


def _format_player_rating(data: dict) -> str:
    pos_name = data.get("pos_name", "?")
    adjusted = data.get("adjusted", False)
    final_rating = data.get("final_rating", data.get("rating_overall"))

    def _injury(val):
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

    def _trait(val):
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

    lines = [
        f"{data['first_name']} {data['last_name']} | {pos_name} | {data['team_abbr']} | "
        f"Age {data['age']} | B/T:{data['bats_str']}/{data['throws_str']}",
        f"OA:{data['oa']}  POT:{data['pot']}  Rating:{_fmt(final_rating)}/100"
        + (" (adjusted)" if adjusted else "")
        + f"  (#{data['rank']} of {data['rank_total']} at {pos_name})",
        f"{data['key_stat_label']}:{data['key_stat_val']}  WAR:{data['war_val']}",
        "",
        "Component Ratings (0–100):",
    ]

    scores = data.get("scores", {})
    for key, label in data.get("component_labels", []):
        score = scores.get(key, 0)
        bar = "█" * int(score / 5)
        lines.append(f"  {label:<22} {_fmt(score, '.1f'):>5}  {bar}")

    lines.append("")
    lines.append(
        f"Personality: WorkEthic={_trait(data.get('we_v'))}  "
        f"Intelligence={_trait(data.get('iq_v'))}  "
        f"Greed={_trait(data.get('greed_v'))}  "
        f"Loyalty={_trait(data.get('loyalty_v'))}"
    )
    lines.append(
        f"Injury: {_injury(data.get('prone_overall_v'))}  "
        f"(Leg:{_injury(data.get('prone_leg_v'))}  "
        f"Back:{_injury(data.get('prone_back_v'))}  "
        f"Arm:{_injury(data.get('prone_arm_v'))})"
    )

    flags = []
    if data.get("flag_injury_risk"):
        flags.append("⚠ Injury Risk")
    if data.get("flag_leader"):
        flags.append("★ Leader")
    if data.get("flag_high_ceiling"):
        flags.append("★ High Ceiling")
    if flags:
        lines.append(f"\nFlags: {', '.join(flags)}")

    return "\n".join(lines)


def _format_free_agents(rows: list) -> str:
    if not rows:
        return "No free agents found matching those criteria."
    header = f"{'Name':<22} {'Pos':>4} {'Age':>4} {'OA':>4} {'POT':>4} {'Rating':>7} {'wRC+':>6} {'WAR':>5}  Flags"
    lines = [f"Free Agents ({len(rows)} results)\n", header, "-" * 72]
    for r in rows:
        pos = POS_MAP.get(int(r.get("position") or 0), "?")
        name = f"{r['first_name']} {r['last_name']}"[:22]
        key = _fmt(r.get("wrc_plus"), ".0f")
        fl = ("⚠" if r.get("flag_injury_risk") else " ") + ("★" if r.get("flag_high_ceiling") else " ")
        lines.append(
            f"{name:<22} {pos:>4} {str(r.get('age', '?')):>4} {str(r.get('oa', '?')):>4} {str(r.get('pot', '?')):>4}"
            f" {_fmt(r.get('rating_overall')):>7} {key:>6} {_fmt(r.get('war')):>5}  {fl}"
        )
    return "\n".join(lines)


def _format_draft_prospects(rows: list, pool: str) -> str:
    if not rows:
        return f"No {pool} prospects found matching those criteria."
    header = (
        f"{'Name':<22} {'Pos':>4} {'Age':>4} {'OA':>4} {'Overall':>8} "
        f"{'Ceiling':>8} {'Tools':>6} {'Dev':>5} {'Def':>5}"
    )
    lines = [f"{pool.upper()} Prospects ({len(rows)} results)\n", header, "-" * 70]
    for r in rows:
        pos = POS_MAP.get(int(r.get("position") or 0), "?")
        name = f"{r['first_name']} {r['last_name']}"[:22]
        lines.append(
            f"{name:<22} {pos:>4} {str(r.get('age', '?')):>4} {str(r.get('oa', '?')):>4}"
            f" {_fmt(r.get('rating_overall')):>8}"
            f" {_fmt(r.get('rating_ceiling')):>8}"
            f" {_fmt(r.get('rating_tools')):>6}"
            f" {_fmt(r.get('rating_development')):>5}"
            f" {_fmt(r.get('rating_defense')):>5}"
        )
    return "\n".join(lines)


def _format_waiver_claim(data: dict) -> str:
    cand_rating = _fmt(data.get("rating_overall"), ".1f")
    best_name = data.get("best_incumbent_name", "None")
    best_rating = _fmt(data.get("best_incumbent_rating"), ".1f")
    worst_name = data.get("worst_incumbent_name", "None")
    worst_rating = _fmt(data.get("worst_incumbent_rating"), ".1f")
    delta_best = data.get("rating_vs_best")
    delta_worst = data.get("rating_vs_worst")

    status_parts = []
    if data.get("is_on_waivers"):
        status_parts.append(f"Waivers ({data.get('days_waivers_left', 0)}d left)")
    if data.get("is_dfa"):
        status_parts.append(f"DFA ({data.get('dfa_days_left', 0)}d left)")
    status = ", ".join(status_parts) or "Roster"

    adv_lines = []
    if data.get("player_type") == "pitcher":
        if data.get("adv_era") is not None:
            adv_lines.append(
                f"  ERA:{data['adv_era']}  FIP:{data.get('adv_fip', '—')}  "
                f"xFIP:{data.get('adv_xfip', '—')}  K-BB%:{data.get('adv_k_bb_pct', '—')}"
            )
    else:
        if data.get("adv_avg_ev") is not None:
            adv_lines.append(
                f"  wRC+ vs LHP:{data.get('adv_wrc_plus_vs_lhp', '—')}  "
                f"wRC+ vs RHP:{data.get('adv_wrc_plus_vs_rhp', '—')}"
            )
            adv_lines.append(
                f"  AvgEV:{data.get('adv_avg_ev', '—')}  HH%:{data.get('adv_hard_hit_pct', '—')}  "
                f"Brl%:{data.get('adv_barrel_pct', '—')}  xwOBA:{data.get('adv_xwoba', '—')}"
            )

    flex = data.get("positional_flexibility", [])
    flex_str = ", ".join(flex) if flex else "None"

    lines = [
        f"Waiver Claim: {data['player_name']}",
        f"{data['position']} | {data['team_abbr']} | Age {data['age']} | OA:{data['oa']} POT:{data['pot']}",
        f"Rating: {cand_rating}/100  |  Status: {status}",
        f"Contract: {data.get('current_salary', '—')} × {data.get('years_remaining', '?')}yr  "
        f"({data.get('arb_status', '—')})",
        "",
        f"vs Your Roster ({data.get('num_incumbents', 0)} incumbents at this position):",
        f"  Best:  {best_name} ({best_rating}) — delta: "
        f"{'+' if delta_best and delta_best > 0 else ''}{_fmt(delta_best, '.1f')}",
        f"  Worst: {worst_name} ({worst_rating}) — delta: "
        f"{'+' if delta_worst and delta_worst > 0 else ''}{_fmt(delta_worst, '.1f')}",
        "",
        f"Personality: Greed={data.get('greed_label', '—')}  Loyalty={data.get('loyalty_label', '—')}",
        f"Injury: {data.get('prone_label', '—')}  "
        f"{'⚠ Injury Risk  ' if data.get('flag_injury_risk') else ''}"
        f"{'★ High Ceiling  ' if data.get('flag_high_ceiling') else ''}",
        f"40-man: {data.get('roster_count', '?')}/40"
        f"{'  → needs DFA to claim' if data.get('needs_dfa_to_claim') else ''}",
        f"Positional flexibility: {flex_str}",
    ]
    if adv_lines:
        lines.append("")
        lines.append("Advanced stats:")
        lines.extend(adv_lines)
    return "\n".join(lines)


def _format_contract_extension(data: dict) -> str:
    lines = [
        f"Contract Extension: {data.get('player_name', '?')}",
        f"{data.get('position', '?')} | {data.get('my_team_abbr', '?')} | "
        f"Age {data.get('age', '?')} | OA:{data.get('oa', '?')} POT:{data.get('pot', '?')}",
        f"Rating: {_fmt(data.get('rating_overall'), '.1f')}/100",
        "",
        f"Current: {data.get('current_salary', '—')} / {data.get('years_remaining', '?')}yr remaining  "
        f"Service: {data.get('mlb_service_years', '—')}yr  ({data.get('arb_status', '—')})",
        "",
        f"Key Stats: {data.get('key_stat_label', '?')} = {data.get('key_stat', '—')}  "
        f"WAR(season): {data.get('war_current_season', '—')}  "
        f"WAR(trend): {data.get('war_trend', '—')}  "
        f"Avg WAR/yr: {data.get('avg_war_last_seasons', '—')}",
        "",
        f"Personality: Greed={data.get('greed', '?')}  Loyalty={data.get('loyalty', '?')}  "
        f"Phase: {data.get('age_phase', '—')}",
        f"Injury: {data.get('prone_overall', '—')}  "
        f"{'⚠ Injury Risk  ' if data.get('flag_injury_risk') else ''}"
        f"{'★ High Ceiling  ' if data.get('flag_high_ceiling') else ''}",
        f"Market comp (median AAV): {data.get('median_comp_salary', '—')}",
        f"Comps: {data.get('top_comps') or 'None'}",
    ]
    return "\n".join(lines)


def _format_lineup(data: dict) -> str:
    lineup = json.loads(data.get("lineup_json", "[]"))
    lines = [
        f"Lineup — {data['team_name']} ({data['team_abbr']}) | {data.get('phil_label', data.get('philosophy', ''))} | {data.get('hand_label', 'Neutral')}",
        f"Avg wRC+: {_fmt(data.get('avg_lineup_wrc_plus'), '.0f')}  |  L/R: {data.get('lhb_count', 0)}L / {data.get('rhb_count', 0)}R",
        "",
    ]
    for p in lineup:
        lines.append(
            f"  {p['slot']}. {p['name']:<22} {p['pos']:<4} {p['bats']}  "
            f"wOBA:{_fmt(p.get('woba'), '.3f')}  wRC+:{_fmt(p.get('wrc_plus'), '.0f')}"
        )
    if data.get("hot_players") and data["hot_players"] != "None":
        lines.append(f"\nHot: {data['hot_players']}")
    if data.get("cold_stars") and data["cold_stars"] != "None":
        lines.append(f"Cold: {data['cold_stars']}")
    if data.get("excluded_players") and data["excluded_players"] != "None":
        lines.append(f"Excluded: {data['excluded_players']}")
    return "\n".join(lines)


def _format_trade_targets(data: dict, offer_label: str, mode: str) -> str:
    offered = data.get("offered", [])
    targets = data.get("targets", [])

    lines = [f"Trade Targets — {mode.title()}: {offer_label}", ""]

    if offered:
        lines.append("Offering:")
        for p in offered:
            pos = POS_MAP.get(int(p.get("position") or 0), "?")
            lines.append(
                f"  {p.get('first_name', '')} {p.get('last_name', '')} | {pos} | "
                f"Age {p.get('age', '?')} | OA:{p.get('oa', '?')} | Rating:{_fmt(p.get('rating_overall'), '.1f')}"
            )
    lines.append("")

    lines.append(f"Target candidates ({len(targets)} results):")
    lines.append(f"  {'Name':<22} {'Pos':>4} {'Age':>4} {'OA':>4} {'Rating':>7} {'wRC+':>6} {'WAR':>5}")
    lines.append("  " + "-" * 55)
    for p in targets:
        pos = POS_MAP.get(int(p.get("position") or 0), "?")
        name = f"{p.get('first_name', '')} {p.get('last_name', '')}"[:22]
        lines.append(
            f"  {name:<22} {pos:>4} {str(p.get('age', '?')):>4} {str(p.get('oa', '?')):>4}"
            f" {_fmt(p.get('rating_overall'), '.1f'):>7} {_fmt(p.get('wrc_plus'), '.0f'):>6} {_fmt(p.get('war'), '.1f'):>5}"
        )
    return "\n".join(lines)


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_save_info() -> str:
    """Get the current active OOTP save, your managed team, and last import timestamp."""
    saves = _load_saves()
    active = saves.get("active")
    if not active:
        return "No active save configured. Run `./import.sh <save-name>` to import a save first."
    info = saves["saves"].get(active, {})
    lines = [
        f"Active save: {active}",
        f"Team: {info.get('my_team_abbr', '?')} (team_id={info.get('my_team_id', '?')})",
        f"Last import: {info.get('last_import', 'unknown')}",
        "",
        "Other saves:",
    ]
    for name, s in saves["saves"].items():
        if name != active:
            lines.append(f"  {name} — last import: {s.get('last_import', 'unknown')}")
    return "\n".join(lines)


@mcp.tool()
def standings() -> str:
    """Get current MLB division standings for all 6 divisions."""
    save = _active_save()
    import_time = _get_import_time(save)
    args = {}
    hit = cache_get("standings", args, save, import_time)
    if hit:
        return hit
    rows = query_standings(save)
    result = _format_standings(rows)
    cache_put("standings", args, save, result, import_time)
    return result


@mcp.tool()
def player_stats(first_name: str, last_name: str) -> str:
    """
    Look up a player's bio, composite ratings, and advanced stats.
    Uses the player_ratings table (MLB-level players only).
    """
    save = _active_save()
    import_time = _get_import_time(save)
    args = dict(first_name=first_name, last_name=last_name)
    hit = cache_get("player_stats", args, save, import_time)
    if hit:
        return hit
    data = query_player(save, first_name, last_name)
    if data is None:
        return f"Player not found in MLB roster: {first_name} {last_name}"
    result = _format_player_stats(data)
    cache_put("player_stats", args, save, result, import_time)
    return result


@mcp.tool()
def player_rating(first_name: str, last_name: str) -> str:
    """
    Show a detailed rating breakdown for an MLB-level player.
    Displays component scores, personality, injury profile, and positional rank.
    """
    save = _active_save()
    import_time = _get_import_time(save)
    args = dict(first_name=first_name, last_name=last_name)
    hit = cache_get("player_rating", args, save, import_time)
    if hit:
        return hit
    data = query_player_rating(save, first_name, last_name)
    if data is None:
        return f"Player not found in MLB roster: {first_name} {last_name}"
    result = _format_player_rating(data)
    cache_put("player_rating", args, save, result, import_time)
    return result


@mcp.tool()
def free_agents(
    position: str = "",
    max_age: int = 99,
    min_rating: float = 0.0,
    player_type: str = "",
    extra_where: str = "",
    limit: int = 20,
) -> str:
    """
    Search for free agents.

    position:    Position abbreviation — C, 1B, 2B, 3B, SS, LF, CF, RF, P, or empty for all.
    max_age:     Maximum player age.
    min_rating:  Minimum rating_overall (0–100 scale).
    player_type: "batter", "pitcher", or empty for all.
    extra_where: Optional SQL fragment appended with AND (uses player_ratings columns with pr alias).
    limit:       Max results (default 20).
    """
    save = _active_save()
    import_time = _get_import_time(save)
    args = dict(position=position, max_age=max_age, min_rating=min_rating,
                player_type=player_type, extra_where=extra_where, limit=limit)
    hit = cache_get("free_agents", args, save, import_time)
    if hit:
        return hit

    filters = ["1=1"]
    if position:
        pos_code = POS_CODE.get(position.upper())
        if pos_code:
            filters.append(f"pr.position = {pos_code}")
    if max_age < 99:
        filters.append(f"pr.age <= {int(max_age)}")
    if min_rating > 0:
        filters.append(f"pr.rating_overall >= {float(min_rating)}")
    if player_type in ("batter", "pitcher"):
        filters.append(f"pr.player_type = '{player_type}'")
    if extra_where:
        filters.append(f"({extra_where})")

    where_clause = " AND ".join(filters)
    rows = query_free_agents(save, "search", where_clause, limit=limit)
    result = _format_free_agents(rows)
    cache_put("free_agents", args, save, result, import_time)
    return result


@mcp.tool()
def draft_prospects(
    pool: str = "draft",
    position: str = "",
    max_age: int = 99,
    min_ceiling: float = 0.0,
    extra_where: str = "",
    limit: int = 20,
) -> str:
    """
    Search draft or IFA prospects.

    pool:        "draft" for the draft pool, "ifa" for international free agents.
    position:    Position abbreviation or empty for all.
    max_age:     Maximum age.
    min_ceiling: Minimum ceiling rating (0–100 scale).
    extra_where: Optional SQL fragment (dr alias for draft_ratings, ir alias for ifa_ratings).
    limit:       Max results (default 20).
    """
    save = _active_save()
    import_time = _get_import_time(save)
    args = dict(pool=pool, position=position, max_age=max_age,
                min_ceiling=min_ceiling, extra_where=extra_where, limit=limit)
    hit = cache_get("draft_prospects", args, save, import_time)
    if hit:
        return hit

    alias = "ir" if pool.lower() == "ifa" else "dr"
    filters = ["1=1"]
    if position:
        pos_code = POS_CODE.get(position.upper())
        if pos_code:
            filters.append(f"{alias}.position = {pos_code}")
    if max_age < 99:
        filters.append(f"{alias}.age <= {int(max_age)}")
    if min_ceiling > 0:
        filters.append(f"{alias}.rating_ceiling >= {float(min_ceiling)}")
    if extra_where:
        filters.append(f"({extra_where})")

    where_clause = " AND ".join(filters)
    rows = query_draft_prospects(save, "search", where_clause, limit=limit, pool=pool)
    result = _format_draft_prospects(rows, pool)
    cache_put("draft_prospects", args, save, result, import_time)
    return result


@mcp.tool()
def waiver_claim(first_name: str, last_name: str) -> str:
    """
    Evaluate whether to claim a player off waivers or from DFA.
    Compares the candidate against your team's incumbents at the same position,
    assesses contract obligation and injury risk, and provides a recommendation.
    """
    save = _active_save()
    import_time = _get_import_time(save)
    args = dict(first_name=first_name, last_name=last_name)
    hit = cache_get("waiver_claim", args, save, import_time)
    if hit:
        return hit
    data = query_waiver_claim(save, first_name, last_name)
    if data is None:
        return f"Player not found: {first_name} {last_name}"
    result = _format_waiver_claim(data)
    cache_put("waiver_claim", args, save, result, import_time)
    return result


@mcp.tool()
def contract_extension(first_name: str, last_name: str) -> str:
    """
    Recommend contract extension terms for a player on your roster.
    Projects WAR, checks market comparables, and accounts for personality.
    """
    save = _active_save()
    import_time = _get_import_time(save)
    args = dict(first_name=first_name, last_name=last_name)
    hit = cache_get("contract_extension", args, save, import_time)
    if hit:
        return hit
    data = query_contract_extension(save, first_name, last_name)
    if data is None:
        return f"Player not found on your roster: {first_name} {last_name}"
    result = _format_contract_extension(data)
    cache_put("contract_extension", args, save, result, import_time)
    return result


@mcp.tool()
def lineup_optimizer(
    philosophy: str = "modern",
    vs_hand: str = "",
) -> str:
    """
    Suggest the optimal batting order for your team.

    philosophy: modern | traditional | platoon | hot-hand
    vs_hand:    L (vs left-handed pitcher), R (vs right-handed pitcher), or empty for neutral.
    """
    save = _active_save()
    import_time = _get_import_time(save)
    hand = vs_hand.upper()[:1] if vs_hand else ""
    if hand not in ("L", "R"):
        hand = ""
    # Default to platoon when a handedness matchup is specified
    if hand and philosophy == "modern":
        philosophy = "platoon"
    args = dict(philosophy=philosophy, vs_hand=hand)
    hit = cache_get("lineup_optimizer", args, save, import_time)
    if hit:
        return hit
    data = query_lineup(save, philosophy=philosophy, opponent_hand=hand or None)
    if data is None:
        return "Could not generate lineup — team not found."
    result = _format_lineup(data)
    cache_put("lineup_optimizer", args, save, result, import_time)
    return result


@mcp.tool()
def trade_targets(
    offer_label: str,
    offered_where: str,
    target_where: str,
    mode: str = "offering",
    target_join: str = "",
    limit: int = 15,
) -> str:
    """
    Find trade candidates.

    offer_label:   Human-readable label for what you're offering, e.g. "Jackson Jobe".
    offered_where: SQL fragment identifying the offered player(s) — e.g. "p.last_name='Jobe'".
                   In "offering" mode, filters YOUR players. In "acquiring" mode, filters THEIR players.
    target_where:  SQL fragment for the return side — e.g. "pr.position=6 AND pr.age<=28".
    mode:          "offering" (trading away) or "acquiring" (targeting someone else's player).
    target_join:   Optional JOIN clause for advanced stats (e.g. JOIN batter_advanced_stats bas...).
    limit:         Max target results (default 15).

    Column reference for WHERE/JOIN:
      pr.* — player_ratings (rating_overall, position, age, oa, pot, player_type, wrc_plus, war, ...)
      p.*  — players (free_agent, retired, team_id, league_id, bats, throws, ...)
    """
    save = _active_save()
    import_time = _get_import_time(save)
    args = dict(offer_label=offer_label, offered_where=offered_where,
                target_where=target_where, mode=mode, target_join=target_join, limit=limit)
    hit = cache_get("trade_targets", args, save, import_time)
    if hit:
        return hit

    saves = _load_saves()
    my_team_id = int(saves["saves"].get(save, {}).get("my_team_id", 0))
    data = query_trade_targets(
        save,
        offer_label=offer_label,
        offered_where=offered_where,
        target_where=target_where,
        my_team_id=my_team_id,
        mode=mode,
        target_join=target_join,
        limit=limit,
    )
    result = _format_trade_targets(data, offer_label, mode)
    cache_put("trade_targets", args, save, result, import_time)
    return result


if __name__ == "__main__":
    mcp.run()
