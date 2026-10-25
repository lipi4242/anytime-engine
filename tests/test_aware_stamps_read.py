#!/usr/bin/env python3
"""A state that already holds offset ("aware") stamps must read back without a TypeError.

The measured bug (fleet rollout 2026-10-25): rili-release-agent's vendored 0.2.1
engine was patched (its #69, 2026-09-15) to write timezone-aware stamps, so its
live state holds values like "2026-10-25T00:20:00+02:00". The 0.3 readers did
`naive now() - fromisoformat(aware)` -> TypeError in State.is_stale on every
tick, while the agent's own heartbeat (written before reduce) stayed green.
Receipts and clock.stamp() write offset stamps too, so any state can meet them.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _engine_isolation import IsolatedTestCase  # noqa: E402
from anytime_engine import clock, config, heartbeat  # noqa: E402
from anytime_engine.reducer import reduce, _skip_reason  # noqa: E402
from anytime_engine.registry import Concern, clear, register  # noqa: E402
from anytime_engine.state import State  # noqa: E402

NOW_UTC = datetime(2026, 10, 25, 0, 30, 0, tzinfo=timezone.utc)   # 02:30 CEST (+02:00)
TEN_MIN_AGO = "2026-10-25T02:20:00+02:00"      # Rilí's shape: agent-local with offset
TEN_MIN_AGO_UTC = "2026-10-25T00:20:00+00:00"  # same instant, another offset
TWO_HOURS_AGO = "2026-10-25T00:30:00+02:00"


class AwareCase(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self._real = clock._utcnow
        clock._utcnow = lambda: NOW_UTC
        (self.root / "mentat.json").write_text(json.dumps(
            {"schema": 1, "components": {"engine": {"timezone": "Europe/Budapest"}}}))

    def tearDown(self):
        clock._utcnow = self._real
        clear()
        super().tearDown()

    def state_like_rili(self) -> State:
        """Written to disk and loaded back, the way a tick sees it."""
        path = config.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": 1,
            "concern_last_run": {"release_scan": TEN_MIN_AGO, "old_one": TWO_HOURS_AGO,
                                 "utc_writer": TEN_MIN_AGO_UTC},
            "cache_timestamps": {"repos": TEN_MIN_AGO},
            "cache": {"repos": ["a", "b"]},
            "last_review_at": TEN_MIN_AGO,
        }))
        return State.load()


class TestStateReadsAwareStamps(AwareCase):
    def test_is_stale_fresh_aware_stamp_is_not_stale(self):
        self.assertFalse(self.state_like_rili().is_stale("release_scan", 60))

    def test_is_stale_old_aware_stamp_is_stale(self):
        self.assertTrue(self.state_like_rili().is_stale("old_one", 60))

    def test_is_stale_compares_instants_not_wall_digits(self):
        # 00:20+00:00 is 02:20 local: ten minutes ago, not two hours ten
        s = self.state_like_rili()
        self.assertFalse(s.is_stale("utc_writer", 60))
        self.assertTrue(s.is_stale("utc_writer", 5))

    def test_get_cache_with_aware_timestamp(self):
        s = self.state_like_rili()
        self.assertEqual(s.get_cache("repos", 60), ["a", "b"])
        self.assertIsNone(s.get_cache("repos", 5))

    def test_naive_stamps_still_work(self):
        s = State()
        s.concern_last_run["x"] = "2026-10-25T02:20:00"
        self.assertFalse(s.is_stale("x", 60))

    def test_skip_reason_with_aware_stamp(self):
        s = self.state_like_rili()
        self.assertEqual(_skip_reason("release_scan", s, clock.now()), "ran 10 min ago")

    def test_review_fallback_with_aware_last_review_at(self):
        # 23:45 UTC on the 24th is 01:45 local on the 25th: the night window of the 25th
        import os
        os.environ["ANYTIME_REVIEW_WINDOWS"] = "night:01:00"
        s = self.state_like_rili()
        s.last_review_at = "2026-10-24T23:45:00+00:00"
        self.assertEqual(s._serviced_today("2026-10-25"), {"night"})

    def test_reduce_over_aware_state_has_no_type_error(self):
        register(Concern(name="release_scan", description="scan", triggers=["hourly"],
                         should_run=lambda st: st.is_stale("release_scan", 60),
                         action="scan"))
        plan = reduce("hourly", self.state_like_rili())
        self.assertEqual(plan.get("actions"), [])


class TestHeartbeatReadsAwareStamp(AwareCase):
    def write_hb(self, last_tick_at: str) -> None:
        p = heartbeat.heartbeat_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"schema_version": 1, "pid": 1, "owner_token": "t",
                                 "started_at": last_tick_at, "last_tick_at": last_tick_at}))

    def test_fresh_aware_heartbeat_is_not_stale(self):
        self.write_hb(datetime.now().astimezone().isoformat())
        self.assertFalse(heartbeat.is_stale(90))

    def test_old_aware_heartbeat_is_stale(self):
        self.write_hb("2020-01-01T00:00:00+00:00")
        self.assertTrue(heartbeat.is_stale(90))


if __name__ == "__main__":
    unittest.main()
