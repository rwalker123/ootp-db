"""Cache check, HTML section builders, and report entry point for the waiver wire evaluator."""

import html
from datetime import datetime
from pathlib import Path

from ootp_db_constants import POS_MAP, BATS_MAP, THROWS_MAP, ROLE_MAP
from report_write import write_report_html, report_filename
from shared_css import (
    get_engine,
    get_last_import_iso_for_save,
    get_report_css,
    get_reports_dir,
)
from sqlalchemy import text

from .formatting import (
    fmt_salary,
    get_current_salary,
    get_years_remaining,
    letter_grade,
    score_color,
    injury_label,
    injury_color,
    trait_label,
    arb_status_label,
    _score_td,
    _war_td,
    _fmt_pct,
)
from .queries import (
    _lookup_player,
    query_waiver_claim,
)


def find_existing_waiver_report(player_id, save_name, raw_args=""):
    reports_dir = get_reports_dir(save_name, "waiver_claims")
    path = reports_dir / report_filename(f"waiver_{player_id}", dict(raw_args=raw_args.strip().lower()))
    if not path.exists():
        return None
    last_import = get_last_import_iso_for_save(save_name)
    if not last_import:
        return None
    if path.stat().st_mtime > datetime.fromisoformat(last_import).timestamp():
        return str(path)
    return None


def _build_candidate_header(p, adv, last_import, generated_at):
    pos_label = POS_MAP.get(int(p.get("position") or 0), "?")
    bats = BATS_MAP.get(int(p.get("bats") or 0), "?")
    throws = THROWS_MAP.get(int(p.get("throws") or 0), "?")
    role_label = ROLE_MAP.get(int(p.get("role") or 0), "—")
    player_type = p.get("player_type", "batter")

    rating_now = p.get("rating_now")
    rating_ceiling = p.get("rating_ceiling")
    has_ratings = rating_now is not None
    rating_now = float(rating_now) if has_ratings else None
    rating_ceiling = float(rating_ceiling) if rating_ceiling is not None else None
    rating = float(p.get("rating_overall")) if has_ratings else None
    grade = letter_grade(rating) if rating is not None else "N/A"
    team_disp = p.get("team_abbr") or "FA"

    grade_color = (
        "#1a7a1a" if rating is not None and rating >= 70
        else "#cc7700" if rating is not None and rating >= 40
        else "#cc2222"
    )

    flags_html = ""
    flags = []
    if p.get("flag_injury_risk"):
        flags.append('<span class="flag flag-red">Injury Risk</span>')
    if p.get("flag_leader"):
        flags.append('<span class="flag flag-green">Leader</span>')
    if p.get("flag_high_ceiling"):
        flags.append('<span class="flag flag-blue">High Ceiling</span>')
    if p.get("no_trade"):
        flags.append('<span class="flag flag-yellow">No-Trade Clause</span>')
    if p.get("injury_is_injured") and int(p.get("injury_is_injured") or 0) > 0:
        dl_left = p.get("injury_dl_left") or 0
        flags.append(f'<span class="flag flag-red">Currently Injured ({dl_left}d left)</span>')
    if flags:
        flags_html = f'<div class="flags" style="margin-top:8px">{"".join(flags)}</div>'

    # Waiver status pill
    status_html = ""
    if p.get("is_on_waivers") and int(p.get("is_on_waivers") or 0) == 1:
        days_left = p.get("days_on_waivers_left") or 0
        days_on = p.get("days_on_waivers") or 0
        status_html = (
            f'<span style="background:#cc2222;color:white;font-weight:bold;'
            f'border-radius:4px;padding:3px 10px;font-size:12px">'
            f'ON WAIVERS — {days_left}d left ({days_on}d elapsed)</span>'
        )
    elif p.get("designated_for_assignment") and int(p.get("designated_for_assignment") or 0) == 1:
        dfa_left = p.get("days_on_dfa_left") or 0
        status_html = (
            f'<span style="background:#cc7700;color:white;font-weight:bold;'
            f'border-radius:4px;padding:3px 10px;font-size:12px">'
            f'DFA — {dfa_left}d remaining</span>'
        )
    else:
        status_html = (
            '<span style="background:#888;color:white;font-weight:bold;'
            'border-radius:4px;padding:3px 10px;font-size:12px">'
            'NOT ON WAIVERS</span>'
        )

    current_salary = get_current_salary(p)
    years_rem = get_years_remaining(p)
    arb = arb_status_label(p.get("mlb_service_years"))

    war_val = p.get("war")
    war_disp = f"{float(war_val):.1f}" if war_val is not None else "—"

    key_stat = ""
    if player_type == "batter":
        wrc = p.get("wrc_plus")
        key_stat = f"wRC+: <b>{int(wrc) if wrc is not None else '—'}</b>"
        if adv:
            ba = adv.get("ba")
            key_stat += f" | AVG: <b>{float(ba):.3f}</b>" if ba is not None else ""
    else:
        if adv:
            era = adv.get("era")
            fip = adv.get("fip")
            key_stat = f"ERA: <b>{float(era):.2f}</b> | FIP: <b>{float(fip):.2f}</b>" if era is not None and fip is not None else ""

    prone = p.get("prone_overall") or p.get("pr_prone")
    inj_label = injury_label(prone)
    inj_color = injury_color(prone)

    svc_yrs = p.get("mlb_service_years") or 0

    first_name_esc = html.escape(str(p.get("first_name", "")))
    last_name_esc = html.escape(str(p.get("last_name", "")))
    team_disp_esc = html.escape(str(team_disp))

    return f"""
<div class="page-header">
  <div class="header-top">
    <div>
      <div class="player-name">{first_name_esc} {last_name_esc}</div>
      <div class="player-meta">
        {pos_label}{f" ({role_label})" if pos_label == "P" else ""} &bull;
        {team_disp_esc} &bull; Age {p.get("age", "?")} &bull;
        {bats}/{throws} &bull;
        <span class="badge badge-oa">NOW {f"{rating_now:.1f}" if rating_now is not None else "N/A"}</span>&nbsp;
        <span class="badge badge-pot">CEIL {f"{rating_ceiling:.1f}" if rating_ceiling is not None else "N/A"}</span>&nbsp;
        <span class="badge" style="background:#333;color:{'#1a7a1a' if (p.get('confidence') or 0) >= 0.9 else '#cc7700' if (p.get('confidence') or 0) >= 0.5 else '#cc2222'}">CONF {"N/A" if not has_ratings else f"{p.get('confidence') or 0:.0%}"}</span>
      </div>
      <div style="margin-top:8px">{status_html}</div>
      {flags_html}
    </div>
    <div style="text-align:right">
      <div class="grade-badge" style="color:{grade_color}">{grade}</div>
      <div style="font-size:20px;font-weight:700;color:#f0c040;margin-top:4px">{f"{rating:.1f}" if rating is not None else "N/A"}</div>
      <div style="font-size:12px;color:#aaa">Composite Rating</div>
    </div>
  </div>
  <div style="margin-top:12px;display:flex;gap:24px;font-size:12px;color:#ccc;flex-wrap:wrap">
    <span>WAR: <b style="color:#f0c040">{war_disp}</b></span>
    <span>{key_stat}</span>
    <span>Salary: <b style="color:#f0c040">{fmt_salary(current_salary)}</b>
          {f"({years_rem}yr remaining)" if years_rem > 0 else "(Arb/Pre-arb)"}</span>
    <span>Service: <b>{svc_yrs:.1f}yr</b> ({arb})</span>
    <span>Injury Risk: <b style="color:{inj_color}">{inj_label}</b></span>
  </div>
  <div class="import-ts">Waiver Claim Evaluator &bull; Last DB import: {html.escape(last_import or "unknown")} &bull; Generated: {html.escape(generated_at)}</div>
</div>"""


