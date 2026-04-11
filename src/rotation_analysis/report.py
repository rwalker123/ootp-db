"""HTML report generation and caching for /rotation-analysis."""

from __future__ import annotations

import html as html_mod
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report_write import report_filename, write_report_html
from shared_css import (
    get_engine,
    get_last_import_iso_for_save,
    get_report_css,
    get_reports_dir,
)

from .constants import (
    FIP_XFIP_LUCK_THRESHOLD,
    MODE_LABELS,
    OPENER_SHORT_IP_LABEL,
    THROWS_LABEL,
)
from .queries import query_rotation


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def _fip_color(fip):
    if fip is None:
        return "#888"
    if fip <= 3.00:
        return "#1a7a1a"
    if fip <= 4.00:
        return "#cc7700"
    return "#cc2222"


def _era_color(era):
    if era is None:
        return "#888"
    if era <= 3.25:
        return "#1a7a1a"
    if era <= 4.50:
        return "#cc7700"
    return "#cc2222"


def _kpct_color(k_pct):
    if k_pct is None:
        return "#888"
    if k_pct >= 0.27:
        return "#1a7a1a"
    if k_pct >= 0.18:
        return "#cc7700"
    return "#cc2222"


def _whip_color(whip):
    if whip is None:
        return "#888"
    if whip <= 1.15:
        return "#1a7a1a"
    if whip <= 1.40:
        return "#cc7700"
    return "#cc2222"


def _score_color(score):
    if score >= 70:
        return "#1a7a1a"
    if score >= 50:
        return "#2266cc"
    if score >= 40:
        return "#cc7700"
    return "#cc2222"


def _fmt(val, fmt=".2f"):
    return f"{val:{fmt}}" if val is not None else "—"


def _fmt_pct(val):
    return f"{val:.1%}" if val is not None else "—"


def _fmt_ip(val):
    return f"{val:.1f}" if val is not None else "—"


# ---------------------------------------------------------------------------
# HTML row builders
# ---------------------------------------------------------------------------

def _rotation_row(slot_num, pitcher):
    """Return an HTML <tr> for a rotation card row."""
    name  = html_mod.escape(f"{pitcher.get('first_name','')} {pitcher.get('last_name','')}".strip())
    hand  = THROWS_LABEL.get(pitcher.get("throws"), "?")
    age   = pitcher.get("age") or "?"
    stats = pitcher.get("_stats") or {}
    score = pitcher.get("score") or 0
    flags = pitcher.get("_flags") or []

    fip     = stats.get("fip")
    xfip    = stats.get("xfip")
    ip      = stats.get("ip")
    gs      = stats.get("gs") or 0
    k_bb    = stats.get("k_bb_pct")
    whip    = stats.get("whip")
    era     = stats.get("era")
    stamina = pitcher.get("stamina")

    def _stamina_color(s):
        if s is None: return "#888"
        if s >= 60: return "#1a7a1a"
        if s >= 50: return "#cc7700"
        return "#cc2222"

    flag_badges = ""
    if pitcher.get("_forced"):
        flag_badges += ' <span style="color:#2266cc;font-size:11px;font-weight:bold" title="Force-included">[F]</span>'
    if flags:
        flag_badges += ' <span style="color:#cc2222;font-weight:bold" title="' + html_mod.escape("; ".join(flags)) + '">⚠</span>'

    stamina_cell = (
        f'<td style="color:{_stamina_color(stamina)};font-weight:bold">{stamina}</td>'
        if stamina is not None else "<td>—</td>"
    )

    slot_cell = f'<td style="font-size:15px;font-weight:900;color:#1a1a2e;width:24px">{slot_num}</td>'
    return f"""
      <tr>
        {slot_cell}
        <td class="left">{name}{flag_badges}</td>
        <td>{hand}</td>
        <td style="color:#555">{age}</td>
        {stamina_cell}
        <td style="color:{_fip_color(fip)};font-weight:bold">{_fmt(fip)}</td>
        <td style="color:{_fip_color(xfip)};font-weight:bold">{_fmt(xfip)}</td>
        <td style="color:{_era_color(era)};font-weight:bold">{_fmt(era)}</td>
        <td style="color:#555">{_fmt_ip(ip)}</td>
        <td style="color:#555">{gs}</td>
        <td style="color:{_kpct_color(k_bb)};font-weight:bold">{_fmt_pct(k_bb)}</td>
        <td style="color:{_whip_color(whip)};font-weight:bold">{_fmt(whip)}</td>
        <td style="background:#e8f5e9;color:{_score_color(score)};font-weight:bold">{score:.0f}</td>
      </tr>"""


