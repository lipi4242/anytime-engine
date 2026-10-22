#!/usr/bin/env python3
"""bekotes pack — the weekly full reconciliation runs once, not on every tick.

Its stamp (`last_weekly_check`, per business) lives in the engine State cache:
a real tick persists it, a dry run does not. Success -> next one 7 days later;
failure -> retried at most once a day.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _bekotes_concern_fixture import DAY, HOUR, T, ConcernCase  # noqa: E402
from anytime_engine import tick  # noqa: E402

PLAN = "bekotes_frissites"
MIDNIGHT = (T + DAY).replace(hour=0, minute=0)


class TestWeeklyStamp(ConcernCase):

    def series(self, start, hours=24):
        """Real hourly ticks (state persisted, no executor) -> (planned, weekly calls)."""
        import anytime_bekotes.diff as d
        planned = 0
        with mock.patch.object(d, "unresolved_refs", wraps=d.unresolved_refs) as spy:
            for h in range(hours):
                plan = tick.run_tick("hourly", now=start + h * HOUR)
                planned += sum(a["concern"] == PLAN for a in plan["actions"])
        return planned, spy.call_count

    def test_quiet_weekly_due_day_checks_once_plans_nothing(self):
        self.map_file("terkep.md", "- (forrás: web:regi.txt)\n")
        self.cli("--baseline")
        self.assertEqual(self.series(MIDNIGHT), (0, 1))
        self.assertEqual(self.series(MIDNIGHT + DAY), (0, 0))       # next due in 7 days
        self.assertEqual(self.series(MIDNIGHT + 7 * DAY, hours=8), (0, 1))

    def test_failed_weekly_plans_at_most_once_a_day(self):
        self.map_file("terkep.md", "- (forrás: web:nincs.txt)\n")
        self.cli("--baseline")
        self.assertEqual(self.series(MIDNIGHT), (1, 1))
        self.assertEqual(self.series(MIDNIGHT + DAY), (1, 1))       # retried next day

    def test_dry_run_persists_no_stamp(self):
        self.cli("--baseline")
        import anytime_bekotes.diff as d
        with mock.patch.object(d, "unresolved_refs", wraps=d.unresolved_refs) as spy:
            for h in (8, 9):
                tick.run_tick("hourly", dry_run=True, now=MIDNIGHT + h * HOUR)
        self.assertEqual(spy.call_count, 2)
        self.assertFalse((self.root / "data" / "state" / "anytime-state.json").exists())


class TestWeeklyRule(ConcernCase):

    def compute(self, weekly, when=T):
        import anytime_bekotes.diff as d
        with mock.patch.object(d, "unresolved_refs", wraps=d.unresolved_refs) as spy:
            out = d.compute(self.biz, self.root, when, weekly=weekly)
        return out, spy.call_count

    def test_rule(self):
        self.map_file("terkep.md", "- (forrás: web:nincs.md)\n")
        self.cli("--baseline")
        iso = lambda t: t.isoformat()  # noqa: E731
        d, n = self.compute(None)
        self.assertEqual((d["deleted"], n), (["web:nincs.md"], 1))
        self.assertEqual(d["weekly"], {"at": iso(T), "ok": False, "unresolved": ["web:nincs.md"]})
        self.assertEqual(self.compute(d["weekly"])[0]["deleted"], ["web:nincs.md"])  # same instant
        self.assertEqual(self.compute(d["weekly"])[1], 0)
        later = self.compute(d["weekly"], T + HOUR)
        self.assertEqual((later[0]["deleted"], later[1], later[0]["weekly"]), ([], 0, None))
        self.assertEqual(self.compute(d["weekly"], T + DAY)[1], 1)         # failed: daily retry
        ok = {"at": iso(T - 6 * DAY), "ok": True, "unresolved": []}
        self.assertEqual(self.compute(ok)[1], 0)
        self.assertEqual(self.compute(dict(ok, at=iso(T - 7 * DAY)))[1], 1)


if __name__ == "__main__":
    unittest.main()
