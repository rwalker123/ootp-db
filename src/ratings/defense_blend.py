"""Shared defense rating: OOTP fielding rating + career fielding stats (batch + focus path).

Pandas-free so ``query_player_rating`` does not import ``compute``.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from config import (
    CATCHER_MIN_CS_ATTEMPTS,
    FIELDING_MIN_GAMES,
    OOTP_RATING_SCALE_MIN,
)
from ootp_db_constants import (
    POS_CATCHER,
    POS_FIRST_BASE as POS_1B,
    POS_SECOND_BASE as POS_2B,
    POS_THIRD_BASE as POS_3B,
    POS_SHORTSTOP as POS_SS,
    POS_LEFT_FIELD as POS_LF,
    POS_CENTER_FIELD as POS_CF,
    POS_RIGHT_FIELD as POS_RF,
)

from .constants import (
    DP_SCALE,
    POS_FIELD_COL,
    SCALE_RANGE,
    ZR_HALF_RANGE,
    apply_defense_position_score_multiplier,
)


def _clamp_num(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    if math.isnan(val):
        return 50.0
    return float(max(lo, min(hi, val)))


def _get(mapping: Any, key: str) -> Any:
    if mapping is None:
        return None
    if hasattr(mapping, "get"):
        return mapping.get(key)
    try:
        return mapping[key]
    except (KeyError, TypeError):
        return None


def _fval(stats_row: Mapping[str, Any] | Any, key: str, default: float = 0.0) -> float:
    v = _get(stats_row, key)
    if v is None:
        return default
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(fv):
        return default
    return fv


def _rating_from_fielding_column(fielding_row: Any, position: int) -> float:
    pos_col = POS_FIELD_COL.get(position)
    if not pos_col or fielding_row is None:
        return 50.0
    field_rating = _get(fielding_row, pos_col)
    if field_rating is None:
        return 50.0
    try:
        fr = float(field_rating)
    except (TypeError, ValueError):
        return 50.0
    if math.isnan(fr) or fr <= 0:
        return 50.0
    return _clamp_num((fr - OOTP_RATING_SCALE_MIN) / SCALE_RANGE * 100)


def defense_score_from_rating_and_stats(fielding_row: Any, stats_row: Any, position: int) -> float:
    """Blend OOTP position rating with counting stats; apply premium/low multiplier.

    ``stats_row`` should expose ``fld_g``, ``fld_tc``, ``fld_po``, ``fld_e``, ``fld_dp``,
    ``fld_pb``, ``fld_sba``, ``fld_rto``, ``fld_framing``, ``fld_arm``, ``fld_zr``
    (same names as batch ``fielding_cur``). Missing keys → 0.0 via :func:`_fval`.

    ``fielding_row`` is a mapping (e.g. ``players_fielding`` row) with ``fielding_rating_pos*``.
    """
    rating_score = _rating_from_fielding_column(fielding_row, position)

    fld_g = int(_fval(stats_row, "fld_g", 0.0))

    if fld_g < FIELDING_MIN_GAMES:
        score = rating_score
    else:
        half_range = ZR_HALF_RANGE.get(position, 5.0)
        zr_score = _clamp_num(50.0 + _fval(stats_row, "fld_zr", 0.0) / half_range * 50.0)

        tc = _fval(stats_row, "fld_tc", 0.0)
        e = _fval(stats_row, "fld_e", 0.0)
        fpct_score = (
            _clamp_num((((tc - e) / tc) - 0.950) / 0.035 * 100) if tc > 0 else 50.0
        )

        if position == POS_CATCHER:
            sba = _fval(stats_row, "fld_sba", 0.0)
            rto = _fval(stats_row, "fld_rto", 0.0)
            total_att = sba + rto
            cs_score = (
                _clamp_num(rto / total_att / 0.35 * 100)
                if total_att >= CATCHER_MIN_CS_ATTEMPTS
                else 50.0
            )

            framing = _fval(stats_row, "fld_framing", 0.0)
            framing_score = _clamp_num(50.0 + framing / 12.0 * 50.0)

            components = [
                (zr_score, 0.30),
                (fpct_score, 0.15),
                (cs_score, 0.30),
                (framing_score, 0.25),
            ]

        elif position in (POS_2B, POS_SS):
            dp_per_150 = _fval(stats_row, "fld_dp", 0.0) / fld_g * 150
            dp_min, dp_max = DP_SCALE[position]
            dp_score = _clamp_num((dp_per_150 - dp_min) / (dp_max - dp_min) * 100)
            components = [(zr_score, 0.40), (fpct_score, 0.20), (dp_score, 0.40)]

        elif position in (POS_3B, POS_1B):
            dp_per_150 = _fval(stats_row, "fld_dp", 0.0) / fld_g * 150
            dp_min, dp_max = DP_SCALE[position]
            dp_score = _clamp_num((dp_per_150 - dp_min) / (dp_max - dp_min) * 100)
            components = [(zr_score, 0.40), (fpct_score, 0.30), (dp_score, 0.30)]

        elif position == POS_CF:
            arm_score = _clamp_num(50.0 + _fval(stats_row, "fld_arm", 0.0) * 10.0)
            po_score = _clamp_num((_fval(stats_row, "fld_po", 0.0) / fld_g - 0.9) / 2.0 * 100)
            components = [(zr_score, 0.40), (fpct_score, 0.10), (arm_score, 0.20), (po_score, 0.30)]

        else:  # LF, RF
            arm_score = _clamp_num(50.0 + _fval(stats_row, "fld_arm", 0.0) * 10.0)
            components = [(zr_score, 0.40), (fpct_score, 0.20), (arm_score, 0.40)]

        total_w = sum(w for _, w in components)
        stats_score = sum(s * w for s, w in components) / total_w if total_w > 0 else 50.0

        score = rating_score * 0.50 + stats_score * 0.50

    return apply_defense_position_score_multiplier(score, position)
