#!/usr/bin/env python3
"""`preview --at` — the morning message of a given day in one command (mérés 11).

The agent asked "run the morning summary as if it were the gas bill's morning"
and spent ~7 rounds on --help / grep / sed to find tick --dry-run --now | deliver
--preview. Compatible with pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _cases_fixture import CasesCase  # noqa: E402


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns
            for p in sorted(root.rglob("*")) if p.is_file()}


class TestPreview(CasesCase):
    def preview(self, *args):
        from anytime_engine import preview
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = preview.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_a_day_prints_that_mornings_message_and_touches_nothing(self):
        before = snapshot(self.root)
        rc, out, err = self.preview("--at", "2026-09-10")
        self.assertEqual(rc, 0, err)
        self.assertIn("Gázszámla", out)
        self.assertEqual(snapshot(self.root), before, "preview must write nothing")
        self.assertFalse((self.root / "data" / "outbox").exists())

    def test_a_time_before_the_morning_says_nothing_is_planned(self):
        rc, out, _ = self.preview("--at", "2020-01-01T05:00")
        self.assertEqual(rc, 0)
        self.assertIn("nothing is planned", out)

    def test_bad_input_is_one_clear_line(self):
        rc, _, err = self.preview("--at", "nem-datum")
        self.assertEqual(rc, 1)
        self.assertTrue(err.startswith("preview: NOT done"))
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_the_module_entry_and_help_name_the_use(self):
        from anytime_engine import __main__ as m, preview
        self.assertIn("preview", m.COMMANDS)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            preview.main(["--help"])
        self.assertIn("preview --at 2026-11-10", " ".join(buf.getvalue().split()))


if __name__ == "__main__":
    unittest.main()
