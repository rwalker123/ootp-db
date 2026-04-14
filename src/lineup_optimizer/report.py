"""HTML report generation for lineup optimizer."""

import html as html_mod
from datetime import datetime

from ootp_db_constants import BATS_MAP, POS_MAP
from report_write import write_report_html, report_filename
from shared_css import (
    get_engine,
    get_last_import_iso_for_save,
    get_report_css,
    get_reports_dir,
)

from .constants import PHIL_LABELS, PHILOSOPHIES
from .engine import is_star
from .formatting import (
    _fatigue_color, fmt_int, fmt_woba, grade_color,
    handedness_pattern, iso_td, temp_emoji, woba_td, wrc_td,
)
from .loaders import resolve_team
from .queries import query_lineup


def build_html(team_name, team_abbr, philosophy, hand, lineup, all_players,
               alternation_score, dh_used, save_name, excluded_names,
               primary_only=False, forced_bench=None, fatigue_threshold=None,
               fatigue_benched=None, favor_offense=False, args_str="",
               args_display=""):
    now = datetime.now()
    now_str = now.strftime("%B %d, %Y %I:%M %p")
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S")
    hand_label = {"L": "vs LHP", "R": "vs RHP"}.get(hand, "Handedness Not Specified")
    phil_label = PHIL_LABELS.get(philosophy, philosophy.title())

    _title_parts = [f"Lineup Optimizer \u2014 {team_name}", phil_label]
    if hand:
        _title_parts.append(hand_label)
    if primary_only:
        _title_parts.append("Primary Only")
    if favor_offense:
        _title_parts.append("Favor Offense")
    report_title = " | ".join(_title_parts)

    if alternation_score >= 8:
        alt_color, alt_label = "#155724", "Excellent"
        alt_bg = "#d4edda"
    elif alternation_score >= 6:
        alt_color, alt_label = "#856404", "Good"
        alt_bg = "#fff3cd"
    else:
        alt_color, alt_label = "#721c24", "Poor"
        alt_bg = "#f8d7da"

    pattern_str = handedness_pattern(lineup)

    # ── Lineup card rows ──────────────────────────────────────────────────
    lineup_rows = []
    for slot in range(1, (10 if dh_used else 9)):
        if slot not in lineup:
            continue
        p = lineup[slot]
        adv = p.get("adv") or {}
        name = html_mod.escape(f"{p['first_name']} {p['last_name']}")
        pos_str = p.get("assigned_pos") or POS_MAP.get(p.get("position"), "?")
        bats_str = BATS_MAP.get(p.get("bats") or 1, "R")
        star_badge = ' <span style="color:#f0c040;font-weight:bold" title="Star player">★</span>' if is_star(p) else ""
        rolling = p.get("rolling") or {}

        pa_val = adv.get("pa") or 0
        pa_style = ' style="color:#cc7700;font-weight:bold"' if pa_val < 80 else ' style="color:#555"'
        fat_val = p.get("fatigue_points") or 0
        fat_color = _fatigue_color(fat_val)
        fat_cell = f'<td style="color:{fat_color};font-weight:bold">{fat_val}</td>'
        force_badge = ' <span class="tag tag-force" title="Manager force-start override">[F]</span>' if p.get("forced") else ""
        emg_badge = ' <span class="tag tag-bad" title="Emergency assignment — no qualified player met rating/games floors">[!]</span>' if p.get("emergency") else ""
        temp_badge = temp_emoji(p.get('temp_flag', 'neutral'))

        if hand == "L":
            woba_cell = f'<td>{fmt_woba(adv.get("woba_vs_lhp"))}</td>'
            rating_now_val = p.get("rating_now_lhp") or 0
            conf_val = p.get("confidence_lhp") or 0
        elif hand == "R":
            woba_cell = f'<td>{fmt_woba(adv.get("woba_vs_rhp"))}</td>'
            rating_now_val = p.get("rating_now_rhp") or 0
            conf_val = p.get("confidence_rhp") or 0
        else:
            woba_cell = woba_td(adv.get('woba'))
            rating_now_val = p.get("rating_now") or 0
            conf_val = p.get("confidence") or 0

        rating_now_color = grade_color(rating_now_val)
        conf_color = "#1a7a1a" if conf_val >= 0.8 else "#cc7700" if conf_val >= 0.4 else "#cc2222"

        lineup_rows.append(f"""
          <tr>
            <td style="font-size:16px;font-weight:900;color:#1a1a2e;width:28px">{slot}</td>
            <td class="left">{name}{temp_badge}{star_badge}{force_badge}{emg_badge}</td>
            <td>{pos_str}</td>
            <td>{bats_str}</td>
            {wrc_td(adv.get('wrc_plus'))}
            <td{pa_style}>{fmt_int(pa_val) if pa_val else "—"}</td>
            <td>{fmt_woba(adv.get('obp'))}</td>
            {iso_td(adv.get('iso'))}
            {woba_cell}
            <td style="background:#e8f5e9;color:{rating_now_color};font-weight:bold">{rating_now_val:.0f}</td>
            <td style="color:{conf_color};font-weight:bold">{conf_val:.2f}</td>
            {fat_cell}
            <td style="color:#555">{int(p.get('rating_baserunning') or 0)}</td>
          </tr>""")
    lineup_rows_html = "\n".join(lineup_rows)

    # ── Full roster rows ──────────────────────────────────────────────────
    lineup_pids = {p["player_id"] for p in lineup.values()}
    _fb_lower = {n.lower() for n in (forced_bench or [])}
    _fatb_lower = {n.lower() for n in (fatigue_benched or [])}
    roster_rows = []
    for p in sorted(all_players, key=lambda x: (x["player_id"] not in lineup_pids,
                                                  ((x.get("adv") or {}).get("pa") or 0) == 0,
                                                  -(x.get("sort_score") or 0))):
        adv = p.get("adv") or {}
        in_lineup = p["player_id"] in lineup_pids
        name = html_mod.escape(f"{p['first_name']} {p['last_name']}")
        pos_str = POS_MAP.get(p.get("position"), "?")
        bats_str = BATS_MAP.get(p.get("bats") or 1, "R")
        row_style = "" if in_lineup else ' style="opacity:0.65"'
        role_cell = ('<td class="left"><span class="tag tag-good">Starting</span></td>'
                     if in_lineup else
                     '<td class="left"><span class="tag tag-neutral">Bench</span></td>')

        full_name_lower = f"{p['first_name']} {p['last_name']}".lower()
        is_forced_bench = full_name_lower in _fb_lower
        is_fat_benched = full_name_lower in _fatb_lower
        if is_forced_bench:
            role_cell = '<td class="left"><span class="tag tag-force">[F] Bench</span></td>'
        elif is_fat_benched:
            role_cell = '<td class="left"><span class="tag tag-bad">Fatigued</span></td>'

        pa_val = adv.get("pa") or 0
        pa_style = ' style="color:#cc7700;font-weight:bold"' if pa_val < 80 else ' style="color:#555"'
        fat_val = p.get("fatigue_points") or 0
        fat_color = _fatigue_color(fat_val)
        force_badge = ' <span class="tag tag-force" title="Manager force-start override">[F]</span>' if p.get("forced") else ""
        temp_badge = temp_emoji(p.get('temp_flag', 'neutral'))

        if hand == "L":
            woba_cell = f'<td>{fmt_woba(adv.get("woba_vs_lhp"))}</td>'
            rating_now_val = p.get("rating_now_lhp") or 0
            conf_val = p.get("confidence_lhp") or 0
        elif hand == "R":
            woba_cell = f'<td>{fmt_woba(adv.get("woba_vs_rhp"))}</td>'
            rating_now_val = p.get("rating_now_rhp") or 0
            conf_val = p.get("confidence_rhp") or 0
        else:
            woba_cell = woba_td(adv.get('woba'))
            rating_now_val = p.get("rating_now") or 0
            conf_val = p.get("confidence") or 0

        rating_now_color = grade_color(rating_now_val)
        conf_color = "#1a7a1a" if conf_val >= 0.8 else "#cc7700" if conf_val >= 0.4 else "#cc2222"

        roster_rows.append(f"""
          <tr{row_style}>
            <td class="left">{name}{temp_badge}{force_badge}</td>
            <td>{pos_str}</td>
            <td>{bats_str}</td>
            {wrc_td(adv.get('wrc_plus'))}
            <td{pa_style}>{fmt_int(pa_val) if pa_val else "—"}</td>
            <td>{fmt_woba(adv.get('obp'))}</td>
            {iso_td(adv.get('iso'))}
            {woba_cell}
            <td style="background:#e8f5e9;color:{rating_now_color};font-weight:bold">{rating_now_val:.0f}</td>
            <td style="color:{conf_color};font-weight:bold">{conf_val:.2f}</td>
            <td style="color:{fat_color};font-weight:bold">{fat_val}</td>
            <td style="color:#555">{int(p.get('rating_baserunning') or 0)}</td>
            {role_cell}
          </tr>""")
    roster_rows_html = "\n".join(roster_rows)

    # ── Override / exclusion banners ──────────────────────────────────────
    excl_html = ""
    if excluded_names:
        excl_list = ", ".join(html_mod.escape(n) for n in excluded_names)
        excl_html += f'<div class="stale-banner" style="margin-top:8px">Excluded (without): <b>{excl_list}</b></div>'
    if forced_bench:
        fb_list = ", ".join(html_mod.escape(n) for n in forced_bench)
        excl_html += f'<div class="stale-banner-blue" style="margin-top:4px"><b>[F] Manager bench:</b> {fb_list}</div>'
    if fatigue_benched:
        fat_list = ", ".join(html_mod.escape(n) for n in fatigue_benched)
        thr_label = f" (threshold: {fatigue_threshold}%)" if fatigue_threshold is not None else ""
        excl_html += f'<div class="stale-banner-red" style="margin-top:4px"><b>Fatigued — auto-benched{thr_label}:</b> {fat_list}</div>'
    if favor_offense:
        excl_html += '<div class="stale-banner" style="margin-top:4px"><b>Favor Offense:</b> defense weight reduced at C / 2B / SS / CF — batting quality has more influence over positional assignments.</div>'

    css = get_report_css("1120px")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html_mod.escape(report_title)}</title>
  <meta name="ootp-skill" content="lineup-optimizer">
  <meta name="ootp-args" content="{html_mod.escape(args_str)}">
  <meta name="ootp-args-display" content="{html_mod.escape(args_display)}">
  <meta name="ootp-save" content="{html_mod.escape(save_name)}">
  <meta name="ootp-generated" content="{now_iso}">
  <style>{css}
    .pattern-str {{ font-family: monospace; font-size: 14px; letter-spacing: 3px;
                   color: #f0c040; font-weight: bold; }}
    .temp-legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 8px 0;
                   font-size: 12px; color: #ccc; }}
  </style>
</head>
<body>
<div class="container">

  <div class="page-header">
    <div class="header-top">
      <div>
        <div class="player-name">{html_mod.escape(team_name)}</div>
        <div class="player-meta">Lineup Optimizer &mdash;
          <b>{html_mod.escape(phil_label)}</b> &mdash; {hand_label}
        </div>
        <div class="player-meta">Generated {now_str}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:13px;color:#aaa;margin-bottom:4px">{hand_label}</div>
        <div class="pattern-str">{pattern_str}</div>
        <div style="font-size:12px;color:#aaa;margin-top:4px">L/R/S batting pattern</div>
      </div>
    </div>
    <div class="flags" style="margin-top:14px">
      <span class="flag flag-blue">Philosophy: {html_mod.escape(phil_label)}</span>
      <span class="flag" style="background:{alt_bg};color:{alt_color}">
        Alternation: {alternation_score}/10 &mdash; {alt_label}
      </span>
      {'<span class="flag flag-green">DH In Use</span>' if dh_used else '<span class="flag flag-neutral">No DH</span>'}
      {'<span class="flag flag-yellow">Primary Position Only</span>' if primary_only else '<span class="flag flag-blue">Multi-Position</span>'}
    </div>
    <div class="temp-legend">
      <span>🔥🔥 extreme hot streak (30-day wOBA &ge;+.060)</span>
      <span>🔥 hot (+.030&ndash;.059)</span>
      <span>🧊 cold (&minus;.030&ndash;.059)</span>
      <span>🧊🧊 extreme cold (&le;&minus;.060)</span>
      <span style="color:#f0c040;font-weight:bold">★</span>&nbsp;= Star (wOBA &ge;.370 or Rating &ge;70) &mdash; cold-streak penalty halved
    </div>
    {excl_html}
  </div>

  <!-- Lineup Card -->
  <div class="section">
    <div class="section-title">Batting Order</div>
    <table>
      <thead>
        <tr>
          <th style="width:36px">#</th>
          <th class="left">Name</th>
          <th>Pos</th><th>Bats</th>
          <th>wRC+</th><th title="Career MLB plate appearances — amber = low sample, ranking adjusted">PA</th>
          <th>OBP</th><th>ISO</th>
          <th>{"vs LHP" if hand == "L" else "vs RHP" if hand == "R" else "wOBA"}</th>
          <th title="Performance rating (rating_now or split equivalent)">Rating</th>
          <th title="Statistical confidence 0–1. Red = thin sample, green = established">Conf</th>
          <th title="Fatigue 0–100. Red ≥70, amber ≥40, green &lt;40">Fat.</th>
          <th>Speed</th>
        </tr>
      </thead>
      <tbody>
{lineup_rows_html}
      </tbody>
    </table>
    <div class="split-note">
      wOBA column shows career split vs today&rsquo;s opponent handedness (or overall when unspecified).
      🔥 = hot streak (30-day wOBA +.030+), 🔥🔥 = extreme (+.060+).
      🧊 = cold (−.030+), 🧊🧊 = extreme (−.060+).<br>
      * = playing out of primary position.
      C, 2B, SS, CF selection applies a small defense tiebreaker.<br>
      <b>PA (amber = &lt;80):</b> Low-PA players rank by talent rating until they have meaningful MLB samples.<br>
      <b>[F]</b> = manager override (force-start or force-position). Bypasses eligibility floors.
      <b>Fat.</b> = fatigue 0&ndash;100 (green &lt;40, amber &ge;40, red &ge;70).
      Use <code>fatigue &lt;N&gt;</code> in skill args to auto-bench players above a threshold.
    </div>
  </div>

  <!-- Analysis Placeholder -->
  <div class="section">
    <div class="section-title">Lineup Analysis</div>
    <!-- LINEUP_ANALYSIS -->
  </div>

  <!-- Full Roster -->
  <div class="section">
    <div class="section-title">Full Roster — Batter Stats</div>
    <table>
      <thead>
        <tr>
          <th class="left">Name</th><th>Pos</th><th>Bats</th>
          <th>wRC+</th><th title="Career MLB plate appearances — amber = low sample, ranking adjusted">PA</th>
          <th>OBP</th><th>ISO</th>
          <th>{"vs LHP" if hand == "L" else "vs RHP" if hand == "R" else "wOBA"}</th>
          <th title="Performance rating (rating_now or split equivalent)">Rating</th>
          <th title="Statistical confidence 0–1. Red = thin sample, green = established">Conf</th>
          <th title="Fatigue 0–100">Fat.</th><th>Speed</th>
          <th class="left">Role</th>
        </tr>
      </thead>
      <tbody>
{roster_rows_html}
      </tbody>
    </table>
    <div class="split-note">
      wOBA column reflects career PA vs today&rsquo;s opponent handedness (or overall when unspecified).
      Values may be sparse at low sample sizes. Bench players are dimmed.
    </div>
  </div>

</div>
</body>
</html>"""


def generate_lineup_report(save_name, team_query=None, philosophy="modern",
                            opponent_hand=None, excluded_names=None,
                            primary_only=False, forced_starts=None,
                            forced_bench=None, fatigue_threshold=None,
                            favor_offense=False, raw_args=""):
    """
    Generate (or return cached) lineup optimizer report.

    forced_starts:     list of {"name": str, "pos": int|None} — player is guaranteed
                       a lineup spot; if pos is given they're locked to that position
                       (bypasses eligibility floors).
    forced_bench:      list of player name strings — excluded from lineup regardless.
    fatigue_threshold: int 0-100 — auto-bench any player whose fatigue_points >= this.
                       When set, also bypasses cache.
    favor_offense:     bool — reduces defense weight at premium positions (C, 2B,
                       SS, CF), overriding moderate batting advantages.

    Returns:
        (path_str, data_dict)  on generation
        (path_str, None)       on cache hit
        (None, None)           on error / team not found
    """
    if philosophy not in PHILOSOPHIES:
        philosophy = "modern"
    excluded_names = list(excluded_names or [])
    forced_starts = forced_starts or []
    forced_bench = forced_bench or []
    hand = (opponent_hand or "").upper()[:1]
    if hand not in ("L", "R"):
        hand = None

    # Cache check requires team_abbr — resolve team with a quick DB call
    engine = get_engine(save_name)
    with engine.connect() as conn:
        team_id, team_name, team_abbr = resolve_team(conn, team_query)
        if not team_id:
            return None, None

        args_key = dict(
            philosophy=philosophy,
            hand=hand,
            primary_only=primary_only,
            excluded=sorted(excluded_names),
            forced_starts=sorted(str(fs) for fs in (forced_starts or [])),
            forced_bench=sorted(forced_bench or []),
            fatigue_threshold=fatigue_threshold,
            favor_offense=favor_offense,
            raw_args=raw_args.strip().lower(),
        )
        report_dir = get_reports_dir(save_name, "lineups")
        report_path = report_dir / report_filename("lineup_" + team_abbr.lower(), args_key)
        last_import = get_last_import_iso_for_save(save_name)
        if report_path.exists() and last_import:
            if report_path.stat().st_mtime > datetime.fromisoformat(last_import).timestamp():
                return str(report_path), None

    # Cache miss — query all data
    data = query_lineup(save_name, team_query=team_query, philosophy=philosophy,
                        opponent_hand=opponent_hand, excluded_names=excluded_names,
                        primary_only=primary_only, forced_starts=forced_starts,
                        forced_bench=forced_bench, fatigue_threshold=fatigue_threshold,
                        favor_offense=favor_offense)
    if data is None:
        return None, None

    # Extract private keys for HTML
    team_name = data.pop("_team_name")
    team_abbr = data.pop("_team_abbr")
    lineup = data.pop("_lineup")
    batters = data.pop("_batters")
    alt_score = data.pop("_alt_score")
    dh_used = data.pop("_dh_used")
    fatigue_benched = data.pop("_fatigue_benched")
    args_str = data.pop("_args_str")
    hand = data.pop("_hand")
    excluded_names = data.pop("_excluded_names")
    forced_bench = data.pop("_forced_bench")
    primary_only = data.pop("_primary_only")
    fatigue_threshold = data.pop("_fatigue_threshold")
    favor_offense = data.pop("_favor_offense")

    _disp = []
    if hand:
        _disp.append("vs LHP" if hand == "L" else "vs RHP")
    if primary_only:
        _disp.append("Primary only")
    if favor_offense:
        _disp.append("Favor offense")
    if excluded_names:
        names = ", ".join(excluded_names[:3]) + ("…" if len(excluded_names) > 3 else "")
        _disp.append(f"Excl: {names}")
    if forced_bench:
        _disp.append("Bench: " + ", ".join(forced_bench[:2]))
    if fatigue_threshold is not None:
        _disp.append(f"Fatigue ≤{fatigue_threshold}%")
    if raw_args.strip():
        _disp.append(raw_args.strip())
    args_display = " · ".join(_disp)

    html_content = build_html(
        team_name, team_abbr, philosophy, hand,
        lineup, batters, alt_score,
        dh_used, save_name, excluded_names,
        primary_only=primary_only,
        forced_bench=forced_bench,
        fatigue_threshold=fatigue_threshold,
        fatigue_benched=fatigue_benched,
        favor_offense=favor_offense,
        args_str=args_str,
        args_display=args_display,
    )
    write_report_html(report_path, html_content)

    return str(report_path), data
