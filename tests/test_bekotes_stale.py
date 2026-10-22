#!/usr/bin/env python3
"""bekotes pack — the deterministic stale marking, the citation rules it relies
on (undeclared source ignored, an [elavult] line skipped), robust git calls and
a corrupt cursor.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _bekotes_fixture import BekotesCase  # noqa: E402
from anytime_bekotes import cursor, diff, sources, stale  # noqa: E402


class TestStale(BekotesCase):

    def setUp(self):
        super().setUp()
        self.biz_dir = Path(self.biz["dir"])

    def test_mark_idempotent(self):
        f = self.biz_dir / "terkep.md"
        f.write_text("- Domain: zoldag.example (forrás: memoria:a.md)\n- Más (forrás: web:README.md)\n")
        self.assertEqual(stale.mark(self.biz_dir, ["memoria:a.md"], "2026-10-18"), 1)
        self.assertEqual(stale.mark(self.biz_dir, ["memoria:a.md"], "2026-10-19"), 0)
        text = f.read_text()
        self.assertIn("(forrás: memoria:a.md) [elavult 2026-10-18]", text)
        self.assertIn("- Más (forrás: web:README.md)\n", text)
        self.assertNotIn("2026-10-19", text)

    def test_mark_multi_ref_subdirs_and_memoria_skipped(self):
        (self.biz_dir / "al").mkdir()
        sub = self.biz_dir / "al" / "x.md"
        sub.write_text("Ár (forrás: linear:ZOL-1; web:regi.txt)\r\nNincs hivatkozás\r\n")
        mem = self.biz_dir / "memoria" / "b.md"
        mem.write_text("(forrás: web:regi.txt)\n")
        self.assertEqual(stale.mark(self.biz_dir, ["web:regi.txt"], "2026-10-18"), 1)
        self.assertEqual(sub.read_bytes().decode(),
                         "Ár (forrás: linear:ZOL-1; web:regi.txt) [elavult 2026-10-18]\r\n"
                         "Nincs hivatkozás\r\n")
        self.assertEqual(mem.read_text(), "(forrás: web:regi.txt)\n")

    def test_mark_nothing_leaves_file_untouched(self):
        f = self.biz_dir / "terkep.md"
        f.write_text("- (forrás: web:regi.txt)\n")
        before = f.stat().st_mtime_ns
        self.assertEqual(stale.mark(self.biz_dir, [], "2026-10-18"), 0)
        self.assertEqual(f.stat().st_mtime_ns, before)


class TestRefRules(BekotesCase):

    def test_undeclared_source_is_ignored(self):
        self.map_file("terkep.md", "- (forrás: ismeretlen:valami.md)\n- (forrás: web:regi.txt)\n")
        self.assertEqual(diff.unresolved_refs(self.biz, self.root), [])

    def test_stale_marked_line_is_not_reported_again(self):
        self.map_file("terkep.md", "- (forrás: web:nincs.txt) [elavult 2026-10-11]\n"
                                   "- (forrás: memoria:eltunt.md)\n")
        self.assertEqual(diff.unresolved_refs(self.biz, self.root), ["memoria:eltunt.md"])


class TestGitRobust(BekotesCase):

    def test_git_disables_signature_and_color(self):
        with mock.patch.object(subprocess, "run") as run:
            sources.git(Path("/x"), "log")
        argv = run.call_args.args[0]
        self.assertEqual(argv[:7], ["git", "-c", "log.showSignature=false",
                                    "-c", "color.ui=never", "-C", "/x"])
        self.assertEqual(run.call_args.kwargs.get("errors"), "replace")

    def test_git_output_with_invalid_utf8_does_not_crash(self):
        (self.root / "munka" / "web" / "bin.txt").write_bytes(b"ok \xff\xfe vege\n")
        self.commit("munka/web", "bin", files={})
        r = sources.git(self.root / "munka" / "web", "show", "HEAD:bin.txt")
        self.assertEqual(r.returncode, 0)
        self.assertIn("�", r.stdout)


class TestCorruptCursor(BekotesCase):

    def test_corrupt_cursor_is_a_clear_error(self):
        cursor.path(self.biz["dir"]).write_text("{ nem json")
        with self.assertRaises(cursor.CursorError) as e:
            cursor.load(self.biz["dir"])
        self.assertIn("frissit --baseline", str(e.exception))


if __name__ == "__main__":
    unittest.main()
