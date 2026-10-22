#!/usr/bin/env python3
"""bekotes pack — regression tests from the final review: a partial Linear
export, a failed advance, malformed config / cursor / export, ref
normalisation, undecodable map files, an empty --begin, atomic marking.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from datetime import timezone
from pathlib import Path
from unittest import mock

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _bekotes_concern_fixture import DAY, HOUR, T, ConcernCase, action  # noqa: E402

PLAN = "bekotes_frissites"


class TestPartialLinear(ConcernCase):

    def setUp(self):
        super().setUp()
        self.map_file("terkep.md", "- Jegy (forrás: linear:ZOL-1)\n")
        self.cli("--baseline")
        self.linear([("ZOL-2", "2026-10-18T06:00:00Z")], complete=False)

    def test_weekly_full_keeps_ref_of_partial_export(self):
        self.begin(when=T + 8 * DAY)
        self.assertNotIn("elavult", (self.kurzor.parent / "terkep.md").read_text())

    def test_partial_export_does_not_block_advance(self):
        run_id = self.begin(when=T + DAY)
        rc, out = self.cli("--advance", run_id, when=T + DAY)
        self.assertEqual(rc, 0, out)


class TestFailedAdvance(ConcernCase):

    def test_no_replan_same_day_but_next_day(self):
        self.cli("--baseline")
        self.commit("munka/web", "új oldal")
        run_id = self.begin(when=T + DAY)
        self.map_file("terkep.md", "- Új (forrás: web:nincs.txt)\n")
        self.assertEqual(self.cli("--advance", run_id, when=T + DAY)[0], 1)
        planned = [h for h in range(1, 12) if action(self.plan("hourly", T + DAY + h * HOUR), PLAN)]
        self.assertEqual(planned, [])
        self.assertIsNotNone(action(self.plan("hourly", T + 2 * DAY), PLAN))


class TestMalformed(ConcernCase):

    def bekotes(self, srcs):
        (self.kurzor.parent / "bekotes.json").write_text(
            json.dumps({"schema": 1, "business": "zoldag", "sources": srcs}))

    def survives(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(action(self.plan("hourly", T + DAY), PLAN))
            self.assertEqual(self.cli("--status", when=T + DAY)[0] in (0, 1), True)
            self.cli("--begin", when=T + DAY)

    def test_source_without_name_or_as_string(self):
        self.cli("--baseline")
        for srcs in ([{"kind": "repo", "path": "munka/web"}], ["web"], "web"):
            self.bekotes(srcs)
            self.survives()

    def test_cursor_entry_not_a_dict(self):
        self.cli("--baseline")
        d = json.loads(self.kurzor.read_text())
        d["sources"]["web"] = "x"
        self.kurzor.write_text(json.dumps(d))
        self.survives()

    def test_linear_odd_identifiers_and_updated_types(self):
        self.cli("--baseline")
        for issues in ([{"identifier": ["x"], "updatedAt": "a"}],
                       [{"identifier": "A", "updatedAt": 5}, {"identifier": "B", "updatedAt": "x"}]):
            (self.root / "munka" / "linear.json").write_text(
                json.dumps({"complete": True, "issues": issues}))
            with contextlib.redirect_stderr(io.StringIO()):
                self.plan("hourly", T + DAY)
                self.assertEqual(self.cli("--status", when=T + DAY)[0], 0)

    def test_absolute_brain_root(self):
        (self.root / "mentat.json").write_text(json.dumps({"schema": 1, "components": {
            "brain": {"root": "/etc"}, "engine": {"plugins": ["anytime_bekotes"]}}}))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(action(self.plan("hourly", T + DAY), PLAN))

    def test_aware_and_naive_pending_times(self):
        from anytime_bekotes import pending
        self.assertTrue(pending.fresh({"started_at": "2026-10-15T08:00:00+00:00"},
                                      T.replace(tzinfo=timezone.utc)))


class TestRefsAndBegin(ConcernCase):

    def test_spaced_and_dot_slash_refs_are_normalised(self):
        from anytime_bekotes import refs
        self.assertEqual(refs.line_refs("(forrás: web: ./regi.txt ; linear : ZOL-1)"),
                         ["web:regi.txt", "linear:ZOL-1"])
        self.map_file("terkep.md", "- Régi (forrás: web: regi.txt)\n")
        self.cli("--baseline")
        self.commit("munka/web", "törlés", rm="regi.txt")
        run_id = self.begin(when=T + DAY)
        self.assertIn("[elavult", (self.kurzor.parent / "terkep.md").read_text())
        self.assertEqual(self.cli("--advance", run_id, when=T + DAY)[0], 0)

    def test_undecodable_map_file_is_skipped(self):
        from anytime_bekotes import diff
        (self.kurzor.parent / "rossz.md").write_bytes("(forrás: web:nincs2.txt) ".encode() + b"\xff\n")
        self.map_file("terkep.md", "- (forrás: web:nincs.txt)\n")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(diff.unresolved_refs(self.biz, self.root), ["web:nincs.txt"])

    def test_begin_with_nothing_to_do(self):
        self.cli("--baseline")
        rc, out = self.cli("--begin", when=T + DAY)
        self.assertEqual(rc, 1)
        self.assertNotIn("run_id", out)
        self.assertIn("nincs teendő — ne léptess", out)

    def test_stale_rewrite_is_atomic(self):
        from anytime_bekotes import stale
        f = self.kurzor.parent / "terkep.md"
        f.write_text("- (forrás: web:regi.txt)\n")
        with mock.patch.object(os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                stale.mark(f.parent, ["web:regi.txt"], "2026-10-18")
        self.assertEqual(f.read_text(), "- (forrás: web:regi.txt)\n")
        self.assertEqual([p.name for p in f.parent.iterdir() if p.name.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
