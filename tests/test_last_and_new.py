#!/usr/bin/env python3
"""`last` (what did the tick find?) and `anytime_cases.new` (one-command case).

2026-10-16 (10/04): the tick left no readable trace of what it read from the
brain, and the agent hand-rolled a ULID and read the template to add a case.
Compatible with pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _cases_fixture import CasesCase  # noqa: E402
from anytime_engine import config, lasttick, tick  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.state import State  # noqa: E402

T = datetime(2026, 10, 15, 8, 30)


def run(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(list(args))
    return rc, out.getvalue(), err.getvalue()


class TestLast(CasesCase):
    def test_a_real_tick_leaves_a_readable_summary(self):
        self.assertEqual(run(lasttick.main)[0], 1, "no tick yet")
        tick.run_tick("review", now=T)
        rc, out, _ = run(lasttick.main)
        self.assertEqual(rc, 0)
        self.assertIn("Planned: cases_morning", out)
        self.assertIn("overdue 2 [Gázszámla (2026-09-10)", out)
        self.assertIn("read 5 cases", out)
        self.assertIn("invalid 1 [agy/cases/rossz.md]", out)
        self.assertLess(len(out.splitlines()), 15)

    def test_skipped_concerns_say_why_and_a_dry_run_writes_nothing(self):
        tick.run_tick("hourly", dry_run=True, now=T)
        self.assertFalse(lasttick.path().exists())
        tick.run_tick("review", now=T)
        s = json.loads(lasttick.path().read_text())
        self.assertIn("cases_morning", [a["concern"] for a in s["planned"]])
        self.assertIsInstance(s["skipped"], dict)

    def test_json_flag_and_unwritable_record_never_fail_the_tick(self):
        plan = reduce("review", State(), now=T)
        lasttick.path().parent.mkdir(parents=True, exist_ok=True)
        lasttick.path().mkdir()   # a directory where the record goes: os.replace fails
        with contextlib.redirect_stderr(io.StringIO()):
            lasttick.write(plan)   # must not raise
        lasttick.path().rmdir()
        lasttick.write(plan)
        self.assertEqual(json.loads(run(lasttick.main, "--json")[1])["trigger"], "review")


class TestNew(CasesCase):
    def new(self, *args):
        from anytime_cases import new
        return run(new.main, *args)

    def test_writes_a_case_the_pack_reads(self):
        rc, out, err = self.new("Kémény ellenőrzés", "--due", "2026-10-20", "--next", "Időpontot kérni")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), "agy/cases/kemeny-ellenorzes.md")
        text = (self.root / out.strip()).read_text()
        self.assertRegex(text, r"case_id: [0-9A-HJKMNP-TV-Z]{26}\n")
        due = reduce("review", State(), now=T)["actions"][0]["context"]["cases.due"]
        self.assertIn("Kémény ellenőrzés", [o["title"] for k in ("today", "week") for o in due[k]])

    def test_refuses_overwrite_bad_date_and_series_without_anchor(self):
        self.assertEqual(self.new("A", "--due", "2026-10-20", "--slug", "x")[0], 0)
        self.assertEqual(self.new("A", "--due", "2026-10-20", "--slug", "x")[0], 2)
        self.assertEqual(self.new("B", "--due", "holnap")[0], 2)
        self.assertEqual(self.new("C", "--due", "2026-10-20", "--recurrence", "monthly:10")[0], 2)
        rc, out, _ = self.new("D", "--due", "2026-11-10", "--recurrence", "monthly:10",
                              "--anchor", "2026-11-10")
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
