"""Shared CSS and utilities for all OOTP HTML reports.

Visual design based on the polished rating report style:
- Dark navy header (#1a1a2e) with gold accent (#f0c040)
- White card container with shadow and rounded corners
- Consistent table headers, tag colors, flag pills, bar charts
"""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_reports_dir(save_name: str, report_type: str) -> Path:
    """Return the report directory for a save/type, creating it if needed.

    Path: <project_root>/reports/<save_name>/<report_type>/
    """
    d = _PROJECT_ROOT / "reports" / save_name / report_type
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_report_css(max_width="920px"):
    """Return CSS for embedding in a report's <style> tag.

    max_width: container width — use "920px" for ratings/FA,
               "1400px" for player-stats (wider stats tables).
    """
    return f"""
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
         font-size: 13px; background: #f5f5f5; color: #222; }}
  .container {{ max-width: {max_width}; margin: 24px auto; background: #fff;
               border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.12); overflow: hidden; }}

  /* ── Page header (dark navy band) ─────────────────────────────────── */
  .page-header {{ background: #1a1a2e; color: #fff; padding: 20px 24px; }}
  .header-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .player-name {{ font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }}
  .player-meta {{ font-size: 13px; color: #aaa; margin-top: 4px; }}
  .grade-badge {{ font-size: 42px; font-weight: 900; color: #f0c040; line-height: 1; }}
  .rating-bar-wrap {{ margin-top: 14px; display: flex; align-items: center; gap: 10px; }}
  .rating-label {{ font-size: 12px; color: #aaa; }}
  .rating-val {{ font-size: 20px; font-weight: 700; color: #f0c040; }}
  .oa-pot {{ font-size: 13px; color: #ccc; }}
  .import-ts {{ font-size: 11px; color: #666; margin-top: 6px; }}
  /* OA/POT inline badges (used in player-stats header) */
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 4px;
            font-weight: bold; font-size: 13px; }}
  .badge-oa  {{ background: #2266cc; color: white; }}
  .badge-pot {{ background: #228844; color: white; }}
  /* Legacy class names used in player-stats */
  .oa  {{ background: #2266cc; color: white; }}
  .pot {{ background: #228844; color: white; }}

  /* ── Sections ──────────────────────────────────────────────────────── */
  .section {{ padding: 16px 24px; border-top: 1px solid #eee; }}
  .section-title {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
                   letter-spacing: 0.8px; color: #555; margin-bottom: 10px; }}
  /* h2/h3 for player-stats compatibility — styled to match section-title */
  h2 {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.8px; color: #555; margin: 20px 24px 8px;
        padding-bottom: 0; border: none; }}
  h3 {{ font-size: 11px; color: #777; margin: 12px 0 6px;
        font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}

  /* ── Tables ────────────────────────────────────────────────────────── */
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 0 0 8px; }}
  th {{ background: #2c2c3e; color: #fff; padding: 7px 10px; text-align: center;
        font-size: 11px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.5px; white-space: nowrap; }}
  td {{ padding: 6px 10px; text-align: center; vertical-align: middle;
        white-space: nowrap; border-bottom: 1px solid #eee; }}
  tr:nth-child(even) td {{ background: #f9f9f9; }}
  tr:hover td {{ background: #f0f4f8; }}
  .left {{ text-align: left; }}

  /* ── Score bars ─────────────────────────────────────────────────────── */
  .bar-bg {{ background: #e8e8e8; border-radius: 4px; height: 10px; width: 180px;
             overflow: hidden; display: inline-block; vertical-align: middle; }}
  .bar-fill {{ height: 100%; border-radius: 4px; }}
  .bar-green  {{ background: #27ae60; }}
  .bar-yellow {{ background: #f39c12; }}
  .bar-red    {{ background: #e74c3c; }}
  .score-num  {{ font-weight: 700; }}

  /* ── Semantic value tags ────────────────────────────────────────────── */
  .tag {{ display: inline-block; border-radius: 4px; padding: 2px 8px;
          font-size: 11px; font-weight: 700; }}
  .tag-good    {{ background: #d4edda; color: #155724; }}
  .tag-warn    {{ background: #fff3cd; color: #856404; }}
  .tag-bad     {{ background: #f8d7da; color: #721c24; }}
  .tag-neutral {{ background: #e2e3e5; color: #383d41; }}

  /* ── Pill flags ─────────────────────────────────────────────────────── */
  .flags {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }}
  .flag {{ display: inline-block; border-radius: 14px; padding: 4px 14px;
           font-size: 12px; font-weight: 700; letter-spacing: 0.3px; }}
  .flag-blue   {{ background: #cce5ff; color: #004085; }}
  .flag-yellow {{ background: #fff3cd; color: #856404; }}
  .flag-green  {{ background: #d4edda; color: #155724; }}
  .flag-red    {{ background: #f8d7da; color: #721c24; }}

  /* ── Rank badge ─────────────────────────────────────────────────────── */
  .rank-badge {{ display: inline-block; background: #1a1a2e; color: #f0c040;
                font-size: 13px; font-weight: 700; border-radius: 6px;
                padding: 6px 14px; margin-top: 4px; }}

  /* ── Analysis / summary blocks ──────────────────────────────────────── */
  .summary {{ background: #f8f9fc; border-left: 4px solid #1a1a2e;
              padding: 12px 16px; margin: 8px 0; border-radius: 0 4px 4px 0; }}
  .summary ul, ul.bullets {{ padding-left: 18px; }}
  .summary li, ul.bullets li {{ margin-bottom: 6px; line-height: 1.5; }}
  /* Callout variant (free-agents search summary) */
  .callout {{ background: #f0f4ff; border-left: 4px solid #2266cc;
              padding: 12px 16px; margin: 8px 0; font-size: 13px;
              border-radius: 0 4px 4px 0; }}

  /* ── Inline value highlights ────────────────────────────────────────── */
  .good {{ color: #1a7a3c; font-weight: 700; }}
  .poor {{ color: #c0392b; font-weight: 700; }}
  .avg  {{ color: #8a6000; }}

  /* ── Stale data warning ─────────────────────────────────────────────── */
  .stale-banner {{ background: #fff3cd; border: 1px solid #ffc107;
                  padding: 8px 12px; border-radius: 4px; margin: 8px 0;
                  font-size: 13px; }}

  /* ── Player-stats multi-column layout ──────────────────────────────── */
  .ratings-grid {{ display: flex; gap: 20px; flex-wrap: wrap; }}
  .ratings-grid table {{ min-width: 180px; width: auto; }}
  .splits-container {{ display: flex; flex-direction: column; gap: 16px; }}
  .split-note {{ font-size: 11px; color: #888; margin-top: 6px; }}

  /* ── Index page ─────────────────────────────────────────────────────── */
  .ts {{ color: #999; font-size: 12px; margin-top: 4px; }}
  a {{ color: #2266cc; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .stale-badge {{ color: #cc7700; font-weight: bold; font-size: 12px; }}
"""
