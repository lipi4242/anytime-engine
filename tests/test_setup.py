#!/usr/bin/env python3
"""setup — the whole install after the vendoring, as one command.

The acceptance run (2026-10-15, 04) cost $3.6 / 1.7M cache-read tokens: the
agent read the README, wrote its own concern and executor, found the schedule
by trial, and the timezone was never asked. `python3 -m anytime_engine.setup`
records timezone + morning + delivery channel + executor in mentat.json, runs
the selftest, and installs the timer — a dry run unless --install.
Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _cases_fixture import CasesCase  # noqa: E402
from anytime_engine import setup, status  # noqa: E402


class SetupCase(CasesCase):
    def run_setup(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        args = list(argv) + ["--no-selftest", "--no-enable", "--unit-dir", str(self.units)]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = setup.main(args)
        return rc, out.getvalue() + err.getvalue()

    def setUp(self):
        super().setUp()
        self.units = self.root / "units"

    def engine(self):
        return json.loads((self.root / "mentat.json").read_text())["components"]["engine"]


class TestSetup(SetupCase):
    def test_default_is_a_dry_run(self):
        before = (self.root / "mentat.json").read_text()
        rc, out = self.run_setup("--tz", "Europe/Budapest")
        self.assertEqual(rc, 0, out)
        self.assertIn("Europe/Budapest", out)
        self.assertEqual((self.root / "mentat.json").read_text(), before)
        self.assertFalse(self.units.exists())

    def test_install_records_the_choices_and_the_timer(self):
        rc, out = self.run_setup("--tz", "Europe/Budapest", "--morning", "07:00",
                                 "--lang", "hu", "--install")
        self.assertEqual(rc, 0, out)
        eng = self.engine()
        self.assertEqual(eng["timezone"], "Europe/Budapest")
        self.assertEqual(eng["morning"], "07:00")
        self.assertEqual(eng["delivery"], {"channel": "file", "lang": "hu"})
        self.assertEqual(eng["exec"], "python3 -m anytime_cases.deliver")
        # the unit runs the plain tick; the tick takes the executor from mentat.json,
        # so the engine's timer and the fleet's run the same thing
        service = next(self.units.glob("*-hourly.service")).read_text()
        self.assertIn('"anytime_engine.tick" "hourly"\n', service)

    def test_output_is_short_by_default_and_full_with_verbose(self):
        """mérés 04: setup printed 10 127 characters (both unit files, the plan) unclipped."""
        for extra in ((), ("--install",)):
            rc, out = self.run_setup("--tz", "Europe/Budapest", "--lang", "hu", *extra)
            self.assertEqual(rc, 0, out)
            self.assertLessEqual(len(out.strip().splitlines()), 15, out)
            self.assertLess(len(out), 1800)
            self.assertNotIn("[Service]", out)
            self.assertIn("Europe/Budapest", out)
            self.assertIn("anytime_engine preview --at", out)   # the next step
        self.assertIn("-hourly.timer", out)
        rc, full = self.run_setup("--tz", "Europe/Budapest", "--verbose")
        self.assertIn("[Service]", full)
        self.assertGreater(len(full), len(out))

    def test_a_refusal_inside_the_schedule_step_is_shown_whole(self):
        doc = json.loads((self.root / "mentat.json").read_text())
        doc["components"]["engine"]["plugins"] = []
        (self.root / "mentat.json").write_text(json.dumps(doc))
        rc, out = self.run_setup("--tz", "UTC", "--install")
        self.assertEqual(rc, 2)
        self.assertIn("components.engine.plugins is empty", out)

    def test_quiet_hours_are_recorded_and_can_be_switched_off(self):
        self.run_setup("--tz", "UTC", "--install")
        self.assertEqual(self.engine()["quiet_hours"], "22:00-07:00")
        self.run_setup("--tz", "UTC", "--quiet-hours", "off", "--install")
        self.assertEqual(self.engine()["quiet_hours"], "off")
        rc, out = self.run_setup("--tz", "UTC", "--quiet-hours", "late", "--install")
        self.assertEqual(rc, 2)

    def test_unknown_timezone_writes_nothing(self):
        before = (self.root / "mentat.json").read_text()
        rc, out = self.run_setup("--tz", "Mars/Olympus", "--install")
        self.assertEqual(rc, 2)
        self.assertEqual((self.root / "mentat.json").read_text(), before)

    def test_telegram_needs_its_keys_first(self):
        rc, out = self.run_setup("--tz", "UTC", "--deliver", "telegram", "--install")
        self.assertEqual(rc, 2)
        self.assertIn("TELEGRAM_BOT_TOKEN", out)
        self.assertNotIn("delivery", self.engine())

    def test_telegram_without_node_says_so_but_file_does_not_care(self):
        real_keys, real_which = setup._missing_telegram_keys, setup.shutil.which
        setup._missing_telegram_keys, setup.shutil.which = (lambda: []), (lambda _n: None)
        try:
            rc, out = self.run_setup("--tz", "UTC", "--deliver", "telegram", "--install")
            self.assertEqual(rc, 2)
            self.assertIn("Node.js", out)
            self.assertNotIn("delivery", self.engine())
            rc, out = self.run_setup("--tz", "UTC", "--install")
            self.assertEqual(rc, 0, out)
        finally:
            setup._missing_telegram_keys, setup.shutil.which = real_keys, real_which

    def test_fleet_owned_schedule_records_but_installs_no_timer(self):
        doc = json.loads((self.root / "mentat.json").read_text())
        doc["components"]["engine"]["schedule_owner"] = "fleet"
        (self.root / "mentat.json").write_text(json.dumps(doc))
        rc, out = self.run_setup("--tz", "Europe/Budapest", "--install")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.engine()["exec"], "python3 -m anytime_cases.deliver")
        self.assertFalse(self.units.exists())
        self.assertIn("fleet", out)


class TestConcernContract(SetupCase):
    def test_status_lists_which_concerns_read_the_cases(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(status.main(["--concerns"]), 0)
        rows = {c["name"]: c for c in json.loads(out.getvalue())["concerns"]}
        self.assertTrue(rows["cases_morning"]["reads_cases"])
        self.assertEqual(rows["cases_morning"]["pack"], "anytime_cases")
        self.assertIn("hourly", rows["cases_morning"]["triggers"])


if __name__ == "__main__":
    unittest.main()
