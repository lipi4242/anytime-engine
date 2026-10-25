#!/usr/bin/env python3
"""setup --expect: what every scheduled output must contain, stored with the schedule.

Failure class: a scheduled output that lacks what the job promised (a morning summary without
the people to call) went unchecked, because the check needed the agent to remember --expect.
The promise now lives in components.engine.delivery.expect; the brain's done-check and its
session-start check read it from there. Without one, setup asks for it.
Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
from test_setup import SetupCase  # noqa: E402


class TestSetupExpect(SetupCase):
    def test_the_promise_is_stored_and_kept_on_a_later_run(self):
        rc, out = self.run_setup("--tz", "Europe/Budapest", "--install", "--expect", "Hívd fel:", "--expect", "Határidő")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.engine()["delivery"]["expect"], ["Hívd fel:", "Határidő"])
        rc, out = self.run_setup("--tz", "Europe/Budapest", "--install", "--morning", "08:00")
        self.assertEqual(self.engine()["delivery"]["expect"], ["Hívd fel:", "Határidő"], "a re-run keeps it")

    def test_without_a_promise_setup_asks_for_it(self):
        rc, out = self.run_setup("--tz", "Europe/Budapest", "--install")
        self.assertEqual(rc, 0, out)
        self.assertIn("what must every output contain", out)
        self.assertIn("--expect", out)


if __name__ == "__main__":
    unittest.main()
