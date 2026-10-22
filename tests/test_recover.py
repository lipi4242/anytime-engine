#!/usr/bin/env python3
"""recover — the operator's way out of a fail-closed state.

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

from _engine_isolation import IsolatedTestCase  # noqa: E402
from anytime_engine import config, recover  # noqa: E402
from anytime_engine.state import State, StateUnavailable  # noqa: E402


def _run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc = recover.main(argv)
    return rc, out.getvalue()


class TestRecover(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.path = config.state_path()
        self.path.parent.mkdir(parents=True)

    def test_reset_unblocks_and_keeps_receipts(self):
        State().mark_run("send_digest")
        self.path.write_text("{broken")
        with self.assertRaises(StateUnavailable):
            with contextlib.redirect_stderr(io.StringIO()):
                State.load()
        rc, out = _run(["reset", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("1 receipt(s)", out)
        self.assertFalse(State.load().is_stale("send_digest", 24 * 60))
        self.assertTrue(any(".bak." in p.name for p in self.path.parent.iterdir()))

    def test_restore_picks_the_named_backup(self):
        self.path.write_text("{broken")
        prev2 = self.path.with_suffix(".json.prev.2")
        prev2.write_text(json.dumps({"schema_version": 1, "cache": {"k": 2}}))
        rc, _ = _run(["restore", "2"])
        self.assertEqual(rc, 0)
        self.assertEqual(State.load().cache, {"k": 2})

    def test_status_names_the_unusable_file(self):
        self.path.write_text(json.dumps({"schema_version": 99}))
        rc, out = _run(["status"])
        self.assertEqual(rc, 0)
        self.assertIn("UNUSABLE", out)


if __name__ == "__main__":
    unittest.main()
