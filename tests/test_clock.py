#!/usr/bin/env python3
"""clock — the agent's local time, and `tick --now` in it.

The measured bug (acceptance run 2026-10-15, section 10): the box ran on UTC,
so a "morning after 07:00" concern would have fired at 09:00 Budapest time.
The engine now reads the agent's timezone (mentat.json
components.engine.timezone, or ANYTIME_TZ) and every engine time — the
reducer's clock, `state.now()`, `--now` — is wall time in that zone.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
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
from anytime_engine import clock, tick  # noqa: E402
from anytime_engine.assembler import clear_providers  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.registry import Concern, clear, register  # noqa: E402
from anytime_engine.state import State  # noqa: E402

# 05:00 UTC on 2026-10-16 = 07:00 in Budapest (CEST, UTC+2)
UTC_5 = datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc)


class ClockCase(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self._real = clock._utcnow
        clock._utcnow = lambda: UTC_5

    def tearDown(self):
        clock._utcnow = self._real
        super().tearDown()

    def manifest(self, engine: dict):
        (self.root / "mentat.json").write_text(json.dumps(
            {"schema": 1, "components": {"engine": engine}}))


class TestClock(ClockCase):
    def test_timezone_from_mentat_json(self):
        self.manifest({"timezone": "Europe/Budapest"})
        self.assertEqual(clock.now(), datetime(2026, 10, 16, 7, 0))

    def test_env_wins_over_the_manifest(self):
        self.manifest({"timezone": "Europe/Budapest"})
        os.environ["ANYTIME_TZ"] = "UTC"
        self.assertEqual(clock.now(), datetime(2026, 10, 16, 5, 0))

    def test_unknown_timezone_is_an_error_not_a_guess(self):
        self.manifest({"timezone": "Europe/Atlantis"})
        with self.assertRaises(clock.ClockError):
            clock.now()

    def test_reducer_and_state_read_the_agent_clock(self):
        self.manifest({"timezone": "Europe/Budapest"})
        self.assertEqual(State().now(), datetime(2026, 10, 16, 7, 0))
        self.assertEqual(reduce("hourly", State())["timestamp"], "2026-10-16T07:00:00")

    def test_parse_reads_naive_times_as_agent_local(self):
        self.manifest({"timezone": "Europe/Budapest"})
        self.assertEqual(clock.parse("2026-12-10T08:00"), datetime(2026, 12, 10, 8, 0))
        # an explicit offset is converted into the agent's zone (CET in December)
        self.assertEqual(clock.parse("2026-12-10T07:00+00:00"), datetime(2026, 12, 10, 8, 0))
        self.assertEqual(clock.parse("now"), datetime(2026, 10, 16, 7, 0))


class TestTickNow(ClockCase):
    def setUp(self):
        super().setUp()
        clear()
        clear_providers()
        register(Concern(name="ping", description="d", triggers=["hourly"],
                         should_run=lambda s: True, action="ping"))
        self.manifest({"timezone": "Europe/Budapest"})

    def tearDown(self):
        clear()
        clear_providers()
        super().tearDown()

    def run_tick(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = tick.main(argv + ["--no-discover"])
            except SystemExit as e:   # argparse refusal
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def test_dry_run_now_is_local_time(self):
        rc, out, _ = self.run_tick(["hourly", "--dry-run", "--now", "2026-12-10T08:00"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["timestamp"], "2026-12-10T08:00:00")

    def test_bare_now_runs_a_real_tick_right_now(self):
        rc, out, _ = self.run_tick(["hourly", "--now"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["timestamp"], "2026-10-16T07:00:00")
        self.assertTrue((self.root / "data" / "state" / "last-tick.json").exists())

    def test_last_tick_stamp_is_agent_local_not_the_boxes_utc(self):
        # 05:00 UTC; the box clock (UTC) would stamp 05:00:00, Budapest says 07:00,
        # and the offset says so: the agent reading it cannot take it for UTC
        self.run_tick(["hourly", "--now"])
        stamp = json.loads((self.root / "data" / "state" / "last-tick.json").read_text())
        self.assertEqual(stamp["at"], "2026-10-16T07:00:00+02:00")

    def test_a_made_up_time_never_runs_for_real(self):
        rc, _, err = self.run_tick(["hourly", "--now", "2026-12-10T08:00"])
        self.assertEqual(rc, 2)
        self.assertIn("--dry-run", err)
        self.assertFalse((self.root / "data" / "state" / "last-tick.json").exists())


if __name__ == "__main__":
    unittest.main()
