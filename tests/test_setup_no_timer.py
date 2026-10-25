#!/usr/bin/env python3
"""setup --install --no-timer: the settings without a timer (friction #7).

"No timer, it will run on a server": `setup` wrote mentat.json only with --install, and
--install also installs the timer, so the agent copied the dry run's values by hand.
Compatible with pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_setup import SetupCase  # noqa: E402


class TestNoTimer(SetupCase):
    def test_records_the_settings_and_installs_no_timer(self):
        rc, out = self.run_setup("--tz", "Europe/Budapest", "--morning", "06:30", "--lang", "hu",
                                 "--install", "--no-timer")
        self.assertEqual(rc, 0, out)
        eng = self.engine()
        self.assertEqual((eng.get("timezone"), eng.get("morning")), ("Europe/Budapest", "06:30"), eng)
        self.assertFalse(self.units.exists(), "no unit files")
        self.assertIn("--no-timer", out)
        self.assertIn("AGENTS.md", out)


if __name__ == "__main__":
    unittest.main()