def _depth_row(rank, pitcher):
    """Compact depth ladder row."""
    name  = html_mod.escape(f"{pitcher.get('first_name','')} {pitcher.get('last_name','')}".strip())
    hand  = THROWS_LABEL.get(pitcher.get("throws"), "?")
    age   = pitcher.get("age") or "?"
    stats = pitcher.get("_stats") or {}
    score = pitcher.get("score") or 0
    role_code = pitcher.get("role")
    role_label = {11: "SP", 12: "RP", 13: "CL"}.get(role_code, "?")

    fip  = stats.get("fip")
    ip   = stats.get("ip")
    gs   = stats.get("gs") or 0
    whip = stats.get("whip")

    return f"""
      <tr>
        <td style="color:#888;font-size:13px">{rank}</td>
        <td class="left">{name}</td>
        <td><span style="font-size:12px;background:#e0e8f0;padding:1px 5px;border-radius:3px">{role_label}</span></td>
        <td>{hand}</td>
        <td style="color:#555">{age}</td>
        <td style="color:{_fip_color(fip)};font-weight:bold">{_fmt(fip)}</td>
        <td style="color:#555">{_fmt_ip(ip)}</td>
        <td style="color:#555">{gs}</td>
        <td style="color:{_whip_color(whip)};font-weight:bold">{_fmt(whip)}</td>
        <td style="color:{_score_color(score)};font-weight:bold">{score:.0f}</td>
      </tr>"""


def _opener_pairing_rows(pairing):
    """Return two HTML <tr> rows for an opener+bulk pairing."""
    slot_display = pairing["slot"] + 1
    bulk   = pairing["bulk"]
    opener = pairing.get("opener")
    reason = pairing.get("reason", "")

    bulk_name   = html_mod.escape(f"{bulk.get('first_name','')} {bulk.get('last_name','')}".strip())
    bulk_hand   = THROWS_LABEL.get(bulk.get("throws"), "?")
    bulk_stats  = bulk.get("_stats") or {}
    bulk_fip    = bulk_stats.get("fip")

    if opener:
        opener_name  = html_mod.escape(f"{opener.get('first_name','')} {opener.get('last_name','')}".strip())
        opener_hand  = THROWS_LABEL.get(opener.get("throws"), "?")
        opener_stats = opener.get("_stats") or {}
        op_k_pct = opener_stats.get("k_pct")
        op_whip  = opener_stats.get("whip")
        op_fip   = opener_stats.get("fip")
        opener_row = f"""
      <tr style="background:#f0f8ff">
        <td style="color:#2266cc;font-weight:bold;font-size:12px">OPN</td>
        <td class="left" style="color:#2266cc">{opener_name}</td>
        <td>{opener_hand}</td>
        <td style="font-size:12px;color:#888">{OPENER_SHORT_IP_LABEL}</td>
        <td style="color:{_kpct_color(op_k_pct)};font-weight:bold">{_fmt_pct(op_k_pct)}</td>
        <td style="color:{_whip_color(op_whip)};font-weight:bold">{_fmt(op_whip)}</td>
        <td style="color:{_fip_color(op_fip)};font-weight:bold">{_fmt(op_fip)}</td>
        <td colspan="4" style="font-size:12px;color:#555;font-style:italic">{html_mod.escape(reason)}</td>
      </tr>"""
    else:
        opener_row = f"""
      <tr style="background:#fff8e1">
        <td colspan="11" style="color:#cc7700;font-style:italic">⚠ No viable opener found for slot #{slot_display}</td>
      </tr>"""

    bulk_row = f"""
      <tr>
        <td style="font-size:15px;font-weight:900;color:#1a1a2e">{slot_display}</td>
        <td class="left"><strong>{bulk_name}</strong> <span style="font-size:12px;color:#555">(Bulk)</span></td>
        <td>{bulk_hand}</td>
        <td colspan="8" style="color:{_fip_color(bulk_fip)};font-weight:bold">FIP {_fmt(bulk_fip)}</td>
      </tr>"""

    return opener_row + bulk_row


def _ootp_diff_row(diff):
    same = diff["same"]
    bg   = "background:#f0fff0" if same else ""
    move = diff["move_str"]
    move_color = "#1a7a1a" if same else "#cc7700"
    return f"""
      <tr style="{bg}">
        <td style="font-weight:bold;color:#1a1a2e">#{diff['slot']}</td>
        <td class="left">{html_mod.escape(diff['model_name'])}</td>
        <td class="left" style="color:#555">{html_mod.escape(diff['ootp_name'])}</td>
        <td style="color:{move_color};font-size:13px">{html_mod.escape(move)}</td>
      </tr>"""


# ---------------------------------------------------------------------------
# Full HTML report
# ---------------------------------------------------------------------------

