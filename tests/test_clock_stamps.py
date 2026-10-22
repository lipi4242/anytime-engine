#!/usr/bin/env python3
"""Stamps the agent reads carry their UTC offset.

The measured bug (acceptance run 2026-10-19, section 10): a delivery receipt
said "at": "2026-10-19T13:17:03" (Budapest, correct) while `ls` showed the
outbox file at 11:17 (the box's UTC). The agent took the receipt for UTC and
told the user "15:17 local time". A stamp with its offset cannot be misread.

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
from anytime_engine import clock, receipts  # noqa: E402
from anytime_engine.state import State  # noqa: E402

SUMMER = datetime(2026, 10, 19, 11, 17, 3, tzinfo=timezone.utc)   # 13:17 CEST
WINTER = datetime(2026, 12, 10, 7, 17, 3, tzinfo=timezone.utc)    # 08:17 CET


class StampCase(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self._real = clock._utcnow
        (self.root / "mentat.json").write_text(json.dumps(
            {"schema": 1, "components": {"engine": {"timezone": "Europe/Budapest"}}}))

    def tearDown(self):
        clock._utcnow = self._real
        super().tearDown()

    def receipt_at(self, utc: datetime) -> str:
        clock._utcnow = lambda: utc
        State().mark_run("delivered:cases_morning:x")
        lines = receipts.path().read_text().splitlines()
        return json.loads(lines[-1])["at"]


class TestReceiptStamp(StampCase):
    def test_summer_receipt_says_local_time_with_its_offset(self):
        self.assertEqual(self.receipt_at(SUMMER), "2026-10-19T13:17:03+02:00")

    def test_winter_receipt_says_local_time_with_its_offset(self):
        self.assertEqual(self.receipt_at(WINTER), "2026-12-10T08:17:03+01:00")

    def test_old_naive_and_new_offset_receipts_still_compare(self):
        p = receipts.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"concern": "ping", "trigger": "hourly",
                                 "at": "2026-10-19T12:00:00", "result": "ok"}) + "\n")
        clock._utcnow = lambda: SUMMER
        State().mark_run("ping")              # 13:17 local, with offset
        s = State()
        receipts.overlay(s)
        self.assertEqual(s.concern_last_run["ping"], "2026-10-19T13:17:03")
        self.assertFalse(s.is_stale("ping", 60))


if __name__ == "__main__":
    unittest.main()
