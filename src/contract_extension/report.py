"""Entry point and HTML assembly for the contract extension advisor."""

import html as html_mod
from datetime import datetime

from ootp_db_constants import POS_MAP
from report_write import write_report_html, report_filename
from shared_css import (
    get_engine,
    get_last_import_iso_for_save,
    get_report_css,
    get_reports_dir,
)

from .formatting import (
    fmt_salary,
    get_current_salary,
    get_years_remaining,
    injury_color,
    injury_label,
    letter_grade,
    pop_color,
    pop_label,
    trait_color,
    trait_label,
)
from .queries import _lookup_player_id, query_contract_extension
from .tables import (
    build_adv_stats_batter_table,
    build_adv_stats_pitcher_table,
    build_comps_table,
    build_war_table_batter,
    build_war_table_pitcher,
)


def generate_contract_extension_report(save_name, first_name, last_name, raw_args=""):
    """Generate a contract extension advisor HTML report.

    Returns (path_str, data_dict) on generation, or (path_str, None) on cache hit.
    Returns (None, None) if the player is not found.
    """
    last_import = get_last_import_iso_for_save(save_name)
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
