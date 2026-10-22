#!/usr/bin/env python3
"""State-path resolution, the THUFIR_* -> ANYTIME_* rename, and the migration
of the pre-0.3 default state file. Also: no personal review-time default.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
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
from anytime_engine import config  # noqa: E402
from anytime_engine.state import State  # noqa: E402


class TestStatePathResolution(IsolatedTestCase):
    def test_default_is_neutral_and_next_to_the_fleet_stamps(self):
        self.assertEqual(config.state_path(),
                         self.root / "data" / "state" / "anytime-state.json")

    def test_anytime_state_path_wins(self):
        os.environ["ANYTIME_STATE_PATH"] = str(self.root / "x.json")
        os.environ["THUFIR_STATE_PATH"] = str(self.root / "old.json")
        self.assertEqual(config.state_path(), self.root / "x.json")

    def test_thufir_state_path_still_honoured_with_a_warning(self):
        os.environ["THUFIR_STATE_PATH"] = str(self.root / "old.json")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(config.state_path(), self.root / "old.json")
        self.assertIn("THUFIR_STATE_PATH is deprecated", err.getvalue())
        self.assertIn("ANYTIME_STATE_PATH", err.getvalue())

    def test_save_creates_the_state_dir(self):
        s = State()
        s.mark_run("alpha")
        s.save()
        self.assertTrue(config.state_path().exists())


class TestLegacyStateMigration(IsolatedTestCase):
    def _legacy(self) -> Path:
        p = self.root / "scripts" / "anytime" / "anytime-state-v2.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"schema_version": 1,
                                 "concern_last_run": {"todos": "2026-10-14T08:00:00"}}))
        return p

    def test_old_default_file_is_migrated_on_load(self):
        legacy = self._legacy()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            s = State.load()
        self.assertEqual(s.concern_last_run, {"todos": "2026-10-14T08:00:00"})
        self.assertTrue(config.state_path().exists())       # copied forward
        self.assertTrue(legacy.exists())                    # original kept (rollback)
        self.assertIn("migrated", err.getvalue())

    def test_load_without_migrate_reads_legacy_and_writes_nothing(self):
        self._legacy()
        s = State.load(migrate=False)
        self.assertEqual(s.concern_last_run, {"todos": "2026-10-14T08:00:00"})
        self.assertFalse(config.state_path().exists())

    def test_new_file_wins_over_legacy(self):
        self._legacy()
        new = config.state_path()
        new.parent.mkdir(parents=True, exist_ok=True)
        new.write_text(json.dumps({"schema_version": 1, "concern_last_run": {}}))
        self.assertEqual(State.load().concern_last_run, {})

    def test_explicit_override_never_migrates(self):
        self._legacy()
        os.environ["ANYTIME_STATE_PATH"] = str(self.root / "elsewhere.json")
        self.assertEqual(State.load().concern_last_run, {})
        self.assertFalse((self.root / "elsewhere.json").exists())


class TestNoPersonalReviewDefault(IsolatedTestCase):
    def test_no_review_windows_unless_configured(self):
        self.assertEqual(config.review_times(), [])
        self.assertEqual(config.review_windows(), [])

    def test_unconfigured_review_is_never_due_and_says_why(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertFalse(State().review_due())
        self.assertIn("ANYTIME_REVIEW_TIMES", err.getvalue())


if __name__ == "__main__":
    unittest.main()
