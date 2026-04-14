"""Unit tests for src/report_formatting.py shared presentation helpers."""

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"


def _load_report_formatting():
    original = list(sys.path)
    try:
        p = str(_SRC)
        if p not in sys.path:
            sys.path.insert(0, p)
        from report_formatting import (
            arb_status_label,
            fmt_salary,
            get_current_salary,
            get_years_remaining,
            grade_badge,
            greed_color,
            greed_label,
            injury_color,
            injury_label,
            letter_grade,
            row_bg,
            score_color,
            trait_color,
            trait_label,
        )
        return (
            arb_status_label,
            fmt_salary,
            get_current_salary,
            get_years_remaining,
            grade_badge,
            greed_color,
            greed_label,
            injury_color,
            injury_label,
            letter_grade,
            row_bg,
            score_color,
            trait_color,
            trait_label,
        )
    finally:
        sys.path[:] = original


(
    arb_status_label,
    fmt_salary,
    get_current_salary,
    get_years_remaining,
    grade_badge,
    greed_color,
    greed_label,
    injury_color,
    injury_label,
    letter_grade,
    row_bg,
    score_color,
    trait_color,
    trait_label,
) = _load_report_formatting()


class TestLetterGrade(unittest.TestCase):
    def test_a_plus(self):
        self.assertEqual(letter_grade(95), "A+")
        self.assertEqual(letter_grade(90), "A+")

    def test_a(self):
        self.assertEqual(letter_grade(85), "A")
        self.assertEqual(letter_grade(80), "A")

    def test_b_plus(self):
        self.assertEqual(letter_grade(75), "B+")
        self.assertEqual(letter_grade(70), "B+")

    def test_b(self):
        self.assertEqual(letter_grade(65), "B")
        self.assertEqual(letter_grade(60), "B")

    def test_c_plus(self):
        self.assertEqual(letter_grade(55), "C+")
        self.assertEqual(letter_grade(50), "C+")

    def test_c(self):
        self.assertEqual(letter_grade(45), "C")
        self.assertEqual(letter_grade(40), "C")

    def test_d(self):
        self.assertEqual(letter_grade(35), "D")
        self.assertEqual(letter_grade(30), "D")

    def test_f(self):
        self.assertEqual(letter_grade(29), "F")
        self.assertEqual(letter_grade(0), "F")


class TestGradeBadge(unittest.TestCase):
    def test_contains_grade(self):
        badge = grade_badge(85)
        self.assertIn("A", badge)

    def test_contains_score(self):
        badge = grade_badge(85)
        self.assertIn("85.0", badge)

    def test_green_for_a(self):
        self.assertIn("#1a7a1a", grade_badge(90))

    def test_blue_for_b(self):
        self.assertIn("#2266cc", grade_badge(65))

    def test_orange_for_c(self):
        self.assertIn("#cc7700", grade_badge(45))

    def test_red_for_d_f(self):
        self.assertIn("#cc2222", grade_badge(20))


class TestRowBg(unittest.TestCase):
    def test_green_tier(self):
        self.assertEqual(row_bg(70), "#f0fff0")
        self.assertEqual(row_bg(85), "#f0fff0")

    def test_yellow_tier(self):
        self.assertEqual(row_bg(50), "#fffff0")
        self.assertEqual(row_bg(69), "#fffff0")

    def test_white_tier(self):
        self.assertEqual(row_bg(49), "white")
        self.assertEqual(row_bg(0), "white")


class TestScoreColor(unittest.TestCase):
    def test_green(self):
        self.assertEqual(score_color(70), "#1a7a1a")

    def test_orange(self):
        self.assertEqual(score_color(55), "#cc7700")

    def test_red(self):
        self.assertEqual(score_color(30), "#cc2222")

    def test_none(self):
        self.assertEqual(score_color(None), "#888")


class TestInjuryLabel(unittest.TestCase):
    def test_none(self):
        self.assertEqual(injury_label(None), "—")

    def test_iron_man(self):
        self.assertEqual(injury_label(10), "Iron Man")

    def test_durable(self):
        self.assertEqual(injury_label(50), "Durable")

    def test_normal(self):
        self.assertEqual(injury_label(100), "Normal")

    def test_fragile(self):
        self.assertEqual(injury_label(150), "Fragile")

    def test_wrecked(self):
        self.assertEqual(injury_label(200), "Wrecked")


