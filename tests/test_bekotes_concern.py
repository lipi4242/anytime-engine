#!/usr/bin/env python3
"""bekotes pack — the daily `bekotes_frissites` concern and the `frissit` CLI,
through the real reducer (the pack loaded as an agent would load it).

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

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

from _bekotes_concern_fixture import DAY, HOUR, T, ConcernCase, action  # noqa: E402
from anytime_engine import tick  # noqa: E402
from anytime_engine.registry import validate  # noqa: E402


class TestConcern(ConcernCase):

    def test_pack_validates(self):
        self.assertEqual(validate(), [])

    def test_no_change_no_action_change_plans_advance_stops(self):
        self.assertIsNone(action(self.plan("hourly", T), "bekotes_frissites"))   # no cursor
        self.assertEqual(self.cli("--baseline")[0], 0)
        before = self.kurzor.stat().st_mtime_ns
        self.assertIsNone(action(self.plan("hourly", T + DAY), "bekotes_frissites"))
        tick.run_tick("hourly", dry_run=True, now=T + DAY)
        self.assertEqual(self.kurzor.stat().st_mtime_ns, before)
        self.commit("munka/web", "domain váltás")
        a = action(self.plan("hourly", T + 2 * DAY), "bekotes_frissites")
        self.assertEqual(a["context"]["bekotes.diff"],
                         {"businesses": [{"business": "zoldag", "changes": {"web": 2}, "deleted": 0}]})
        self.assertEqual(self.kurzor.stat().st_mtime_ns, before)
        self.now = T + 2 * DAY
        run_id = self.begin()
        self.assertIn("domain váltás", self.last_begin)
        self.assertEqual(self.cli("--advance", "rossz")[0], 1)
        self.assertEqual(self.kurzor.stat().st_mtime_ns, before)
        self.assertEqual(self.cli("--advance", run_id)[0], 0)
        self.assertIsNone(action(self.plan("hourly", T + 2 * DAY + HOUR), "bekotes_frissites"))
        self.assertFalse((self.kurzor.parent / ".pending-kurzor.json").exists())
        self.assertIn(".pending-kurzor.json", (self.kurzor.parent / ".gitignore").read_text())

    def test_interrupted_run_replans_next_day_with_same_changes(self):
        self.cli("--baseline")
        self.commit("munka/web", "domain váltás")
        self.mem("a.md", None)
        self.map_file("terkep.md", "- Domain (forrás: memoria:a.md)\n")
        self.now = T + DAY
        pending = self.kurzor.parent / ".pending-kurzor.json"
        first_id = self.begin()
        first = json.loads(pending.read_text())
        self.assertEqual(first["run_id"], first_id)
        self.assertIn("domain váltás", self.last_begin)
        self.assertEqual(first["deleted"], ["memoria:a.md"])
        self.assertIn("[elavult 2026-10-16]", (self.kurzor.parent / "terkep.md").read_text())
        self.assertIsNone(action(self.plan("hourly", T + DAY + HOUR), "bekotes_frissites"))  # fresh pending
        self.assertEqual(self.cli("--begin", when=T + DAY + HOUR)[0], 1)
        self.assertIsNotNone(action(self.plan("hourly", T + 2 * DAY), "bekotes_frissites"))
        self.now = T + 2 * DAY
        self.assertNotEqual(self.begin(), first_id)
        again = json.loads(pending.read_text())
        self.assertEqual((again["changes"], again["deleted"]), (first["changes"], first["deleted"]))
        self.assertIn("domain váltás", self.last_begin)
        self.assertNotIn("2026-10-17", (self.kurzor.parent / "terkep.md").read_text())

    def test_morning_gate_and_review(self):
        self.cli("--baseline")
        self.commit("munka/web", "új oldal")
        early = (T + DAY).replace(hour=6, minute=30)
        self.assertIsNone(action(self.plan("hourly", early), "bekotes_frissites"))
        self.assertIsNotNone(action(self.plan("review", early), "bekotes_frissites"))

    def test_advance_refuses_unresolvable_citation(self):
        self.cli("--baseline")
        self.commit("munka/web", "új oldal")
        self.now = T + DAY
        run_id = self.begin()
        self.map_file("terkep.md", "- Új (forrás: web:nincs-ilyen.txt)\n")
        before = self.kurzor.read_text()
        rc, out = self.cli("--advance", run_id)
        self.assertEqual(rc, 1)
        self.assertIn("web:nincs-ilyen.txt", out)
        self.assertEqual(self.kurzor.read_text(), before)

    def test_advance_without_pending_exits_1(self):
        self.cli("--baseline")
        self.assertEqual(self.cli("--advance", "barmi")[0], 1)

    def test_error_only_diff_is_empty_and_status_shows_it(self):
        self.cli("--baseline")
        (self.root / "munka" / "linear.json").unlink()
        self.assertIsNone(action(self.plan("review", T + DAY), "bekotes_frissites"))
        rc, out = self.cli("--status", when=T + DAY)
        self.assertEqual(rc, 0)
        self.assertIn("linear", out)
        self.assertIn("HIBA", out)

    def test_corrupt_cursor_no_crash(self):
        self.kurzor.write_text("{ nem json")
        self.assertIsNone(action(self.plan("review", T), "bekotes_frissites"))
        rc, out = self.cli("--status")
        self.assertIn("hibás", out)
        self.assertEqual(self.cli("--begin")[0], 1)

    def test_status_without_cursor(self):
        rc, out = self.cli("--status")
        self.assertEqual(rc, 0)
        self.assertIn("futtasd: frissit --baseline", out)


if __name__ == "__main__":
    unittest.main()
