#!/usr/bin/env python3
"""setup --doctor: the installed timer units against what setup would generate now.

The measured gap (holdout, 0.3.0): the agent hand-edited the timer the installer manages; the
next `setup --install` would silently overwrite it, and nothing said the two had drifted.
The doctor writes nothing: each managed unit is OK, MISSING or HAND-EDITED (with the lines),
an environment-only difference is a note, and a unit setup does not manage is named.
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
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from test_setup import SetupCase  # noqa: E402


class Doctor(SetupCase):
    def setUp(self):
        super().setUp()
        rc, out = self.run_setup("--tz", "Europe/Budapest", "--install")
        assert rc == 0, out
        self.service = next(self.units.glob("*-hourly.service"))
        self.timer = next(self.units.glob("*-hourly.timer"))

    def doctor(self):
        return self.run_setup("--doctor")

    def test_fresh_units_are_ok_and_nothing_is_written(self):
        before = {p.name: p.read_text() for p in self.units.iterdir()}
        rc, out = self.doctor()
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count("OK "), 2, out)
        self.assertEqual({p.name: p.read_text() for p in self.units.iterdir()}, before)

    def test_a_hand_edit_is_named_with_its_line(self):
        self.timer.write_text(self.timer.read_text().replace("OnCalendar=hourly", "OnCalendar=*:0/15"))
        rc, out = self.doctor()
        self.assertEqual(rc, 1, out)
        self.assertIn("HAND-EDITED %s" % self.timer.name, out)
        self.assertIn("+ OnCalendar=*:0/15", out)
        self.assertIn("- OnCalendar=hourly", out)
        self.assertIn("setup --install", out)

    def test_a_missing_unit_and_an_unmanaged_one(self):
        self.service.unlink()
        (self.units / self.timer.name.replace("hourly", "every-5-min")).write_text("[Timer]\n")
        rc, out = self.doctor()
        self.assertEqual(rc, 1, out)
        self.assertIn("MISSING %s" % self.service.name, out)
        self.assertIn("NOT MANAGED", out)
        self.assertIn("every-5-min", out)

    def test_an_environment_only_difference_is_a_note(self):
        self.service.write_text(self.service.read_text().replace(
            "[Service]\n", '[Service]\nEnvironment="ANYTIME_TZ=Europe/Budapest"\n'))
        rc, out = self.doctor()
        self.assertEqual(rc, 0, out)
        self.assertIn("NOTE", out)
        self.assertIn("ANYTIME_TZ", out)


if __name__ == "__main__":
    unittest.main()
