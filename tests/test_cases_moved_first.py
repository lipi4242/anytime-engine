#!/usr/bin/env python3
"""A first month with its own date stays in the series (found in an acceptance run).

Gas from now on by the 10th, but October's 10th has passed: October is due on
the 20th — `recurrence: monthly:10`, `anchor_at: 2026-10-10`, `due_at: 2026-10-20`.
The markdown backend must read that as the admin does: the earliest open
occurrence is on the 20th (not overdue since the 10th), then every 10th.

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
    from anytime_cases.due import open_dates  # noqa: E402
except ImportError:  # pack not vendored into this repo
    raise unittest.SkipTest("anytime_cases pack not present")

GAS = {"status": "open", "recurrence": "monthly:10", "anchor_at": "2026-10-10", "due_at": "2026-10-20",
       "occurrences": []}
d = date.fromisoformat


class TestMovedFirstOccurrence(unittest.TestCase):
    def test_the_moved_october_is_due_on_the_20th(self):
        self.assertEqual(open_dates(GAS, d("2026-10-19")), [])
        self.assertEqual(open_dates(GAS, d("2026-11-10")), [d("2026-10-20"), d("2026-11-10")])

    def test_after_closing_october_the_series_goes_on(self):
        paid = {**GAS, "due_at": "2026-11-10", "occurrences": [{"due_at": "2026-10-10", "status": "done"}]}
        self.assertEqual(open_dates(paid, d("2026-12-10")), [d("2026-11-10"), d("2026-12-10")])

    def test_a_due_at_outside_the_period_is_ignored(self):
        # a stale or hand-written due_at past the next date does not hide an open month
        stale = {**GAS, "due_at": "2026-11-20"}
        self.assertEqual(open_dates(stale, d("2026-11-10")), [d("2026-10-10"), d("2026-11-10")])


if __name__ == "__main__":
    unittest.main()
