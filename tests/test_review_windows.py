#!/usr/bin/env python3
"""Tests for the unified review-window model (config-driven).

Compatible with both pytest and direct execution:
    pytest packages/anytime-engine/tests/test_review_windows.py -v
    python3 packages/anytime-engine/tests/test_review_windows.py

The engine is domain-free: review windows come from config.review_windows(),
sourced from the ANYTIME_REVIEW_WINDOWS env var (or auto-named from
ANYTIME_REVIEW_TIMES). These tests pin an explicit four-window config so the
model's behaviour is deterministic regardless of the deployed default, then
build in-memory State objects with an explicit `now`/`when` so they never touch
the production state file.

The idempotent-audit tests are NOT ported here: the review audit
(append_review_audit / REVIEW_AUDIT) is a consumer-side (Thufir) concern, not
part of the domain-free engine.
"""

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

try:  # importable under both stdlib unittest and pytest
    import pytest  # noqa: F401
except ImportError:  # pragma: no cover
    pytest = None

# Package layout: src/anytime_engine — importable when run in-place.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from anytime_engine import config  # noqa: E402
from anytime_engine.state import State  # noqa: E402

# The canonical four-window cadence this model was designed around.
_WINDOWS_ENV = "morning:05:57,midday:12:27,evening:16:57,end_of_day:22:00"


def setUpModule():  # noqa: N802 — unittest hook name
    """Pin the four-window config for every test in this module. config reads
    the env var live on each call, so setting it here is enough."""
    global _PREV_WINDOWS, _PREV_TIMES
    _PREV_WINDOWS = os.environ.get("ANYTIME_REVIEW_WINDOWS")
    _PREV_TIMES = os.environ.get("ANYTIME_REVIEW_TIMES")
    os.environ["ANYTIME_REVIEW_WINDOWS"] = _WINDOWS_ENV
    os.environ.pop("ANYTIME_REVIEW_TIMES", None)


def tearDownModule():  # noqa: N802 — unittest hook name
    for key, prev in (("ANYTIME_REVIEW_WINDOWS", _PREV_WINDOWS),
                      ("ANYTIME_REVIEW_TIMES", _PREV_TIMES)):
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev


def _dt(hhmm: str, day: str = "2026-07-10") -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00")


class TestWindowConfig(unittest.TestCase):
    def test_windows_sorted_and_named(self):
        windows = config.review_windows()
        self.assertEqual([n for n, _ in windows],
                         ["morning", "midday", "evening", "end_of_day"])
        self.assertEqual([t for _, t in windows],
                         ["05:57", "12:27", "16:57", "22:00"])

    def test_explicit_windows_override_times(self):
        # ANYTIME_REVIEW_WINDOWS pins names+times independently of
        # ANYTIME_REVIEW_TIMES — an explicit windows config wins.
        self.assertEqual(
            config.review_windows(),
            [("morning", "05:57"), ("midday", "12:27"),
             ("evening", "16:57"), ("end_of_day", "22:00")],
        )


class TestWindowModel(unittest.TestCase):
    def test_current_window_boundaries(self):
        cw = State._current_window
        self.assertIsNone(cw(_dt("03:00")))            # before first window
        self.assertEqual(cw(_dt("05:57"))[0], "morning")
        self.assertEqual(cw(_dt("12:00"))[0], "morning")   # NOT yet midday
        self.assertEqual(cw(_dt("12:27"))[0], "midday")
        self.assertEqual(cw(_dt("16:00"))[0], "midday")
        self.assertEqual(cw(_dt("16:57"))[0], "evening")
        self.assertEqual(cw(_dt("21:00"))[0], "evening")
        self.assertEqual(cw(_dt("22:00"))[0], "end_of_day")
        self.assertEqual(cw(_dt("23:59"))[0], "end_of_day")

    def test_review_type_matches_windows(self):
        s = State()
        # The case that bit us on 2026-07-10: 11:24 is the MORNING window,
        # not midday — review_type and review_due now agree on that.
        self.assertEqual(s.review_type(_dt("11:24")), "morning")
        self.assertEqual(s.review_type(_dt("13:00")), "midday")
        self.assertEqual(s.review_type(_dt("17:30")), "evening")
        self.assertEqual(s.review_type(_dt("22:30")), "end_of_day")
        self.assertEqual(s.review_type(_dt("03:00")), "morning")  # pre-first default


