"""Batting and pitching rate-stat calculators (pure functions, no DB)."""

from config import WOBA_BB, WOBA_HBP, WOBA_1B, WOBA_2B, WOBA_3B, WOBA_HR


def calc_rates(ab, h, d, t, hr, bb, k, hp, sf, pa, lg=None):
    if ab == 0 or pa == 0:
        return {}
    singles = h - d - t - hr
    ba = h / ab
    obp = (h + bb + hp) / (ab + bb + hp + sf)
    slg = (singles + 2 * d + 3 * t + 4 * hr) / ab
    ops = obp + slg
    iso = slg - ba
    k_pct = k / pa * 100
    bb_pct = bb / pa * 100
    babip_denom = ab - k - hr + sf
    babip = (h - hr) / babip_denom if babip_denom > 0 else 0.0

    woba_num = (WOBA_BB * bb + WOBA_HBP * hp +
                WOBA_1B * singles + WOBA_2B * d +
                WOBA_3B * t + WOBA_HR * hr)
    woba_den = ab + bb + hp + sf
    woba = woba_num / woba_den if woba_den > 0 else 0.0

    wrc_plus = None
    ops_plus = None
    if lg:
        lg_ab, lg_h, lg_d, lg_t, lg_hr, lg_bb, lg_hp, lg_sf, lg_pa, lg_r = lg
        lg_singles = lg_h - lg_d - lg_t - lg_hr
        lg_obp = (lg_h + lg_bb + lg_hp) / (lg_ab + lg_bb + lg_hp + lg_sf)
        lg_slg = (lg_singles + 2 * lg_d + 3 * lg_t + 4 * lg_hr) / lg_ab
        lg_woba_num = (WOBA_BB * lg_bb + WOBA_HBP * lg_hp +
                       WOBA_1B * lg_singles + WOBA_2B * lg_d +
                       WOBA_3B * lg_t + WOBA_HR * lg_hr)
        lg_woba = lg_woba_num / (lg_ab + lg_bb + lg_hp + lg_sf)
        lg_rpa = lg_r / lg_pa
        wrc_plus = ((woba - lg_woba) / 1.15 + lg_rpa) / lg_rpa * 100
        ops_plus = 100 * (obp / lg_obp + slg / lg_slg - 1)

    return dict(ba=ba, obp=obp, slg=slg, ops=ops, iso=iso, k_pct=k_pct,
                bb_pct=bb_pct, babip=babip, woba=woba, wrc_plus=wrc_plus, ops_plus=ops_plus)


def calc_pitching_rates(ip, ha, hra, bb, k, er, bf, hp, gb, fb, lg_pitch=None):
    """Compute ERA, FIP, xFIP, WHIP, K%, BB%, etc. for a pitcher season."""
    if ip == 0 or bf == 0:
        return {}
    era = er / ip * 9
    whip = (bb + ha) / ip
    k_pct = k / bf * 100
    bb_pct = bb / bf * 100
    k_bb_pct = k_pct - bb_pct
    hr_9 = hra / ip * 9
    k_9 = k / ip * 9
    bb_9 = bb / ip * 9
    babip_denom = bf - k - hra - bb - hp  # approximate AB - K - HR
    babip = (ha - hra) / babip_denom if babip_denom > 0 else 0.0
    total_balls = gb + fb
    gb_pct = gb / total_balls * 100 if total_balls > 0 else 0.0

    # FIP: (13*HR + 3*(BB+HBP) - 2*K) / IP + cFIP
    # cFIP = lgERA - (13*lgHR + 3*(lgBB+lgHBP) - 2*lgK) / lgIP
    fip = None
    xfip = None
    if lg_pitch:
        lg_ip, lg_hra, lg_bb, lg_hp, lg_k, lg_er = lg_pitch
        if lg_ip > 0:
            lg_era = lg_er / lg_ip * 9
            cfip = lg_era - (13 * lg_hra + 3 * (lg_bb + lg_hp) - 2 * lg_k) / lg_ip
            fip = (13 * hra + 3 * (bb + hp) - 2 * k) / ip + cfip
            # xFIP: replace HR with a rough league-average expected HR estimate
            if fb > 0:
                expected_hr = fb * (lg_hra / (lg_ip * 3)) * 3  # rough lg HR/FB
                xfip = (13 * expected_hr + 3 * (bb + hp) - 2 * k) / ip + cfip

    return dict(era=era, whip=whip, k_pct=k_pct, bb_pct=bb_pct, k_bb_pct=k_bb_pct,
                hr_9=hr_9, k_9=k_9, bb_9=bb_9, babip=babip, gb_pct=gb_pct,
                fip=fip, xfip=xfip)
