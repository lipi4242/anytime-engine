#!/usr/bin/env python3
"""Anchored recurrence: the month-end rule and its cousins.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from anytime_cases.recurrence import RecurrenceError, occurrences  # noqa: E402
except ImportError:  # pack not vendored into this repo
    raise unittest.SkipTest("anytime_cases pack not present")


def d(s: str) -> date:
    return date.fromisoformat(s)


class TestRecurrence(unittest.TestCase):
    def test_monthly_10(self):
        self.assertEqual(occurrences("monthly:10", d("2026-08-10"), d("2026-11-10")),
                         [d("2026-08-10"), d("2026-09-10"), d("2026-10-10"), d("2026-11-10")])

    def test_monthly_31_falls_on_the_last_day_of_short_months(self):
        self.assertEqual(occurrences("monthly:31", d("2026-01-31"), d("2026-04-30")),
                         [d("2026-01-31"), d("2026-02-28"), d("2026-03-31"), d("2026-04-30")])

    def test_monthly_31_in_a_leap_february(self):
        self.assertIn(d("2028-02-29"), occurrences("monthly:31", d("2028-01-31"), d("2028-03-01")))

    def test_short_month_does_not_shift_the_series(self):
        # after Feb 28 the series returns to the 30th, not the 28th
        self.assertEqual(occurrences("monthly:30", d("2026-02-28"), d("2026-03-31")),
                         [d("2026-02-28"), d("2026-03-30")])

    def test_anchor_before_the_rule_day_starts_on_the_rule_day(self):
        self.assertEqual(occurrences("monthly:10", d("2026-10-05"), d("2026-10-31")),
                         [d("2026-10-10")])

    def test_yearly_feb_29(self):
        self.assertEqual(occurrences("yearly:02-29", d("2027-02-28"), d("2028-12-31")),
                         [d("2027-02-28"), d("2028-02-29")])

    def test_yearly_05_20(self):
        self.assertEqual(occurrences("yearly:05-20", d("2026-05-20"), d("2027-06-01")),
                         [d("2026-05-20"), d("2027-05-20")])

    def test_weekly(self):
        # 2026-10-15 is a Thursday; the first Monday on/after is the 19th
        self.assertEqual(occurrences("weekly:mon", d("2026-10-15"), d("2026-10-27")),
                         [d("2026-10-19"), d("2026-10-26")])

    # quarterly:<day> — the phase is the anchor's month; the rows are the
    # admin's shared table (mentat-admin agent/cases/tests/series.json).
    def test_quarterly_steps_three_months_and_rolls_over_the_year(self):
        self.assertEqual(occurrences("quarterly:20", d("2026-01-20"), d("2027-01-20")),
                         [d("2026-01-20"), d("2026-04-20"), d("2026-07-20"), d("2026-10-20"), d("2027-01-20")])

    def test_quarterly_31_in_february_and_april(self):
        self.assertEqual(occurrences("quarterly:31", d("2026-11-30"), d("2027-08-31")),
                         [d("2026-11-30"), d("2027-02-28"), d("2027-05-31"), d("2027-08-31")])
        self.assertEqual(occurrences("quarterly:31", d("2027-01-31"), d("2027-07-31")),
                         [d("2027-01-31"), d("2027-04-30"), d("2027-07-31")])
        self.assertIn(d("2028-02-29"), occurrences("quarterly:31", d("2027-11-30"), d("2028-03-01")))

    def test_unknown_rules_are_refused(self):
        for rule in ("daily", "monthly:0", "monthly:32", "yearly:13-01", "weekly:xyz", "monthly:x",
                     "quarterly", "quarterly:0", "quarterly:32"):
            with self.subTest(rule=rule), self.assertRaises(RecurrenceError):
                occurrences(rule, d("2026-01-01"), d("2026-12-31"))


if __name__ == "__main__":
    unittest.main()
