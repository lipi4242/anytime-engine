#!/usr/bin/env python3
"""bekotes pack — diff since the cursor (repo, memory, linear) + weekly full.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _bekotes_fixture import BekotesCase  # noqa: E402
from anytime_bekotes import cursor, diff  # noqa: E402

T = datetime(2026, 10, 18, 8, 0)


class TestDiff(BekotesCase):

    def baseline(self):
        d = diff.compute(self.biz, self.root, T)
        cursor.save(self.biz["dir"], d["next"])
        return d

    def test_baseline_has_no_changes_and_writes_nothing(self):
        d = diff.compute(self.biz, self.root, T)
        self.assertTrue(d["baseline"])
        self.assertEqual((d["changes"], d["deleted"]), ([], []))
        self.assertIsNone(cursor.load(self.biz["dir"]))
        self.assertIn("head", d["next"]["sources"]["web"])

    def test_baseline_then_commit_memory_linear(self):
        self.baseline()
        self.commit("munka/web", "domain: zoldag-kert.example", rm="regi.txt")
        self.mem("uj.md", "új tény"); self.mem("a.md", None)
        self.linear([("ZOL-1", "2026-10-10T10:00:00Z"), ("ZOL-2", "2026-10-18T06:00:00Z")])
        d = diff.compute(self.biz, self.root, T)
        self.assertFalse(d["baseline"]); self.assertFalse(d["empty"])
        kinds = sorted({(c["source"], c["kind"]) for c in d["changes"]})
        self.assertEqual(kinds, [("linear", "issue"), ("memoria", "memory"),
                                 ("web", "commit"), ("web", "file")])
        commit = next(c for c in d["changes"] if c["kind"] == "commit")
        self.assertEqual(commit["subject"], "domain: zoldag-kert.example")
        self.assertIn("memoria:a.md", d["deleted"]); self.assertIn("web:regi.txt", d["deleted"])
        self.assertEqual([c["identifier"] for c in d["changes"] if c["kind"] == "issue"], ["ZOL-2"])

    def test_nothing_new_is_empty(self):
        self.baseline()
        d = diff.compute(self.biz, self.root, T)
        self.assertTrue(d["empty"])
        self.assertEqual(d["next"]["sources"], cursor.load(self.biz["dir"])["sources"])

    def test_overlap_dedupes_seen_items(self):
        self.baseline()
        self.linear([("ZOL-1", "2026-10-10T10:00:00Z"), ("ZOL-5", "2026-10-01T09:00:00Z")])
        d = diff.compute(self.biz, self.root, T)
        self.assertEqual([c["identifier"] for c in d["changes"]], ["ZOL-5"])

    def test_incomplete_export_never_deletes(self):
        self.baseline()
        self.linear([("ZOL-3", "2026-10-17T09:00:00Z")], complete=False)
        d = diff.compute(self.biz, self.root, T)
        self.assertEqual(d["deleted"], [])
        self.assertIn("ZOL-1", d["next"]["sources"]["linear"]["items"])
        self.linear([("ZOL-3", "2026-10-17T09:00:00Z")], complete=True)
        self.assertEqual(diff.compute(self.biz, self.root, T)["deleted"], ["linear:ZOL-1"])

    def test_weekly_full_resolves_citations(self):
        self.map_file("terkep.md", "Domain (forrás: web:regi.txt), oldal (forrás: web:nincs.md),"
                                   " tény (forrás: memoria:a.md), (forrás: linear:ZOL-1)\n")
        self.baseline()
        stamp = {"at": (T - timedelta(days=8)).isoformat(), "ok": True, "unresolved": []}
        d = diff.compute(self.biz, self.root, T, weekly=stamp)
        self.assertEqual(d["deleted"], ["web:nincs.md"])
        self.assertEqual(d["weekly"], {"at": T.isoformat(), "ok": False, "unresolved": ["web:nincs.md"]})
        self.assertEqual(diff.unresolved_refs(self.biz, self.root), ["web:nincs.md"])
        stamp["at"] = (T - timedelta(days=2)).isoformat()
        d = diff.compute(self.biz, self.root, T, weekly=stamp)
        self.assertEqual((d["deleted"], d["weekly"]), ([], None))

    def test_no_stamp_triggers_full(self):
        self.map_file("terkep.md", "x (forrás: linear:ZOL-9)\n")
        self.baseline()
        self.assertEqual(diff.compute(self.biz, self.root, T)["deleted"], ["linear:ZOL-9"])

    def test_rename_and_recreate_use_end_state(self):
        self.commit("munka/web", "a", files={"a.txt": "a\n", "b.txt": "bé tartalom\n" * 5})
        self.baseline()
        self.commit("munka/web", "törlés", rm="a.txt", files={})
        self.commit("munka/web", "vissza", files={"a.txt": "a\n"})
        self.commit("munka/web", "átnevezés", files={}, mv=("b.txt", "c.txt"))
        d = diff.compute(self.biz, self.root, T)
        self.assertEqual(d["deleted"], ["web:b.txt"])
        files = sorted((c["status"], c["path"]) for c in d["changes"] if c["kind"] == "file")
        self.assertEqual(files, [("A", "c.txt"), ("D", "b.txt")])
        self.assertEqual(len([c for c in d["changes"] if c["kind"] == "commit"]), 3)

    def test_unknown_old_head_is_resync(self):
        self.baseline()
        cur = cursor.load(self.biz["dir"])
        cur["sources"]["web"] = {"head": "0" * 40}
        cursor.save(self.biz["dir"], cur)
        d = diff.compute(self.biz, self.root, T)
        self.assertEqual([c["kind"] for c in d["changes"]], ["resync"])

    def test_unreachable_source_is_error_and_keeps_cursor(self):
        self.baseline()
        old = cursor.load(self.biz["dir"])["sources"]["linear"]
        (self.root / "munka" / "linear.json").unlink()
        d = diff.compute(self.biz, self.root, T)
        self.assertEqual([(c["source"], c["kind"]) for c in d["changes"]], [("linear", "error")])
        self.assertEqual(d["next"]["sources"]["linear"], old)


if __name__ == "__main__":
    unittest.main()
