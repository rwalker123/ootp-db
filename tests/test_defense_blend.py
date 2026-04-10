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
        from ootp_db_constants import POS_SHORTSTOP as POS_SS

        from ratings.defense_blend import defense_score_from_rating_and_stats

        return POS_SS, defense_score_from_rating_and_stats
    finally:
        sys.path[:] = original


POS_SS, defense_score_from_rating_and_stats = _load_defense_blend()


class TestDefenseBlend(unittest.TestCase):
    def test_rating_only_fld_g_zero_gets_premium_multiplier(self):
        """No counting stats → rating-only path; SS still gets premium scale on score."""
        fielding = {"fielding_rating_pos6": 50}
        stats = {"fld_g": 0}
        s = defense_score_from_rating_and_stats(fielding, stats, POS_SS)
        # Rating (50-20)/60*100 = 50; premium 1.3 → 65
        self.assertAlmostEqual(s, 65.0, places=5)

    def test_empty_fielding_defaults_rating_fifty(self):
        stats = {"fld_g": 0}
        s = defense_score_from_rating_and_stats({}, stats, POS_SS)
        self.assertAlmostEqual(s, 65.0, places=5)

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
