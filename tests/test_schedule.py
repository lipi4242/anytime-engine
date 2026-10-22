#!/usr/bin/env python3
"""schedule — the durable-schedule recipe (systemd user timer / cron line).

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _engine_isolation import IsolatedTestCase  # noqa: E402
from anytime_engine import schedule  # noqa: E402


def _run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = schedule.main(argv)
    return rc, out.getvalue()


class TestSchedule(IsolatedTestCase):
    def test_default_is_a_dry_run_that_writes_nothing(self):
        unit_dir = self.root / "units"
        rc, out = _run(["--plugins", "a.concerns", "--name", "bot",
                        "--unit-dir", str(unit_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse(unit_dir.exists())
        self.assertIn("OnCalendar=hourly", out)
        self.assertIn("Persistent=true", out)
        self.assertIn("anytime_engine.tick", out)
        self.assertIn("enable --now anytime-bot-hourly.timer", out)

    def test_service_carries_root_plugins_and_review_config(self):
        os.environ["ANYTIME_REVIEW_TIMES"] = "07:00"
        units = schedule.render_systemd("bot", "hourly", "hourly", "a.concerns",
                                        exec_cmd='run "$PLAN" 100%')
        svc = units["anytime-bot-hourly.service"]
        self.assertIn(f"WorkingDirectory={self.root.resolve()}", svc)
        self.assertIn('Environment="ANYTIME_PLUGINS=a.concerns"', svc)
        self.assertIn('Environment="ANYTIME_REVIEW_TIMES=07:00"', svc)
        self.assertIn('"run \\"$$PLAN\\" 100%%"', svc)   # systemd-escaped

    def test_install_without_enable_writes_both_units(self):
        unit_dir = self.root / "units"
        rc, _ = _run(["--plugins", "a.concerns", "--name", "bot", "--install",
                      "--no-enable", "--unit-dir", str(unit_dir)])
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(p.name for p in unit_dir.iterdir()),
                         ["anytime-bot-hourly.service", "anytime-bot-hourly.timer"])

    def test_cron_line_is_locked_and_logged(self):
        rc, out = _run(["--plugins", "a.concerns", "--cron"])
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("0 * * * * cd "))
        self.assertIn("flock -n", out)
        self.assertIn("ANYTIME_PLUGINS=a.concerns", out)
        self.assertIn("anytime-tick.log", out)


if __name__ == "__main__":
    unittest.main()