def _build_ratings_section(p):
    tip = (
        '<span style="cursor:help;color:#7f8c8d;font-size:10px;margin-left:3px;vertical-align:super" '
        'title="Trade only">†</span>'
    )
    scores = [
        ("offense", "Offense", p.get("rating_offense")),
        ("contact", "Contact", p.get("rating_contact_quality")),
        ("discipline", "Discipline", p.get("rating_discipline")),
        ("defense", "Defense", p.get("rating_defense")),
        ("baserunning", "Baserunning", p.get("rating_baserunning")),
        ("durability", "Durability", p.get("rating_durability")),
        ("potential", f"Potential{tip}", p.get("rating_potential")),
        ("clubhouse", f"Clubhouse{tip}", p.get("rating_clubhouse")),
    ]
    rows = ""
    for _key, label_html, val in scores:
        if val is None:
            continue
        v = float(val)
        bar_class = "bar-green" if v >= 70 else "bar-yellow" if v >= 40 else "bar-red"
        c = score_color(v)
        rows += (
            f"<tr><td class='left'>{label_html}</td>"
            f"<td><div class='bar-bg'><div class='bar-fill {bar_class}' "
            f"style='width:{v}%'></div></div></td>"
            f"<td style='font-weight:bold;color:{c}'>{v:.0f}</td></tr>\n"
        )
    return f"""
<div class="section">
  <div class="section-title">Rating Breakdown</div>
  <table style="width:auto;min-width:280px">
    <thead><tr><th class="left">Dimension</th><th style="width:190px">Score</th><th>Value</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="font-size:10px;color:#888;margin:6px 0 0 0">† Trade only</p>
</div>"""


def _build_contract_section(p):
    years = int(p.get("years") or 0)
    cy = int(p.get("current_year") or 0)
    salaries = []
    for i in range(years):
        sal = p.get(f"salary{i}")
        if sal is None:
            break
        salaries.append((i, sal))

    salary_cells = ""
    total = 0
    for i, sal in salaries:
        is_current = (i == cy)
        style = " style='font-weight:bold;background:#fff3cd'" if is_current else ""
        salary_cells += f"<td{style}>{fmt_salary(sal)}</td>"
        total += int(sal or 0)

    years_rem = get_years_remaining(p)
    no_trade = p.get("no_trade") or 0
    arb = arb_status_label(p.get("mlb_service_years"))
    options = p.get("options_used") or 0

    header_cells = "".join(
        f"<th>Yr {i + 1}{' (Now)' if i == cy else ''}</th>" for i, _ in salaries
    )

    obligation_note = ""
    if years_rem > 0 and total > 0:
        future = sum(int(p.get(f"salary{i}") or 0) for i in range(cy, years))
        obligation_note = (
            f'<p style="margin-top:6px;font-size:12px;color:#555">'
            f'Claiming this player obligates your team to <b>{fmt_salary(future)}</b> '
            f'over the remaining {years_rem} contract year(s).</p>'
        )

    return f"""
<div class="section">
  <div class="section-title">Contract Obligation (If Claimed)</div>
  <table style="width:auto">
    <thead><tr>{header_cells}<th>Total</th></tr></thead>
    <tbody><tr>{salary_cells}<td style="font-weight:bold">{fmt_salary(total)}</td></tr></tbody>
  </table>
  {obligation_note}
  <div style="margin-top:6px;font-size:12px;color:#555;display:flex;gap:16px">
    <span>Status: <b>{arb}</b></span>
    <span>Options used: <b>{options}</b></span>
    {'<span class="tag tag-warn">No-Trade Clause</span>' if no_trade else ""}
  </div>
</div>"""


