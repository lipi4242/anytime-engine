#!/usr/bin/env python3
"""--find-chat reads the bridge events log (UTC dates), not the Bot API."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _telegram_base import TOKEN, Base  # noqa: E402
try:
    from anytime_cases import telegram  # noqa: E402
except ImportError:  # pack not vendored into this repo
    raise unittest.SkipTest("anytime_cases pack not present")


class TestFindChats(Base):
    def _events(self, day, updates):
        d = Path(os.environ["BRIDGE_STATE_DIR"]) / "telegram-inbox"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"events-{day}.jsonl").write_text("\n".join(json.dumps(u) for u in updates) + "\n")

    def test_chats_come_from_the_bridge_events_log(self):
        os.environ["BRIDGE_STATE_DIR"] = str(self.root / "bridge")
        today = datetime.now(timezone.utc).date()
        self._events(today.isoformat(), [
            {"update_id": 1, "message": {"chat": {"id": 7, "first_name": "Ann"}}},
            {"update_id": 2, "channel_post": {"chat": {"id": -9, "title": "Grp"}}}])
        self._events((today - timedelta(days=30)).isoformat(),
                     [{"update_id": 0, "message": {"chat": {"id": 1, "title": "Old"}}}])
        self.assertEqual(dict(telegram.find_chats(self.root)), {"7": "Ann", "-9": "Grp"})

    def test_malformed_lines_and_shapes_are_skipped(self):
        os.environ["BRIDGE_STATE_DIR"] = str(self.root / "bridge")
        today = datetime.now(timezone.utc).date().isoformat()
        self._events(today, [{"update_id": 1, "message": {"chat": "oops"}},
                             {"update_id": 2, "message": "x"}, [1, 2],
                             {"update_id": 3, "message": {"chat": {"id": 5, "title": "Ok"}}}])
        self.assertEqual(telegram.find_chats(self.root), [("5", "Ok")])

    def test_no_log_is_a_clear_error(self):
        os.environ["BRIDGE_STATE_DIR"] = str(self.root / "nope")
        with self.assertRaises(telegram.SendError) as cm:
            telegram.find_chats(self.root)
        self.assertIn("BRIDGE_STATE_DIR", str(cm.exception))
        os.environ.pop("BRIDGE_STATE_DIR")
        with self.assertRaises(telegram.SendError):
            telegram.find_chats(self.root)

if __name__ == "__main__":
    unittest.main()
