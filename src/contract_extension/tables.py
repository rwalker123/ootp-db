"""HTML table builders and scalar extractors for the contract extension advisor."""

from .formatting import (
    arb_status_label,
    fmt_salary,
    get_current_salary,
    get_years_remaining,
    grade_badge,
    safe_div,
    _ev_color,
    _f1,
    _f2,
    _f3,
    _pct,
    _pct_color,
    _xwoba_color,
)


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
