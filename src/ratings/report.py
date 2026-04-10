"""HTML report generation and cache checks for player ratings."""

import json
import sys
from datetime import datetime
from pathlib import Path

from config import (
    INJURY_DURABLE_MAX,
    INJURY_FRAGILE_MAX,
    INJURY_IRON_MAN_MAX,
    INJURY_NORMAL_MAX,
    TRAIT_AVERAGE_MAX,
    TRAIT_BELOW_AVG_MAX,
    TRAIT_GOOD_MAX,
    TRAIT_POOR_MAX,
)
from report_write import report_filename, write_report_html
from shared_css import get_report_css, get_reports_dir, get_write_engine

from .grades import letter_grade
from .queries import query_player_rating

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LAST_IMPORT_PATH = _PROJECT_ROOT / ".last_import"


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
    report_path = get_reports_dir(save_name, "ratings") / report_filename(f"rating_{player_id}", args_key)

    if not report_path.exists():
        return None

    if not _LAST_IMPORT_PATH.exists():
        return str(report_path)

    report_mtime = datetime.fromtimestamp(report_path.stat().st_mtime)
    import_time = datetime.fromisoformat(_LAST_IMPORT_PATH.read_text().strip())

    if report_mtime >= import_time:
        return str(report_path)

    return None


def get_last_import_time():
    if _LAST_IMPORT_PATH.exists():
        return _LAST_IMPORT_PATH.read_text().strip()
    return None


def generate_rating_report(save_name, first_name, last_name, focus_modifiers=None):
    """Generate (or return cached) a player rating HTML report.

    focus_modifiers: list of strings like ["defense", "power"] or None.

    Returns (path_str, data_dict) where data_dict is None on a cache hit.
    """
    engine = get_write_engine(save_name)

    existing = find_existing_rating_report(save_name, first_name, last_name, engine, focus_modifiers)
    if existing:
        return existing, None

    last_import = get_last_import_time()
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    data = query_player_rating(save_name, first_name, last_name, focus_modifiers)
    if data is None:
        print(f"Player not found: {first_name} {last_name}")
        sys.exit(1)

    player_id = data["player_id"]
    first = data["first_name"]
    last = data["last_name"]
    team_abbr = data["team_abbr"]
    pos_name = data["pos_name"]
    age_disp = data["age_disp"]
    oa_disp = data["oa_disp"]
    pot_disp = data["pot_disp"]
    player_type = data["player_type"]
    rating_overall = data["rating_overall"]
    rating_now = data["rating_now"]
    confidence = data["confidence"]
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
    adapt_v = data["adapt_v"]
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
    archetype_label = data.get("archetype_label")
    archetype_color = data.get("archetype_color")
    archetype_desc = data.get("archetype_desc")

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
            return "Unknown"
        v = int(val)
        if v <= TRAIT_POOR_MAX:
            return "Poor"
        if v <= TRAIT_BELOW_AVG_MAX:
            return "Below Avg"
        if v <= TRAIT_AVERAGE_MAX:
            return "Average"
        if v <= TRAIT_GOOD_MAX:
            return "Good"
        return "Elite"

    def trait_color(val, invert=False):
        if val is None:
            return "#888"
        v = int(val)
        if invert:
            if v > TRAIT_GOOD_MAX:
                return "#cc2222"
            if v > TRAIT_AVERAGE_MAX:
                return "#cc7700"
            return "#1a7a1a"
        if v > TRAIT_GOOD_MAX:
            return "#1a7a1a"
        if v > TRAIT_AVERAGE_MAX:
            return "#4a9a2a"
        if v > TRAIT_BELOW_AVG_MAX:
            return "#888"
        return "#cc7700"

    adj_note = ""
    if adjusted:
        adj_note = (f'<div class="section"><div class="callout">'
                    f'Focus: <b>{", ".join(focus_modifiers)}</b> — '
                    f'Default: {rating_overall:.1f} ({lg(rating_overall)}) &rarr; '
                    f'Adjusted: {adj_rating:.1f} ({lg(adj_rating)})</div></div>')

    flag_pills = ""
    if archetype_label:
        title = f' title="{archetype_desc}"' if archetype_desc else ""
        flag_pills += (f'<span class="flag"{title} style="background:{archetype_color}20;'
                       f'color:{archetype_color};border:1px solid {archetype_color}60">'
                       f'{archetype_label}</span>')
    if flag_injury:
        flag_pills += '<span class="flag flag-red">⚠ Injury Risk</span>'
    if flag_leader_val:
        flag_pills += '<span class="flag flag-yellow">🏆 Leader</span>'
    if flag_ceiling:
        flag_pills += '<span class="flag flag-blue">📈 High Ceiling</span>'
    flags_html = f'<div class="flags">{flag_pills}</div>' if flag_pills else ""

    _trade_only_tip = (
        '<span style="cursor:help;color:#7f8c8d;font-size:11px;margin-left:3px;vertical-align:super" '
        'title="Trade only">†</span>'
    )
    sub_rows = ""
    for key, label in component_labels:
        sc = scores[key]
        w_cell = f"{weights[key] * 100:.0f}%"
        label_html = label
        if key in ("potential", "clubhouse"):
            label_html = f"{label}{_trade_only_tip}"
        sub_rows += (f'<tr><td class="left">{label_html}</td>'
                     f'<td>{w_cell}</td>'
                     f'<td class="score-num">{sc:.1f}</td>'
                     f'<td>{bar_html(sc)}</td></tr>')

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
        f'<tr><td class="left">Baseball IQ</td><td>{iq_v}</td>'
        f'<td style="color:{trait_color(iq_v)};font-weight:bold">{trait_label(iq_v)}</td></tr>'
        f'<tr><td class="left">Adaptability</td><td>{adapt_v}</td>'
        f'<td style="color:{trait_color(adapt_v)};font-weight:bold">{trait_label(adapt_v)}</td></tr>'
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
    <div class="grade-badge">{lg(rating_now)}</div>
  </div>
  <div class="rating-bar-wrap">
    <span class="rating-label">Performance Rating</span>
    <span class="rating-val">{rating_now:.1f}</span>
    {'&nbsp;<span style="color:#cc7700;font-size:12px" title="Limited statistical sample — Performance Rating may not reflect true ability">⚠ Limited sample</span>' if confidence < 0.8 else ''}
    <span class="oa-pot">&nbsp;&bull;&nbsp;#{rank} of {rank_total} {pos_name}</span>
  </div>
  <div class="rating-bar-wrap" style="margin-top:4px">
    <span style="font-size:12px;color:#888">Trade/Contract Rating:&nbsp;</span>
    <span style="font-size:14px;color:#aaa;font-weight:600">{final_rating:.1f}</span>
    <span style="font-size:12px;color:#666;margin-left:4px">(age-adjusted)</span>
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
  <td class="left"><b>Trade/Contract Rating</b></td><td></td>
  <td class="score-num">{final_rating:.1f}</td>
  <td>{bar_html(final_rating)}</td>
  </tr>
  </table>
  <p style="font-size:11px;color:#888;margin:6px 0 0 0">† Trade only</p>
</div>

<div class="section">
  <div class="section-title">Durability</div>
  <table>
  <tr><th class="left">Area</th><th>Value</th><th>Label</th></tr>
  {inj_rows}
  </table>
</div>

<div class="section">
  <div class="section-title">Development Potential</div>
  <p style="font-size:12px;color:#666;margin:0 0 8px 0">Work ethic, baseball IQ, and adaptability scale the <b>Potential</b> component in the Trade/Contract rating (along with OA/POT gap and age).</p>
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