def _build_adv_stats_batter(adv):
    if not adv:
        return ""

    def f3(v):
        return f"{float(v):.3f}" if v is not None else "—"

    def f2(v):
        return f"{float(v):.2f}" if v is not None else "—"

    def fp(v):
        return f"{float(v) * 100:.1f}%" if v is not None else "—"

    def c_wrc(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if int(v) >= 115 else "#cc7700" if int(v) >= 85 else "#cc2222"

    def c_ev(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 92 else "#cc7700" if float(v) >= 86 else "#cc2222"

    def c_barrel(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 0.10 else "#cc7700" if float(v) >= 0.04 else "#cc2222"

    def c_hard(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 0.45 else "#cc7700" if float(v) >= 0.32 else "#cc2222"

    def c_xwoba(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 0.360 else "#cc7700" if float(v) >= 0.300 else "#cc2222"

    def c_war(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 3 else "#cc7700" if float(v) >= 1 else "#cc2222"

    wrc = adv.get("wrc_plus")

    # L/R splits row
    pa_l = adv.get("pa_vs_lhp") or 0
    pa_r = adv.get("pa_vs_rhp") or 0
    splits_html = ""
    if pa_l or pa_r:
        splits_html = f"""
  <h3 style="margin:12px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#777">Platoon Splits</h3>
  <table>
    <thead>
      <tr><th>Split</th><th>PA</th><th>AVG</th><th>OBP</th><th>SLG</th><th>ISO</th>
          <th>K%</th><th>BB%</th><th>wOBA</th><th>wRC+</th>
          <th>Avg EV</th><th>Hard Hit%</th><th>Barrel%</th><th>xwOBA</th></tr>
    </thead>
    <tbody>
      <tr>
        <td class="left"><b>vs LHP</b></td>
        <td>{pa_l or "—"}</td>
        <td>{f3(adv.get("ba_vs_lhp"))}</td>
        <td>{f3(adv.get("obp_vs_lhp"))}</td>
        <td>{f3(adv.get("slg_vs_lhp"))}</td>
        <td>{f3(adv.get("iso_vs_lhp"))}</td>
        <td>{fp(adv.get("k_pct_vs_lhp"))}</td>
        <td>{fp(adv.get("bb_pct_vs_lhp"))}</td>
        <td>{f3(adv.get("woba_vs_lhp"))}</td>
        <td style="font-weight:bold;color:{c_wrc(adv.get("wrc_plus_vs_lhp"))}">{int(adv.get("wrc_plus_vs_lhp")) if adv.get("wrc_plus_vs_lhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_ev(adv.get("avg_ev_vs_lhp")) if adv.get("avg_ev_vs_lhp") else "#888"}">{f2(adv.get("avg_ev_vs_lhp")) if adv.get("avg_ev_vs_lhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_hard(adv.get("hard_hit_pct_vs_lhp")) if adv.get("hard_hit_pct_vs_lhp") else "#888"}">{fp(adv.get("hard_hit_pct_vs_lhp")) if adv.get("hard_hit_pct_vs_lhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_barrel(adv.get("barrel_pct_vs_lhp")) if adv.get("barrel_pct_vs_lhp") else "#888"}">{fp(adv.get("barrel_pct_vs_lhp")) if adv.get("barrel_pct_vs_lhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_xwoba(adv.get("xwoba_vs_lhp")) if adv.get("xwoba_vs_lhp") else "#888"}">{f3(adv.get("xwoba_vs_lhp")) if adv.get("xwoba_vs_lhp") else "—"}</td>
      </tr>
      <tr>
        <td class="left"><b>vs RHP</b></td>
        <td>{pa_r or "—"}</td>
        <td>{f3(adv.get("ba_vs_rhp"))}</td>
        <td>{f3(adv.get("obp_vs_rhp"))}</td>
        <td>{f3(adv.get("slg_vs_rhp"))}</td>
        <td>{f3(adv.get("iso_vs_rhp"))}</td>
        <td>{fp(adv.get("k_pct_vs_rhp"))}</td>
        <td>{fp(adv.get("bb_pct_vs_rhp"))}</td>
        <td>{f3(adv.get("woba_vs_rhp"))}</td>
        <td style="font-weight:bold;color:{c_wrc(adv.get("wrc_plus_vs_rhp"))}">{int(adv.get("wrc_plus_vs_rhp")) if adv.get("wrc_plus_vs_rhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_ev(adv.get("avg_ev_vs_rhp")) if adv.get("avg_ev_vs_rhp") else "#888"}">{f2(adv.get("avg_ev_vs_rhp")) if adv.get("avg_ev_vs_rhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_hard(adv.get("hard_hit_pct_vs_rhp")) if adv.get("hard_hit_pct_vs_rhp") else "#888"}">{fp(adv.get("hard_hit_pct_vs_rhp")) if adv.get("hard_hit_pct_vs_rhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_barrel(adv.get("barrel_pct_vs_rhp")) if adv.get("barrel_pct_vs_rhp") else "#888"}">{fp(adv.get("barrel_pct_vs_rhp")) if adv.get("barrel_pct_vs_rhp") else "—"}</td>
        <td style="font-weight:bold;color:{c_xwoba(adv.get("xwoba_vs_rhp")) if adv.get("xwoba_vs_rhp") else "#888"}">{f3(adv.get("xwoba_vs_rhp")) if adv.get("xwoba_vs_rhp") else "—"}</td>
      </tr>
    </tbody>
  </table>"""

    return f"""
<div class="section">
  <div class="section-title">Current Season Stats</div>
  <table>
    <thead>
      <tr><th>G</th><th>PA</th><th>HR</th><th>SB</th><th>AVG</th><th>OBP</th><th>SLG</th><th>OPS</th>
          <th>ISO</th><th>BABIP</th><th>K%</th><th>BB%</th><th>wOBA</th><th>wRC+</th><th>OPS+</th><th>WAR</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>{adv.get("g") or "—"}</td>
        <td>{adv.get("pa") or "—"}</td>
        <td>{adv.get("hr") or "—"}</td>
        <td>{adv.get("sb") or "—"}</td>
        <td>{f3(adv.get("ba"))}</td>
        <td>{f3(adv.get("obp"))}</td>
        <td>{f3(adv.get("slg"))}</td>
        <td>{f3(adv.get("ops"))}</td>
        <td>{f3(adv.get("iso"))}</td>
        <td>{f3(adv.get("babip"))}</td>
        <td>{fp(adv.get("k_pct"))}</td>
        <td>{fp(adv.get("bb_pct"))}</td>
        <td>{f3(adv.get("woba"))}</td>
        <td style="font-weight:bold;color:{c_wrc(wrc)}">{int(wrc) if wrc else "—"}</td>
        <td>{int(adv.get("ops_plus")) if adv.get("ops_plus") else "—"}</td>
        <td style="font-weight:bold;color:{c_war(adv.get("war"))}">{f2(adv.get("war"))}</td>
      </tr>
    </tbody>
  </table>
  <h3 style="margin:12px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#777">Contact Quality</h3>
  <table>
    <thead>
      <tr><th>Batted Balls</th><th>Avg EV</th><th>Max EV</th><th>Avg LA</th>
          <th>Hard Hit%</th><th>Barrel%</th><th>Sweet Spot%</th>
          <th>GB%</th><th>LD%</th><th>FB%</th>
          <th>xBA</th><th>xSLG</th><th>xwOBA</th><th>xBACON</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>{adv.get("batted_balls") if adv.get("batted_balls") is not None else "—"}</td>
        <td style="font-weight:bold;color:{c_ev(adv.get("avg_ev")) if adv.get("avg_ev") is not None else "#888"}">{f2(adv.get("avg_ev")) if adv.get("avg_ev") is not None else "—"}</td>
        <td>{f2(adv.get("max_ev")) if adv.get("max_ev") is not None else "—"}</td>
        <td>{f2(adv.get("avg_la")) if adv.get("avg_la") is not None else "—"}°</td>
        <td style="font-weight:bold;color:{c_hard(adv.get("hard_hit_pct")) if adv.get("hard_hit_pct") is not None else "#888"}">{fp(adv.get("hard_hit_pct")) if adv.get("hard_hit_pct") is not None else "—"}</td>
        <td style="font-weight:bold;color:{c_barrel(adv.get("barrel_pct")) if adv.get("barrel_pct") is not None else "#888"}">{fp(adv.get("barrel_pct")) if adv.get("barrel_pct") is not None else "—"}</td>
        <td>{fp(adv.get("sweet_spot_pct")) if adv.get("sweet_spot_pct") is not None else "—"}</td>
        <td>{fp(adv.get("gb_pct")) if adv.get("gb_pct") is not None else "—"}</td>
        <td>{fp(adv.get("ld_pct")) if adv.get("ld_pct") is not None else "—"}</td>
        <td>{fp(adv.get("fb_pct")) if adv.get("fb_pct") is not None else "—"}</td>
        <td>{f3(adv.get("xba")) if adv.get("xba") is not None else "—"}</td>
        <td>{f3(adv.get("xslg")) if adv.get("xslg") is not None else "—"}</td>
        <td style="font-weight:bold;color:{c_xwoba(adv.get("xwoba")) if adv.get("xwoba") is not None else "#888"}">{f3(adv.get("xwoba")) if adv.get("xwoba") is not None else "—"}</td>
        <td>{f3(adv.get("xbacon")) if adv.get("xbacon") is not None else "—"}</td>
      </tr>
    </tbody>
  </table>
  {splits_html}
</div>"""


def _build_adv_stats_pitcher(adv):
    if not adv:
        return ""

    def f2(v):
        return f"{float(v):.2f}" if v is not None else "—"

    def f1(v):
        return f"{float(v):.1f}" if v is not None else "—"

    def fp(v):
        return f"{float(v) * 100:.1f}%" if v is not None else "—"

    def c_era(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) < 3.5 else "#cc7700" if float(v) < 4.5 else "#cc2222"

    def c_kbb(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 0.18 else "#cc7700" if float(v) >= 0.08 else "#cc2222"

    def c_hard(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) < 0.34 else "#cc7700" if float(v) < 0.42 else "#cc2222"

    def c_barrel(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) < 0.06 else "#cc7700" if float(v) < 0.10 else "#cc2222"

    def c_xwoba(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) < 0.290 else "#cc7700" if float(v) < 0.340 else "#cc2222"

    def c_war(v):
        if v is None:
            return "#888"
        return "#1a7a1a" if float(v) >= 3 else "#cc7700" if float(v) >= 1 else "#cc2222"

    era = adv.get("era")
    fip = adv.get("fip")
    kbb = adv.get("k_bb_pct")

    # L/R splits
    bf_l = adv.get("bf_vs_lhb") or 0
    bf_r = adv.get("bf_vs_rhb") or 0
    splits_html = ""
    if bf_l or bf_r:
        splits_html = f"""
  <h3 style="margin:12px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#777">Splits vs LHB / RHB</h3>
  <table>
    <thead>
      <tr><th>Split</th><th>BF</th><th>ERA</th><th>FIP</th>
          <th>K%</th><th>BB%</th><th>K-BB%</th><th>WHIP</th><th>BABIP</th></tr>
    </thead>
    <tbody>
      <tr>
        <td class="left"><b>vs LHB</b></td>
        <td>{bf_l or "—"}</td>
        <td style="font-weight:bold;color:{c_era(adv.get("era_vs_lhb"))}">{f2(adv.get("era_vs_lhb"))}</td>
        <td style="font-weight:bold;color:{c_era(adv.get("fip_vs_lhb"))}">{f2(adv.get("fip_vs_lhb"))}</td>
        <td>{fp(adv.get("k_pct_vs_lhb"))}</td>
        <td>{fp(adv.get("bb_pct_vs_lhb"))}</td>
        <td style="font-weight:bold;color:{c_kbb(adv.get("k_bb_pct_vs_lhb"))}">{fp(adv.get("k_bb_pct_vs_lhb"))}</td>
        <td>{f2(adv.get("whip_vs_lhb"))}</td>
        <td>{f2(adv.get("babip_vs_lhb"))}</td>
      </tr>
      <tr>
        <td class="left"><b>vs RHB</b></td>
        <td>{bf_r or "—"}</td>
        <td style="font-weight:bold;color:{c_era(adv.get("era_vs_rhb"))}">{f2(adv.get("era_vs_rhb"))}</td>
        <td style="font-weight:bold;color:{c_era(adv.get("fip_vs_rhb"))}">{f2(adv.get("fip_vs_rhb"))}</td>
        <td>{fp(adv.get("k_pct_vs_rhb"))}</td>
        <td>{fp(adv.get("bb_pct_vs_rhb"))}</td>
        <td style="font-weight:bold;color:{c_kbb(adv.get("k_bb_pct_vs_rhb"))}">{fp(adv.get("k_bb_pct_vs_rhb"))}</td>
        <td>{f2(adv.get("whip_vs_rhb"))}</td>
        <td>{f2(adv.get("babip_vs_rhb"))}</td>
      </tr>
    </tbody>
  </table>"""

    return f"""
<div class="section">
  <div class="section-title">Current Season Stats</div>
  <table>
    <thead>
      <tr><th>G</th><th>GS</th><th>IP</th><th>ERA</th><th>FIP</th><th>xFIP</th>
          <th>WHIP</th><th>K%</th><th>BB%</th><th>K-BB%</th>
          <th>K/9</th><th>BB/9</th><th>HR/9</th><th>BABIP</th><th>GB%</th><th>WAR</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>{adv.get("g") or "—"}</td>
        <td>{adv.get("gs") or "—"}</td>
        <td>{f1(adv.get("ip"))}</td>
        <td style="font-weight:bold;color:{c_era(era)}">{f2(era)}</td>
        <td style="font-weight:bold;color:{c_era(fip)}">{f2(fip)}</td>
        <td>{f2(adv.get("xfip"))}</td>
        <td>{f2(adv.get("whip"))}</td>
        <td>{fp(adv.get("k_pct"))}</td>
        <td>{fp(adv.get("bb_pct"))}</td>
        <td style="font-weight:bold;color:{c_kbb(kbb)}">{fp(kbb)}</td>
        <td>{f1(adv.get("k_9"))}</td>
        <td>{f1(adv.get("bb_9"))}</td>
        <td>{f2(adv.get("hr_9"))}</td>
        <td>{f2(adv.get("babip"))}</td>
        <td>{fp(adv.get("gb_pct")) if adv.get("gb_pct") else "—"}</td>
        <td style="font-weight:bold;color:{c_war(adv.get("war"))}">{f2(adv.get("war"))}</td>
      </tr>
    </tbody>
  </table>
  <h3 style="margin:12px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#777">Contact Allowed</h3>
  <table>
    <thead>
      <tr><th>Avg EV Against</th><th>Hard Hit%</th><th>Barrel%</th><th>xBA Against</th><th>xwOBA Against</th></tr>
    </thead>
    <tbody>
      <tr>
        <td style="font-weight:bold;color:{c_hard(adv.get("avg_ev_against")) if adv.get("avg_ev_against") else "#888"}">{f2(adv.get("avg_ev_against")) if adv.get("avg_ev_against") else "—"}</td>
        <td style="font-weight:bold;color:{c_hard(adv.get("hard_hit_pct_against")) if adv.get("hard_hit_pct_against") else "#888"}">{fp(adv.get("hard_hit_pct_against")) if adv.get("hard_hit_pct_against") else "—"}</td>
        <td style="font-weight:bold;color:{c_barrel(adv.get("barrel_pct_against")) if adv.get("barrel_pct_against") else "#888"}">{fp(adv.get("barrel_pct_against")) if adv.get("barrel_pct_against") else "—"}</td>
        <td>{f2(adv.get("xba_against")) if adv.get("xba_against") else "—"}</td>
        <td style="font-weight:bold;color:{c_xwoba(adv.get("xwoba_against")) if adv.get("xwoba_against") else "#888"}">{f2(adv.get("xwoba_against")) if adv.get("xwoba_against") else "—"}</td>
      </tr>
    </tbody>
  </table>
  {splits_html}
</div>"""


def _build_incumbents_section(incumbents, candidate, comparison_positions, my_team_abbr="Your Team"):
    if not incumbents:
        pos_labels = "/".join(POS_MAP.get(p, "?") for p in sorted(comparison_positions))
        return f"""
<div class="section">
  <div class="section-title">{my_team_abbr} Roster at {pos_labels}</div>
  <p style="color:#888;font-style:italic">No {my_team_abbr} players found at this position.</p>
</div>"""

    player_type = candidate.get("player_type", "batter")
    pos_labels = "/".join(POS_MAP.get(p, "?") for p in sorted(comparison_positions))

    cand_rating = float(candidate.get("rating_overall") or 0)
    cand_war = float(candidate.get("war") or 0)
    cand_salary = get_current_salary(candidate) or 0

    header = """
<tr>
  <th class="left">Player</th><th>Pos</th><th>Age</th>
  <th>Now</th><th>Ceiling</th><th>Rating</th>
  <th>WAR</th><th>wRC+/ERA</th>
  <th>Salary</th><th>Yrs Left</th><th>Service</th>
  <th>Options</th><th>Status</th>
</tr>"""

    # Merge candidate into the sorted-by-rating list so it appears in the right position
    cand_salary_disp = get_current_salary(candidate)
    cand_yrs = get_years_remaining(candidate)
    cand_arb = arb_status_label(candidate.get("mlb_service_years"))
    cand_pos_label = POS_MAP.get(int(candidate.get("position") or 0), "?")
    cand_wrc = candidate.get("wrc_plus")
    if player_type == "batter":
        cand_key_td = f'<td><b>{int(cand_wrc) if cand_wrc else "—"}</b></td>'
    else:
        cand_role = ROLE_MAP.get(int(candidate.get("role") or 0), "—")
        cand_key_td = f"<td><b>{cand_role}</b></td>"

    cand_row = f"""<tr style="background:#fff3cd">
      <td class="left"><b>{candidate.get("first_name", "")} {candidate.get("last_name", "")} <span style="font-weight:normal;color:#856404">(Waiver Candidate)</span></b></td>
      <td>{cand_pos_label}</td>
      <td>{candidate.get("age", "?")}</td>
      {_score_td(candidate.get("rating_now"))}
      {_score_td(candidate.get("rating_ceiling"))}
      {_score_td(candidate.get("rating_overall"))}
      {_war_td(candidate.get("war"))}
      {cand_key_td}
      <td>{fmt_salary(cand_salary_disp)}</td>
      <td>{cand_yrs}</td>
      <td>{cand_arb}</td>
      <td>{candidate.get("options_used") or 0}</td>
      <td><span class="tag tag-warn">Waiver/DFA</span></td>
    </tr>"""

    rows_html = ""
    cand_inserted = False
    for inc in incumbents:
        inc_rating = float(inc.get("rating_overall") or 0)

        # Insert candidate row at the correct sorted position
        if not cand_inserted and cand_rating >= inc_rating:
            rows_html += cand_row
            cand_inserted = True

        pos_label = POS_MAP.get(int(inc.get("position") or 0), "?")
        inc_salary = get_current_salary(inc) or 0
        inc_yrs = get_years_remaining(inc)
        arb = arb_status_label(inc.get("mlb_service_years"))
        options = inc.get("options_used") or 0

        status_parts = []
        if inc.get("is_on_dl") or inc.get("is_on_dl60"):
            status_parts.append('<span class="tag tag-bad">IL</span>')
        elif inc.get("designated_for_assignment"):
            status_parts.append('<span class="tag tag-warn">DFA</span>')
        else:
            status_parts.append('<span class="tag tag-good">Active</span>')
        if inc.get("flag_injury_risk"):
            status_parts.append('<span class="tag tag-bad">⚠</span>')

        if player_type == "batter":
            wrc = inc.get("wrc_plus")
            key_stat_td = f'<td>{int(wrc) if wrc else "—"}</td>'
        else:
            role = ROLE_MAP.get(int(inc.get("role") or 0), "—")
            key_stat_td = f"<td>{role}</td>"

        rows_html += f"""<tr>
          <td class="left"><b>{inc.get("first_name", "")} {inc.get("last_name", "")}</b></td>
          <td>{pos_label}</td>
          <td>{inc.get("age", "?")}</td>
          {_score_td(inc.get("rating_now"))}
          {_score_td(inc.get("rating_ceiling"))}
          {_score_td(inc.get("rating_overall"))}
          {_war_td(inc.get("war"))}
          {key_stat_td}
          <td>{fmt_salary(inc_salary)}</td>
          <td>{inc_yrs}</td>
          <td>{arb}</td>
          <td>{options}</td>
          <td>{"".join(status_parts)}</td>
        </tr>"""

    # Append at the bottom if candidate is lower-rated than all incumbents
    if not cand_inserted:
        rows_html += cand_row

    return f"""
<div class="section">
  <div class="section-title">{my_team_abbr} Roster Comparison — {pos_labels}</div>
  <p style="font-size:12px;color:#666;margin-bottom:8px">
    Candidate row highlighted in yellow, sorted by composite rating.
  </p>
  <table>
    <thead>{header}</thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""


def _build_fielding_section(fld, position):
    """Deep fielding component section for defensively important positions: C, 2B, SS, CF."""
    if not fld:
        return ""
    pos = int(position or 0)
    # Only show for premium defensive positions
    if pos not in (2, 4, 6, 8):
        return ""

    def _r(val, invert=False):
        """Color a 20-80 rating. invert=True means lower is better (error rate)."""
        if val is None:
            return "#888"
        v = int(val)
        if invert:
            return "#1a7a1a" if v <= 40 else "#cc7700" if v <= 55 else "#cc2222"
        return "#1a7a1a" if v >= 60 else "#cc7700" if v >= 40 else "#cc2222"

    def _cell(label, val, invert=False):
        if val is None or int(val) == 0:
            return f"<tr><td class='left'>{label}</td><td>—</td></tr>"
        v = int(val)
        c = _r(v, invert)
        grade = "Elite" if v >= 70 else "Above Avg" if v >= 55 else "Average" if v >= 40 else "Below Avg"
        return f"<tr><td class='left'>{label}</td><td style='font-weight:bold;color:{c}'>{v} <span style='font-size:11px;font-weight:normal;color:#888'>({grade})</span></td></tr>"

    if pos == 2:  # Catcher
        title = "Catching Grades"
        pos_rating = fld.get("fielding_rating_pos2")
        rows = (
            _cell("Overall C Rating", pos_rating)
            + _cell("Receiving / Blocking", fld.get("fielding_ratings_catcher_ability"))
            + _cell("Framing", fld.get("fielding_ratings_catcher_framing"))
            + _cell("Arm Strength", fld.get("fielding_ratings_catcher_arm"))
        )
        note = "Framing and receiving are the primary value drivers for a catching claim."

    elif pos in (4, 6):  # 2B / SS
        pos_label = "2B" if pos == 4 else "SS"
        title = f"Middle Infield Grades ({pos_label})"
        pos_rating = fld.get(f"fielding_rating_pos{pos}")
        rows = (
            _cell(f"Overall {pos_label} Rating", pos_rating)
            + _cell("Range", fld.get("fielding_ratings_infield_range"))
            + _cell("Arm", fld.get("fielding_ratings_infield_arm"))
            + _cell("Turn DP", fld.get("fielding_ratings_turn_doubleplay"))
            + _cell("Error Rate (lower = better)", fld.get("fielding_ratings_infield_error"), invert=True)
        )
        note = "Range is the most important component for SS; DP turn and range both matter at 2B."

    else:  # CF (pos == 8)
        title = "Center Field Grades"
        pos_rating = fld.get("fielding_rating_pos8")
        rows = (
            _cell("Overall CF Rating", pos_rating)
            + _cell("Range", fld.get("fielding_ratings_outfield_range"))
            + _cell("Arm", fld.get("fielding_ratings_outfield_arm"))
            + _cell("Error Rate (lower = better)", fld.get("fielding_ratings_outfield_error"), invert=True)
        )
        note = "Range is the primary value driver in CF; arm matters for suppressing baserunner aggression."

    return f"""
<div class="section">
  <div class="section-title">{title}</div>
  <table style="width:auto;min-width:320px">
    <thead><tr><th class="left">Component</th><th class="left">Grade (20–80)</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="font-size:12px;color:#666;margin-top:6px">{note}</p>
</div>"""


def _build_positional_flexibility(field_positions, primary_pos, player_type):
    if player_type == "pitcher":
        return ""
    playable = {k: v for k, v in field_positions.items() if v >= 40 and k != 1}
    if not playable:
        return ""

    pos_tags = ""
    for pos_int, rating in sorted(playable.items(), key=lambda x: -x[1]):
        pos_label = POS_MAP.get(pos_int, "?")
        is_primary = (pos_int == int(primary_pos or 0))
        c = "tag-good" if rating >= 55 else "tag-warn"
        primary_marker = " (Primary)" if is_primary else ""
        pos_tags += f'<span class="tag {c}" style="margin:2px">{pos_label}: {rating}{primary_marker}</span> '

    return f"""
<div class="section">
  <div class="section-title">Positional Flexibility</div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">{pos_tags}</div>
  <p style="font-size:12px;color:#666;margin-top:6px">
    Ratings ≥ 55 = solid defender; 40–54 = passable; shown on 20–80 scale.
    Multiple positions increase roster flexibility value of this claim.
  </p>
</div>"""


def _build_40man_section(roster_count, candidate):
    max_roster = 40
    spots_left = max(0, max_roster - roster_count)
    needs_dfa = (spots_left == 0)

    status_class = "tag-bad" if needs_dfa else "tag-good"
    status_text = (
        f"FULL — Must DFA a player to make room ({roster_count}/{max_roster})"
        if needs_dfa
        else f"{spots_left} open spot(s) ({roster_count}/{max_roster})"
    )

    active_note = ""
    if needs_dfa:
        active_note = (
            '<p style="font-size:12px;color:#cc2222;margin-top:6px">'
            '<b>Warning:</b> 40-man roster is at capacity. Claiming this player requires DFA\'ing '
            'a current roster member. Consider the least-valuable player at the same position.</p>'
        )

    days_left = candidate.get("days_on_waivers_left") or 0
    claim_window = ""
    if int(candidate.get("is_on_waivers") or 0) == 1 and days_left > 0:
        urgency_color = "#cc2222" if days_left <= 1 else "#cc7700" if days_left <= 2 else "#1a7a1a"
        claim_window = (
            f'<p style="font-size:12px;margin-top:6px">'
            f'Waiver claim window: <b style="color:{urgency_color}">{days_left} day(s) remaining</b> '
            f'— act before the window closes.</p>'
        )
    elif int(candidate.get("designated_for_assignment") or 0) == 1:
        dfa_left = candidate.get("days_on_dfa_left") or 0
        claim_window = (
            f'<p style="font-size:12px;margin-top:6px">'
            f'DFA window: <b style="color:#cc7700">{dfa_left} day(s) remaining</b> '
            f'to claim or release.</p>'
        )

    return f"""
<div class="section">
  <div class="section-title">40-Man Roster Status</div>
  <span class="tag {status_class}">{status_text}</span>
  {active_note}
  {claim_window}
</div>"""


def _build_personality_section(p):
    greed = p.get("greed")
    loyalty = p.get("loyalty")
    work_ethic = p.get("work_ethic")
    intelligence = p.get("intelligence")
    play_for_winner = p.get("personality_play_for_winner")
    local_pop = p.get("local_pop")

    rows = ""
    for label, val, invert in [
        ("Greed", greed, True),
        ("Loyalty", loyalty, False),
        ("Work Ethic", work_ethic, False),
        ("Intelligence", intelligence, False),
    ]:
        if val is None:
            continue
        v = int(val)
        c = (
            "#cc2222" if (invert and v > 150) or (not invert and v < 50)
            else "#1a7a1a" if (invert and v < 80) or (not invert and v > 150)
            else "#cc7700"
        )
        rows += f"<tr><td class='left'>{label}</td><td style='color:{c};font-weight:bold'>{trait_label(v)} ({v})</td></tr>\n"

    if play_for_winner is not None:
        v = int(play_for_winner)
        c = "#cc7700" if v > 150 else "#888"
        rows += f"<tr><td class='left'>Play for Winner</td><td style='color:{c};font-weight:bold'>{trait_label(v)} ({v})</td></tr>\n"

    if local_pop is not None:
        rows += f"<tr><td class='left'>Local Popularity</td><td>{int(local_pop)}/6</td></tr>\n"

    if not rows:
        return ""

    return f"""
<div class="section">
  <div class="section-title">Player Profile</div>
  <table style="width:auto;min-width:260px">
    <thead><tr><th class="left">Trait</th><th class="left">Value</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


def _build_recommendation_placeholder():
    return """
<div class="section">
  <div class="section-title">Claim Recommendation</div>
  <!-- WAIVER_RECOMMENDATION -->
</div>"""


def generate_waiver_claim_report(save_name, first_name, last_name, raw_args=""):
    """Generate a waiver claim evaluation report.

    Returns:
        (None, None)   — player not found
        (path, None)   — cache hit, path is existing report
        (path, dict)   — newly generated report + data dict for agent summary
    """
    engine = get_engine(save_name)

    with engine.connect() as conn:
        candidate = _lookup_player(conn, first_name, last_name)
        if not candidate:
            return None, None

        player_id = candidate["player_id"]

        # Cache check
        existing = find_existing_waiver_report(player_id, save_name, raw_args)
        if existing:
            return existing, None

    # Cache miss — query all data
    data = query_waiver_claim(save_name, first_name, last_name)
    if data is None:
        return None, None

    # Extract private keys for HTML construction
    candidate = data.pop("_candidate")
    adv = data.pop("_adv")
    incumbents = data.pop("_incumbents")
    field_positions = data.pop("_field_positions")
    fielding_details = data.pop("_fielding_details")
    roster_count = data.pop("_roster_count")
    player_id = data.pop("_player_id")
    player_type = data.pop("_player_type")
    position = data.pop("_position")
    player_role = data.pop("_player_role")
    comparison_positions = data.pop("_comparison_positions")
    my_team_name = data.pop("_my_team_name")

    # Build HTML
    last_import = get_last_import_iso_for_save(save_name)
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    css = get_report_css("1200px")
    header_html = _build_candidate_header(candidate, adv, last_import, generated_at)
    ratings_html = _build_ratings_section(candidate)
    contract_html = _build_contract_section(candidate)
    adv_html = (
        _build_adv_stats_batter(adv)
        if player_type == "batter"
        else _build_adv_stats_pitcher(adv)
    )
    incumbents_html = _build_incumbents_section(incumbents, candidate, comparison_positions, my_team_name)
    fielding_html = _build_fielding_section(fielding_details, position)
    flex_html = _build_positional_flexibility(field_positions, position, player_type)
    roster_html = _build_40man_section(roster_count, candidate)
    personality_html = _build_personality_section(candidate)
    recommendation_html = _build_recommendation_placeholder()

    full_name = f"{first_name}_{last_name}".lower().replace(" ", "_")
    title = html.escape(f"Waiver Claim: {first_name} {last_name}")
    esc_first = html.escape(first_name)
    esc_last = html.escape(last_name)
    esc_save = html.escape(save_name)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="ootp-skill" content="waiver-claim">
  <meta name="ootp-args" content="{esc_first} {esc_last}">
  <meta name="ootp-args-display" content="">
  <meta name="ootp-save" content="{esc_save}">
  <meta name="ootp-generated" content="{html.escape(generated_at)}">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>
<div class="container">
  {header_html}
  {recommendation_html}
  {incumbents_html}
  {adv_html}
  {fielding_html}
  {ratings_html}
  {contract_html}
  {flex_html}
  {roster_html}
  {personality_html}
</div>
</body>
</html>"""

    reports_dir = get_reports_dir(save_name, "waiver_claims")
    report_path = reports_dir / report_filename(f"waiver_{player_id}", dict(raw_args=raw_args.strip().lower()))
    write_report_html(report_path, html_doc)

    data["report_path"] = str(report_path)
    return str(report_path), data
