"""Unit tests for ratings.defense_blend (pandas-free defense score)."""

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"


def _load_defense_blend():
    original = list(sys.path)
    try:
        p = str(_SRC)
        if p not in sys.path:
            sys.path.insert(0, p)
        from config import OOTP_RATING_SCALE_MIN
        from ootp_db_constants import POS_SHORTSTOP as POS_SS

        from ratings.constants import SCALE_RANGE, apply_defense_position_score_multiplier
        from ratings.defense_blend import defense_score_from_rating_and_stats

        return (
            POS_SS,
            defense_score_from_rating_and_stats,
            OOTP_RATING_SCALE_MIN,
            SCALE_RANGE,
            apply_defense_position_score_multiplier,
        )
    finally:
        sys.path[:] = original


(
    POS_SS,
    defense_score_from_rating_and_stats,
    _OOTP_RATING_SCALE_MIN,
    _SCALE_RANGE,
    _apply_defense_premium,
) = _load_defense_blend()


def _normalized_fielding_score(raw_ootp_rating: float) -> float:
    """Mirror ``_clamp_num`` + scale step in ``defense_blend._rating_from_fielding_column``."""
    return max(0.0, min(100.0, (raw_ootp_rating - _OOTP_RATING_SCALE_MIN) / _SCALE_RANGE * 100.0))


class TestDefenseBlend(unittest.TestCase):
    def test_rating_only_fld_g_zero_gets_premium_multiplier(self):
        """No counting stats → rating-only path; SS still gets premium scale on score."""
        fielding = {"fielding_rating_pos6": 50}
        stats = {"fld_g": 0}
        s = defense_score_from_rating_and_stats(fielding, stats, POS_SS)
        baseline = _normalized_fielding_score(50.0)
        expected = _apply_defense_premium(baseline, POS_SS)
        self.assertAlmostEqual(s, expected, places=5)

    def test_empty_fielding_defaults_rating_fifty(self):
        stats = {"fld_g": 0}
        s = defense_score_from_rating_and_stats({}, stats, POS_SS)
        # Missing column path uses a fixed 50 on the 0–100 axis (not raw OOTP scale).
        expected = _apply_defense_premium(50.0, POS_SS)
        self.assertAlmostEqual(s, expected, places=5)

    def test_ss_with_enough_games_blends_stats(self):
        fielding = {"fielding_rating_pos6": 50}
        stats = {
            "fld_g": 20,
            "fld_zr": 0.0,
            "fld_tc": 100,
            "fld_e": 5,
            "fld_dp": 10,
            "fld_po": 0,
            "fld_a": 0,
        }
        s = defense_score_from_rating_and_stats(fielding, stats, POS_SS)
        self.assertGreater(s, 0.0)
        self.assertLessEqual(s, 100.0)


if __name__ == "__main__":
    unittest.main()
