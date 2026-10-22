#!/usr/bin/env python3
"""bekotes pack — business discovery, the ingest cursor and source snapshots.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import json
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
from anytime_bekotes import config, cursor, sources  # noqa: E402


class TestBusinesses(BekotesCase):

    def test_lists_business_with_dir(self):
        self.assertEqual(self.biz["business"], "zoldag")
        self.assertEqual(Path(self.biz["dir"]), self.root / "agy" / "business" / "zoldag")

    def test_no_brain_is_empty(self):
        (self.root / "mentat.json").write_text(json.dumps({"schema": 1, "components": {}}))
        self.assertEqual(config.businesses(self.root), [])
        (self.root / "mentat.json").unlink()
        self.assertEqual(config.businesses(self.root), [])


class TestCursor(BekotesCase):

    def test_missing_is_none(self):
        self.assertIsNone(cursor.load(self.biz["dir"]))

    def test_roundtrip(self):
        data = {"schema": 1, "sources": {"web": {"head": "abc"}}, "full_at": None,
                "advanced_at": "2026-10-18T08:00:00"}
        cursor.save(self.biz["dir"], data)
        self.assertEqual(cursor.load(self.biz["dir"]), data)
        self.assertTrue((Path(self.biz["dir"]) / "kurzor.json").is_file())

    def test_save_is_atomic(self):
        cursor.save(self.biz["dir"], {"schema": 1, "sources": {}})
        self.saved_before = cursor.load(self.biz["dir"])
        with mock.patch("os.replace", side_effect=OSError):
            with self.assertRaises(OSError):
                cursor.save(self.biz["dir"], {"schema": 1})
        self.assertEqual(cursor.load(self.biz["dir"]), self.saved_before)
        self.assertEqual([p.name for p in Path(self.biz["dir"]).glob("kurzor*")], ["kurzor.json"])


class TestSnapshot(BekotesCase):

    def src(self, name):
        return next(s for s in self.biz["sources"] if s["name"] == name)

    def test_repo_head(self):
        head = self.git("munka/web", "rev-parse", "HEAD").strip()
        self.assertEqual(sources.snapshot(self.src("web"), self.root), {"head": head})

    def test_memory_hashes(self):
        snap = sources.snapshot(self.src("memoria"), self.root)
        self.assertEqual(list(snap["hashes"]), ["a.md"])
        self.assertEqual(len(snap["hashes"]["a.md"]), 64)

    def test_linear_items(self):
        self.linear([("ZOL-1", "2026-10-10T10:00:00Z"), ("ZOL-2", "2026-10-12T10:00:00Z")])
        self.assertEqual(sources.snapshot(self.src("linear"), self.root),
                         {"items": {"ZOL-1": "2026-10-10T10:00:00Z",
                                    "ZOL-2": "2026-10-12T10:00:00Z"},
                          "max": "2026-10-12T10:00:00Z"})

    def test_live_sha(self):
        (self.root / "munka" / "elo.html").write_text("<p>élő</p>")
        snap = sources.snapshot({"name": "elo", "kind": "live", "path": "munka/elo.html"},
                                self.root)
        self.assertEqual(len(snap["sha256"]), 64)

    def test_unavailable_is_blocked(self):
        for src in (self.src("posta"), {"name": "x", "kind": "repo", "path": "nincs"},
                    {"name": "y", "kind": "linear", "export": "nincs.json"},
                    {"name": "z", "kind": "fax"}):
            self.assertEqual(sources.snapshot(src, self.root), {"state": "blokkolt"}, src)


if __name__ == "__main__":
    unittest.main()
