#!/usr/bin/env python3
"""anytime_todo: when is an occurrence due (date, due_time, the task's tz, DST)
and what is owed for it (the receipts). Pure rules, no API.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _todo_fixture import TodoCase, task  # noqa: E402


def utc(*a) -> datetime:
    return datetime(*a, tzinfo=timezone.utc)


class TestIsDue(TodoCase):
    def setUp(self):
        super().setUp()
        self.due = self.mod("occurrence").is_due

    def test_by_date(self):
        now = utc(2026, 10, 28, 10, 0)                       # 11:00 in Budapest
        self.assertTrue(self.due(task("A", "2026-10-27"), now))
        self.assertTrue(self.due(task("A", "2026-10-28"), now))
        self.assertFalse(self.due(task("A", "2026-10-29"), now))

    def test_due_time_in_the_task_zone(self):
        t = task("A", "2026-10-28", time="11:30")
        self.assertFalse(self.due(t, utc(2026, 10, 28, 10, 29)))   # 11:29 CET
        self.assertTrue(self.due(t, utc(2026, 10, 28, 10, 30)))    # 11:30 CET

    def test_other_task_tz(self):
        t = task("A", "2026-10-28", time="08:00", tz="America/New_York")
        self.assertFalse(self.due(t, utc(2026, 10, 28, 11, 59)))   # 07:59 EDT
        self.assertTrue(self.due(t, utc(2026, 10, 28, 12, 0)))

    def test_dst_end_2026_10_25_does_not_fire_an_hour_early(self):
        t = task("A", "2026-10-25", time="07:00")              # Budapest: CET from 03:00
        self.assertFalse(self.due(t, utc(2026, 10, 25, 5, 30)))     # 06:30 CET (07:30 if CEST)
        self.assertTrue(self.due(t, utc(2026, 10, 25, 6, 0)))       # 07:00 CET

    def test_dst_repeated_hour_fires_on_the_first_pass(self):
        t = task("A", "2026-10-25", time="02:30")
        self.assertFalse(self.due(t, utc(2026, 10, 25, 0, 29)))     # 02:29 CEST
        self.assertTrue(self.due(t, utc(2026, 10, 25, 0, 30)))      # 02:30 CEST
        self.assertTrue(self.due(t, utc(2026, 10, 25, 1, 15)))      # 02:15 CET, second pass

    def test_dst_start_skipped_hour_still_fires(self):
        t = task("A", "2026-03-29", time="02:30")              # 02:00-03:00 does not exist
        self.assertFalse(self.due(t, utc(2026, 3, 29, 0, 59)))      # 01:59 CET
        self.assertTrue(self.due(t, utc(2026, 3, 29, 1, 0)))        # 03:00 CEST

    def test_not_open_archived_or_undated(self):
        now = utc(2026, 10, 28, 10, 0)
        self.assertFalse(self.due({**task("A", "2026-10-01"), "status": "done"}, now))
        self.assertFalse(self.due({**task("A", "2026-10-01"), "archived": 1}, now))
        self.assertFalse(self.due({**task("A", "2026-10-01"), "due_date": None}, now))

    def test_unreadable_zone_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.due(task("A", "2026-10-01", tz="Mars/Olympus"), utc(2026, 10, 28, 10, 0))

    def test_query_cutoff_covers_every_zone(self):
        cut = self.mod("occurrence").query_cutoff
        self.assertEqual(cut(utc(2026, 10, 28, 11, 0)), "2026-10-29")
        self.assertEqual(cut(utc(2026, 10, 28, 9, 0)), "2026-10-28")


class TestOwed(TodoCase):
    T = datetime(2026, 10, 28, 12, 0)
    R = timedelta(hours=6)

    def owed(self, **steps):
        return self.mod("occurrence").owed(
            {k: self.T - timedelta(hours=h) for k, h in steps.items()}, self.T, self.R)

    def test_fresh(self):
        self.assertEqual(self.owed(), "due")

    def test_worked_only_completion_is_owed(self):
        self.assertEqual(self.owed(started=2, worked=1), "complete_pending")

    def test_started_without_end_is_interrupted(self):
        self.assertEqual(self.owed(started=1), "interrupted")

    def test_held_waits_then_comes_back(self):
        self.assertIsNone(self.owed(started=3, held=2))
        self.assertEqual(self.owed(started=8, held=7), "due")

    def test_reopened_after_completion_is_new(self):
        self.assertEqual(self.owed(started=5, worked=4, completed=3), "due")
        self.assertEqual(self.owed(worked=4, completed=3, started=1), "interrupted")


if __name__ == "__main__":
    unittest.main()