class TestInjuryColor(unittest.TestCase):
    def test_none(self):
        self.assertEqual(injury_color(None), "#888")

    def test_green_for_durable(self):
        self.assertEqual(injury_color(10), "#1a7a1a")

    def test_orange_for_normal(self):
        self.assertEqual(injury_color(100), "#cc7700")

    def test_red_for_fragile(self):
        self.assertEqual(injury_color(200), "#cc2222")


class TestTraitLabel(unittest.TestCase):
    def test_none(self):
        self.assertEqual(trait_label(None), "—")

    def test_very_low(self):
        self.assertEqual(trait_label(25), "Very Low")

    def test_low(self):
        self.assertEqual(trait_label(75), "Low")

    def test_average(self):
        self.assertEqual(trait_label(115), "Average")

    def test_high(self):
        self.assertEqual(trait_label(145), "High")

    def test_elite(self):
        self.assertEqual(trait_label(180), "Elite")


class TestTraitColor(unittest.TestCase):
    def test_none(self):
        self.assertEqual(trait_color(None), "#888")

    def test_green_for_high(self):
        self.assertEqual(trait_color(161), "#1a7a1a")

    def test_orange_for_mid(self):
        self.assertEqual(trait_color(110), "#cc7700")

    def test_red_for_low(self):
        self.assertEqual(trait_color(25), "#cc2222")

    def test_invert_green_for_low(self):
        self.assertEqual(trait_color(25, invert=True), "#1a7a1a")

    def test_invert_red_for_high(self):
        self.assertEqual(trait_color(180, invert=True), "#cc2222")


class TestGreedLabel(unittest.TestCase):
    def test_none(self):
        self.assertEqual(greed_label(None), "Unknown")

    def test_low(self):
        self.assertEqual(greed_label(50), "Low")

    def test_average(self):
        self.assertEqual(greed_label(100), "Average")

    def test_high(self):
        self.assertEqual(greed_label(145), "High")

    def test_demanding(self):
        self.assertEqual(greed_label(180), "Demanding")


class TestGreedColor(unittest.TestCase):
    def test_none(self):
        self.assertEqual(greed_color(None), "#888")

    def test_green_for_low(self):
        self.assertEqual(greed_color(50), "#1a7a1a")

    def test_red_for_demanding(self):
        self.assertEqual(greed_color(180), "#cc2222")


class TestFmtSalary(unittest.TestCase):
    def test_none(self):
        self.assertEqual(fmt_salary(None), "—")

    def test_zero(self):
        self.assertEqual(fmt_salary(0), "—")

    def test_millions(self):
        self.assertEqual(fmt_salary(5_000_000), "$5.0M")

    def test_thousands(self):
        self.assertEqual(fmt_salary(750_000), "$750K")

    def test_small(self):
        self.assertEqual(fmt_salary(500), "$500")


class TestGetCurrentSalary(unittest.TestCase):
    def test_reads_correct_year(self):
        d = {"current_year": 2, "salary0": 1_000_000, "salary2": 3_000_000}
        self.assertEqual(get_current_salary(d), 3_000_000)

    def test_clamps_at_9(self):
        d = {"current_year": 15, "salary9": 4_000_000}
        self.assertEqual(get_current_salary(d), 4_000_000)

    def test_missing_current_year_defaults_to_0(self):
        d = {"salary0": 2_000_000}
        self.assertEqual(get_current_salary(d), 2_000_000)


class TestGetYearsRemaining(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(get_years_remaining({"years": 4, "current_year": 1}), 3)

    def test_clamps_to_zero(self):
        self.assertEqual(get_years_remaining({"years": 2, "current_year": 5}), 0)

    def test_missing_keys(self):
        self.assertEqual(get_years_remaining({}), 0)


class TestArbStatusLabel(unittest.TestCase):
    def test_none(self):
        self.assertEqual(arb_status_label(None), "Unknown")

    def test_pre_arb(self):
        self.assertEqual(arb_status_label(1.0), "Pre-Arb")
        self.assertEqual(arb_status_label(2.9), "Pre-Arb")

    def test_arb_yr_1(self):
        self.assertEqual(arb_status_label(3.0), "Arb Yr 1")

    def test_arb_yr_2(self):
        self.assertEqual(arb_status_label(4.0), "Arb Yr 2")

    def test_arb_yr_3(self):
        self.assertEqual(arb_status_label(5.0), "Arb Yr 3")

    def test_fa_eligible(self):
        self.assertEqual(arb_status_label(6.0), "FA Eligible")
        self.assertEqual(arb_status_label(10.0), "FA Eligible")


if __name__ == "__main__":
    unittest.main()
