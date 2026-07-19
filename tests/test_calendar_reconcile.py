#!/usr/bin/env python3
"""Test suite for calendar_reconcile.

Compatible with both pytest and direct execution:
    pytest packages/anytime-engine/tests/ -v
    python3 packages/anytime-engine/tests/test_calendar_reconcile.py
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

try:
    import pytest  # noqa: F401  (both runners must import)
except Exception:  # pragma: no cover
    pytest = None

# Package layout: src/anytime_engine — make it importable when run in-place.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from anytime_engine.calendar_reconcile import changes_since, reconcile  # noqa: E402
from anytime_engine.calendar_reconcile_cli import (  # noqa: E402
    main, _normalize_gws_event, _prune,
)

WS = "2026-06-01T00:00:00+00:00"
WE = "2026-06-30T00:00:00+00:00"
NOW = datetime(2026, 6, 8, 9, 0, 0)


def _ev(eid, start, end=None, summary="S", location=""):
    return {"id": eid, "summary": summary, "start": start,
            "end": end or start, "location": location, "attendees": []}


class TestReconcile(unittest.TestCase):
    def test_empty_cache_all_added(self):
        fresh = [_ev("a", "2026-06-05T10:00:00+02:00")]
        updated, changes = reconcile(fresh, {}, WS, WE, NOW)
        self.assertIn("a", updated)
        self.assertEqual([c.type for c in changes], ["added"])

    def test_removed_in_window(self):
        cached = {"a": _ev("a", "2026-06-05T10:00:00+02:00")}
        updated, changes = reconcile([], cached, WS, WE, NOW)
        self.assertNotIn("a", updated)
        self.assertEqual([c.type for c in changes], ["removed"])

    def test_untouched_out_of_window(self):
        cached = {"a": _ev("a", "2026-09-05T10:00:00+02:00")}  # Sept, outside June window
        updated, changes = reconcile([], cached, WS, WE, NOW)
        self.assertIn("a", updated)
        self.assertEqual(changes, [])

    def test_unscanned_calendar_events_preserved(self):
        # Soft-skip: an in-window cached event from a calendar we did NOT scan
        # this run must be preserved, not deleted (no evidence it vanished).
        cached = {
            "t": {**_ev("t", "2026-06-05T10:00:00+02:00"),
                  "source_calendar": "someone@other-domain.example"},
            "p": {**_ev("p", "2026-06-06T10:00:00+02:00"),
                  "source_calendar": "primary@example.com"},
        }
        # Scanned only the primary calendar; fresh scan returned nothing (both
        # cached events look "missing" from the fresh set).
        updated, changes = reconcile([], cached, WS, WE, NOW,
                                     scanned_calendars={"primary@example.com"})
        self.assertIn("t", updated)                       # unscanned cal kept
        self.assertNotIn("p", updated)                    # scanned cal removed
        self.assertEqual([c.type for c in changes], ["removed"])
        self.assertEqual(changes[0].id, "p")

    def test_scoping_none_preserves_old_behavior(self):
        # scanned_calendars=None (the default) removes as before regardless of
        # any source_calendar tag — full backward compatibility.
        cached = {"a": {**_ev("a", "2026-06-05T10:00:00+02:00"),
                        "source_calendar": "x@y.com"}}
        updated, _ = reconcile([], cached, WS, WE, NOW)
        self.assertNotIn("a", updated)

    def test_untagged_event_removed_when_scoping_active(self):
        # A cached event with no source_calendar tag is still eligible for
        # removal even under scoping (src is None -> not skipped).
        cached = {"a": _ev("a", "2026-06-05T10:00:00+02:00")}
        updated, changes = reconcile([], cached, WS, WE, NOW,
                                     scanned_calendars={"primary@example.com"})
        self.assertNotIn("a", updated)
        self.assertEqual([c.type for c in changes], ["removed"])

    def test_moved(self):
        cached = {"a": _ev("a", "2026-06-05T10:00:00+02:00")}
        fresh = [_ev("a", "2026-06-06T10:00:00+02:00")]
        updated, changes = reconcile(fresh, cached, WS, WE, NOW)
        self.assertEqual([c.type for c in changes], ["moved"])
        self.assertEqual(updated["a"]["start"], "2026-06-06T10:00:00+02:00")

    def test_updated_fields(self):
        cached = {"a": _ev("a", "2026-06-05T10:00:00+02:00", summary="Old")}
        fresh = [_ev("a", "2026-06-05T10:00:00+02:00", summary="New")]
        updated, changes = reconcile(fresh, cached, WS, WE, NOW)
        self.assertEqual([c.type for c in changes], ["updated"])
        self.assertEqual(updated["a"]["summary"], "New")

    def test_tz_equal_no_false_move(self):
        # same instant, different representation -> no change
        cached = {"a": _ev("a", "2026-06-05T10:00:00+02:00", end="2026-06-05T11:00:00+02:00")}
        fresh = [_ev("a", "2026-06-05T08:00:00Z", end="2026-06-05T09:00:00Z")]
        updated, changes = reconcile(fresh, cached, WS, WE, NOW)
        self.assertEqual(changes, [])

    def test_replacement_remove_add(self):
        cached = {"A": _ev("A", "2026-06-01T00:00:00+00:00", summary="Tisza")}
        fresh = [_ev("B", "2026-06-05T00:00:00+00:00", summary="Duna")]
        updated, changes = reconcile(fresh, cached, WS, WE, NOW)
        types = sorted(c.type for c in changes)
        self.assertEqual(types, ["added", "removed"])
        self.assertIn("B", updated)
        self.assertNotIn("A", updated)

    def test_all_day_normalization(self):
        cached = {"a": _ev("a", "2026-06-05")}
        fresh = [_ev("a", "2026-06-05")]
        updated, changes = reconcile(fresh, cached, WS, WE, NOW)
        self.assertEqual(changes, [])

    def test_move_preserves_enrichment(self):
        cached = {"a": {"id": "a", "summary": "S", "start": "2026-06-05T10:00:00+00:00",
                        "end": "2026-06-05T11:00:00+00:00", "location": "", "attendees": [],
                        "prep_notes": "bring docs", "discussed": True, "first_seen": "x"}}
        fresh = [_ev("a", "2026-06-06T10:00:00+00:00", end="2026-06-06T11:00:00+00:00")]
        updated, changes = reconcile(fresh, cached, WS, WE, NOW)
        self.assertEqual([c.type for c in changes], ["moved"])
        self.assertEqual(updated["a"]["start"], "2026-06-06T10:00:00+00:00")  # scanned field updated
        self.assertEqual(updated["a"]["prep_notes"], "bring docs")            # enrichment kept
        self.assertTrue(updated["a"]["discussed"])
        self.assertEqual(updated["a"]["first_seen"], "x")

    def test_empty_fresh_all_removed(self):
        cached = {"a": _ev("a", "2026-06-05T10:00:00+00:00"),
                  "b": _ev("b", "2026-06-10T10:00:00+00:00")}
        updated, changes = reconcile([], cached, WS, WE, NOW)
        self.assertEqual(updated, {})
        self.assertEqual(sorted(c.type for c in changes), ["removed", "removed"])


class TestChangesSince(unittest.TestCase):
    def test_filter(self):
        feed = [{"detected_at": "2026-06-01T09:00:00", "id": "old"},
                {"detected_at": "2026-06-07T09:00:00", "id": "new"}]
        out = changes_since(feed, "2026-06-05T00:00:00")
        self.assertEqual([c["id"] for c in out], ["new"])
        self.assertEqual(len(changes_since(feed, None)), 2)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.state = os.path.join(self.dir, "current.json")
        self.fresh = os.path.join(self.dir, "fresh.json")

    def _write(self, path, obj):
        with open(path, "w") as f:
            json.dump(obj, f)

    def test_normalize_timed_and_allday(self):
        timed = _normalize_gws_event({"id": "x", "summary": "M",
            "start": {"dateTime": "2026-06-05T10:00:00+02:00"},
            "end": {"dateTime": "2026-06-05T11:00:00+02:00"}})
        self.assertEqual(timed["start"], "2026-06-05T10:00:00+02:00")
        allday = _normalize_gws_event({"id": "y", "start": {"date": "2026-06-05"},
            "end": {"date": "2026-06-06"}})
        self.assertEqual(allday["start"], "2026-06-05")

    def test_cli_reconciles_and_writes(self):
        self._write(self.state, {"calendar_events": {
            "A": {"id": "A", "summary": "Tisza", "start": "2026-06-01T00:00:00+00:00",
                  "end": "2026-06-07T00:00:00+00:00", "location": "", "attendees": []}}})
        self._write(self.fresh, {"items": [{"id": "B", "summary": "Duna",
            "start": {"dateTime": "2026-06-05T08:00:00+00:00"},
            "end": {"dateTime": "2026-06-05T18:00:00+00:00"}}]})
        rc = main(["--fresh", self.fresh, "--state", self.state,
                   "--window-start", WS, "--window-end", WE, "--now", "2026-06-08T09:00:00"])
        self.assertEqual(rc, 0)
        data = json.load(open(self.state))
        self.assertIn("B", data["calendar_events"])
        self.assertNotIn("A", data["calendar_events"])
        types = sorted(c["type"] for c in data["calendar_changes"])
        self.assertEqual(types, ["added", "removed"])
        self.assertEqual(data["calendar_scanned_window"], {"start": WS, "end": WE})

    def test_cli_missing_state_ok(self):
        self._write(self.fresh, {"items": []})
        rc = main(["--fresh", self.fresh, "--state", self.state,
                   "--window-start", WS, "--window-end", WE, "--now", "2026-06-08T09:00:00"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.state))

    def test_cli_malformed_fresh_no_write(self):
        with open(self.fresh, "w") as f:
            f.write("{not json")
        rc = main(["--fresh", self.fresh, "--state", self.state,
                   "--window-start", WS, "--window-end", WE])
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(self.state))  # never created on bad input

    def test_prune_drops_old(self):
        now = datetime(2026, 6, 8, 9, 0, 0)
        feed = [{"type": "added", "detected_at": "2026-06-07T09:00:00", "id": "n"},
                {"type": "added", "detected_at": "2026-04-01T09:00:00", "id": "o"}]
        kept = _prune(feed, now, days=30)
        self.assertEqual([c["id"] for c in kept], ["n"])


if __name__ == "__main__":
    unittest.main()
