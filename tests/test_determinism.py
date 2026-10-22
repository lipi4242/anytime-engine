#!/usr/bin/env python3
"""The reducer is a function of (trigger, state, now).

Before: reduce() and State read datetime.now() themselves, so the same input
gave a different plan a minute later, and the reducer special-cased a concern
NAMED `review_email` (a legacy special case). Now `now` is injected (reduce(..., now=)),
every State time read inside the reduction uses it, and review_type reaches a
concern through the ordinary `context_needs` mechanism (a built-in provider).

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _engine_isolation import IsolatedTestCase  # noqa: E402
from anytime_engine.assembler import clear_providers, register_provider  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.registry import Concern, clear, register, validate  # noqa: E402
from anytime_engine.state import State  # noqa: E402

STATE = {"schema_version": 1, "concern_last_run": {"hourly_sync": "2026-10-15T08:00:00"}}
T1 = datetime(2026, 10, 15, 8, 30)
T2 = datetime(2026, 10, 15, 9, 30)


class TestDeterminism(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        os.environ["ANYTIME_REVIEW_WINDOWS"] = "morning:08:00,evening:18:00"
        clear()
        clear_providers()
        # A consumer-style should_run: calls is_stale WITHOUT passing a time.
        register(Concern(name="hourly_sync", description="sync", triggers=["hourly"],
                         should_run=lambda s: s.is_stale("hourly_sync", 60),
                         action="sync", context_needs=["clock"]))
        register_provider("clock", lambda s: s.now().isoformat())

    def tearDown(self):
        clear()
        clear_providers()
        super().tearDown()

    def _plan(self, now):
        return json.dumps(reduce("hourly", State(json.loads(json.dumps(STATE))), now=now),
                          sort_keys=True, default=str)

    def test_same_input_same_plan(self):
        self.assertEqual(self._plan(T2), self._plan(T2))

    def test_now_drives_staleness_inside_should_run(self):
        self.assertEqual(json.loads(self._plan(T1))["actions"], [])
        actions = json.loads(self._plan(T2))["actions"]
        self.assertEqual([a["concern"] for a in actions], ["hourly_sync"])
        self.assertEqual(actions[0]["context"]["clock"], T2.isoformat())

    def test_summary_uses_the_injected_time(self):
        plan = json.loads(self._plan(T1))
        self.assertEqual(plan["timestamp"], T1.isoformat())
        self.assertEqual(plan["state_summary"]["review_type"], "morning")
        self.assertTrue(plan["state_summary"]["review_due"])
        self.assertEqual(json.loads(self._plan(datetime(2026, 10, 15, 19)))
                         ["state_summary"]["review_type"], "evening")


class TestTickNow(TestDeterminism):
    def test_dry_run_reproduces_a_plan_at_a_given_time(self):
        import contextlib, io
        from anytime_engine import tick
        State(json.loads(json.dumps(STATE))).save()
        outs = []
        for _ in range(2):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = tick.main(["hourly", "--no-discover", "--dry-run", "--now", T2.isoformat()])
            self.assertEqual(rc, 0)
            outs.append(buf.getvalue())
        self.assertEqual(outs[0], outs[1])
        self.assertIn('"hourly_sync"', outs[0])

    def test_now_is_refused_on_a_real_tick(self):
        import contextlib, io
        from anytime_engine import tick
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            tick.main(["hourly", "--no-discover", "--now", T2.isoformat()])


class TestNoConcernNamedSpecially(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        os.environ["ANYTIME_REVIEW_WINDOWS"] = "morning:08:00,evening:18:00"
        clear()
        clear_providers()

    def tearDown(self):
        clear()
        super().tearDown()

    def _ctx(self, concern):
        register(concern)
        self.assertEqual(validate(), [])
        return reduce("review", State(), now=T2)["actions"][0]["context"]

    def test_the_name_review_email_gets_nothing_extra(self):
        ctx = self._ctx(Concern(name="review_email", description="", triggers=["review"],
                                should_run=lambda s: True))
        self.assertNotIn("review_type", ctx)

    def test_any_concern_can_ask_for_review_type(self):
        ctx = self._ctx(Concern(name="digest", description="", triggers=["review"],
                                should_run=lambda s: True, context_needs=["review_type"]))
        self.assertEqual(ctx["review_type"], "morning")


if __name__ == "__main__":
    unittest.main()