class TestReviewDue(unittest.TestCase):
    def test_due_when_current_window_unserviced(self):
        s = State()
        self.assertTrue(s.review_due(_dt("13:00")))   # midday open, unserviced

    def test_not_due_before_first_window(self):
        s = State()
        self.assertFalse(s.review_due(_dt("04:00")))

    def test_serviced_window_does_not_retrigger(self):
        # A review sent in the midday window must keep review_due False for the
        # rest of that window, then flip True at evening.
        s = State()
        s.mark_review_serviced(when=_dt("13:00"))
        self.assertEqual(s.reviews_serviced["2026-07-10"], ["midday"])
        self.assertFalse(s.review_due(_dt("13:30")))
        self.assertFalse(s.review_due(_dt("14:00")))
        self.assertFalse(s.review_due(_dt("16:00")))
        self.assertTrue(s.review_due(_dt("17:00")))    # evening window opens

    def test_early_send_services_its_window(self):
        # Sending right at 12:30 services midday; no re-trigger later that window.
        s = State()
        s.mark_review_serviced(when=_dt("12:30"))
        self.assertFalse(s.review_due(_dt("15:00")))

    def test_evening_then_end_of_day(self):
        s = State()
        s.mark_review_serviced(when=_dt("17:05"))       # evening
        self.assertFalse(s.review_due(_dt("20:00")))    # still evening window
        self.assertTrue(s.review_due(_dt("22:05")))     # end_of_day opens


class TestBackwardCompat(unittest.TestCase):
    def test_derives_serviced_from_last_review_at(self):
        # Old state files have no reviews_serviced; derive from last_review_at so
        # the live loop transitions without a duplicate on the refactor deploy.
        s = State({
            "last_review_at": "2026-07-10T13:28:00",
            "last_review_type": "midday",
        })
        self.assertEqual(s.reviews_serviced, {})
        self.assertFalse(s.review_due(_dt("14:00")))    # midday derived-serviced
        self.assertTrue(s.review_due(_dt("17:00")))     # evening still due

    def test_stale_last_review_from_yesterday_is_not_serviced(self):
        s = State({
            "last_review_at": "2026-07-09T17:00:00",
            "last_review_type": "evening",
        })
        self.assertTrue(s.review_due(_dt("13:00")))     # today's midday still due


class TestMissedWindows(unittest.TestCase):
    def test_missed_windows_listed(self):
        s = State()  # nothing serviced today
        self.assertEqual(s.missed_review_windows(_dt("17:00")), ["morning", "midday"])

    def test_no_missed_when_serviced(self):
        s = State()
        s.mark_review_serviced(when=_dt("06:00"))       # morning
        s.mark_review_serviced(when=_dt("12:30"))       # midday
        self.assertEqual(s.missed_review_windows(_dt("17:00")), [])


class TestPruneServiced(unittest.TestCase):
    def test_old_dates_pruned(self):
        s = State({"reviews_serviced": {"2026-07-01": ["morning"]}})
        s.mark_review_serviced(when=_dt("13:00"))
        self.assertNotIn("2026-07-01", s.reviews_serviced)
        self.assertIn("2026-07-10", s.reviews_serviced)


class TestSummaryExposesServiced(unittest.TestCase):
    def test_summary_lists_serviced_today(self):
        s = State()
        s.mark_review_serviced(when=_dt("06:00"))       # morning
        s.mark_review_serviced(when=_dt("12:30"))       # midday
        summ = s.summary()
        # summary() uses the real "today"; assert the field exists and is sorted.
        self.assertIn("reviews_serviced_today", summ)
        self.assertEqual(summ["reviews_serviced_today"],
                         sorted(summ["reviews_serviced_today"]))


if __name__ == "__main__":
    unittest.main()