def build_html(data, raw_args="", save_name=""):
    """Build the complete HTML report for rotation analysis.

    data: dict returned by query_rotation()
    Returns an HTML string.
    """
    team_name   = data["_team_name"]
    team_abbr   = data["_team_abbr"]
    mode        = data["_mode"]
    n_starters  = data["_n_starters"]
    rotation    = data["_rotation"]
    depth       = data["_depth"]
    pairings    = data["_opener_pairings"]
    ootp_diff   = data["_ootp_diff"]
    n_openers   = data["_n_openers"]
    six_man     = data["_six_man"]

    mode_label = MODE_LABELS.get(mode, mode.title())
    now_dt     = datetime.now()
    now_str    = now_dt.strftime("%B %d, %Y %I:%M %p")
    now_iso    = now_dt.strftime("%Y-%m-%dT%H:%M:%S")

    title_parts = [f"Rotation Analysis — {team_name}", mode_label]
    if six_man:
        title_parts.append("Six-Man")
    if n_openers > 0:
        opener_label = "Opener" if n_openers == 1 else f"{n_openers} Openers"
        title_parts.append(opener_label)
    report_title = " | ".join(title_parts)

    # ── Rotation card ──────────────────────────────────────────────────────
    rotation_rows = "\n".join(
        _rotation_row(i + 1, p) for i, p in enumerate(rotation)
    )

    # ── Depth ladder ──────────────────────────────────────────────────────
    depth_rows = "\n".join(
        _depth_row(n_starters + i + 1, p) for i, p in enumerate(depth)
    ) if depth else '<tr><td colspan="10" style="color:#888;font-style:italic">No additional depth available</td></tr>'

    # ── Vulnerability flags summary ────────────────────────────────────────
    vuln_items = []
    for slot_idx, pitcher in enumerate(rotation):
        flags = pitcher.get("_flags") or []
        if flags:
            pname = f"{pitcher.get('first_name','')} {pitcher.get('last_name','')}".strip()
            for flag in flags:
                vuln_items.append(
                    f'<li><strong>#{slot_idx+1} {html_mod.escape(pname)}:</strong> '
                    f'{html_mod.escape(flag)}</li>'
                )
    vuln_html = ("\n".join(vuln_items)
                 if vuln_items
                 else '<li style="color:#1a7a1a">No major vulnerability flags in this rotation.</li>')

    # ── Opener pairings section ────────────────────────────────────────────
    if pairings:
        opener_rows = "\n".join(_opener_pairing_rows(p) for p in pairings)
        opener_section = f"""
    <h2 style="color:#1a1a2e;border-bottom:2px solid #2c3e50;padding-bottom:6px;margin-top:28px">
      Opener Plan ({n_openers} day{"s" if n_openers > 1 else ""})
    </h2>
    <table>
      <thead>
        <tr>
          <th>Slot</th><th>Pitcher</th><th>Hand</th><th>IP/Note</th>
          <th>K%</th><th>WHIP</th><th>FIP</th><th colspan="4">Rationale</th>
        </tr>
      </thead>
      <tbody>
        {opener_rows}
      </tbody>
    </table>"""
    else:
        opener_section = ""

    # ── OOTP diff table ────────────────────────────────────────────────────
    ootp_diff_rows = "\n".join(_ootp_diff_row(d) for d in ootp_diff)

    css = get_report_css()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="ootp-generated" content="{now_iso}">
  <meta name="ootp-skill" content="rotation-analysis">
  <meta name="ootp-args" content="{html_mod.escape(raw_args.strip())}">
  <meta name="ootp-args-display" content="{html_mod.escape(raw_args.strip())}">
  <meta name="ootp-save" content="{html_mod.escape(save_name)}">
  <title>{html_mod.escape(report_title)}</title>
  <style>
    {css}
    .rotation-slot {{ font-size: 16px; font-weight: 900; color: #1a1a2e; }}
    .flag-warn {{ color: #cc2222; font-weight: bold; }}
    .opener-badge {{ background: #e3f2fd; color: #1565c0; padding: 1px 6px;
                     border-radius: 4px; font-size: 12px; font-weight: bold; }}
    .bulk-badge  {{ background: #e8f5e9; color: #2e7d32; padding: 1px 6px;
                     border-radius: 4px; font-size: 12px; font-weight: bold; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{html_mod.escape(report_title)}</h1>
      <p style="color:#aaa;margin:4px 0">Generated {now_str}</p>
    </div>

    <!-- ROTATION_SUMMARY -->

    <h2 style="color:#1a1a2e;border-bottom:2px solid #2c3e50;padding-bottom:6px;margin-top:24px">
      Recommended {n_starters}-Man Rotation
      <span style="font-size:14px;color:#555;font-weight:normal;margin-left:10px">{mode_label} mode</span>
    </h2>
    <table>
      <thead>
        <tr>
          <th>#</th><th>Pitcher</th><th>Hand</th><th>Age</th>
          <th title="Stamina rating (20-80 scale)">Stam</th>
          <th>FIP</th><th>xFIP</th><th>ERA</th><th>IP</th><th>GS</th>
          <th>K-BB%</th><th>WHIP</th><th>Score</th>
        </tr>
      </thead>
      <tbody>
        {rotation_rows}
      </tbody>
    </table>

    {opener_section}

    <h2 style="color:#1a1a2e;border-bottom:2px solid #2c3e50;padding-bottom:6px;margin-top:28px">
      Depth Ladder (Next Men Up)
    </h2>
    <table>
      <thead>
        <tr>
          <th>#</th><th>Pitcher</th><th>Role</th><th>Hand</th><th>Age</th>
          <th>FIP</th><th>IP</th><th>GS</th><th>WHIP</th><th>Score</th>
        </tr>
      </thead>
      <tbody>
        {depth_rows}
      </tbody>
    </table>

    <h2 style="color:#1a1a2e;border-bottom:2px solid #2c3e50;padding-bottom:6px;margin-top:28px">
      Vulnerability Flags
    </h2>
    <div class="summary" style="margin-bottom:16px">
      <ul style="margin:0;padding-left:20px;line-height:1.8">
        {vuln_html}
      </ul>
    </div>

    <h2 style="color:#1a1a2e;border-bottom:2px solid #2c3e50;padding-bottom:6px;margin-top:28px">
      vs OOTP Projected Rotation
    </h2>
    <p style="font-size:13px;color:#555;margin:0 0 8px">
      Comparing model-recommended slot order to OOTP's <em>projected_starting_pitchers</em>.
    </p>
    <table>
      <thead>
        <tr>
          <th>Slot</th>
          <th>Model Pick</th>
          <th>OOTP Pick</th>
          <th>Difference</th>
        </tr>
      </thead>
      <tbody>
        {ootp_diff_rows}
      </tbody>
    </table>

    <p style="font-size:12px;color:#aaa;margin-top:20px;text-align:right">
      Score = weighted composite (0–100); FIP/xFIP range 2.5–5.5 mapped to 100–0.
      Scores use {mode_label} mode weights.
    </p>
  </div>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Main entry point with caching
# ---------------------------------------------------------------------------

def generate_rotation_report(save_name, team_query=None, mode="balanced",
                              n_openers=0, six_man=False, excluded_names=None,
                              forced_names=None, raw_args=""):
    """Generate (or return cached) rotation analysis report.

    Returns:
        (path_str, data_dict)  on generation
        (path_str, None)       on cache hit
        (None, None)           on error / team not found
    """
    if mode not in ("balanced", "ace-first", "innings", "six-man"):
        mode = "balanced"
    excluded_names = list(excluded_names or [])

    # Need team_abbr for cache key — quick resolve
    engine = get_engine(save_name)
    from .queries import resolve_team
    with engine.connect() as conn:
        team_id, _, team_abbr = resolve_team(conn, team_query)
    if not team_id:
        return None, None

    forced_names = list(forced_names or [])
    args_key = dict(
        team_id=team_id,
        mode=mode,
        openers=n_openers,
        six_man=six_man,
        excluded=sorted(excluded_names),
        forced=sorted(n.lower() for n in forced_names),
    )
    report_dir  = get_reports_dir(save_name, "rotation")
    report_path = report_dir / report_filename("rotation_" + team_abbr.lower(), args_key)
    last_import = get_last_import_iso_for_save(save_name)

    if report_path.exists() and last_import:
        from datetime import datetime as _dt
        if report_path.stat().st_mtime > _dt.fromisoformat(last_import).timestamp():
            return str(report_path), None

    # Cache miss — run full query
    data = query_rotation(
        save_name,
        team_query=team_query,
        mode=mode,
        n_openers=n_openers,
        six_man=six_man,
        excluded_names=excluded_names,
        forced_names=forced_names,
    )
    if data is None:
        return None, None

    html_content = build_html(data, raw_args=raw_args, save_name=save_name)
    write_report_html(report_path, html_content)

    # Return a lightweight summary for the agent terminal output
    rotation = data.get("_rotation") or []
    summary = dict(
        team_name=data.get("_team_name"),
        mode=mode,
        n_starters=data.get("_n_starters"),
        n_openers=n_openers,
        rotation_names=[
            f"{p.get('first_name','')} {p.get('last_name','')}".strip()
            for p in rotation
        ],
        top_flag=next(
            (f for p in rotation for f in (p.get("_flags") or [])), None
        ),
        ootp_disagree=next(
            (d for d in (data.get("_ootp_diff") or []) if not d["same"]), None
        ),
    )
    return str(report_path), summary
