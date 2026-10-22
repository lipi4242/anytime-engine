#!/usr/bin/env python3
"""Where send.mjs is found, and the no-direct-API guard."""
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

from _fake_sendmjs import needs_node  # noqa: E402
from _telegram_base import TOKEN, Base  # noqa: E402
try:
    from anytime_cases import telegram  # noqa: E402
except ImportError:  # pack not vendored into this repo
    raise unittest.SkipTest("anytime_cases pack not present")


class TestLocate(Base):
    def test_no_location_is_an_error_without_api_fallback(self):
        os.environ.pop("SUBETHA_SEND_MJS")
        with self.assertRaises(telegram.SendError) as cm:
            telegram.send(self.root, "hi")
        self.assertIn("SUBETHA_SEND_MJS", str(cm.exception))
        self.assertEqual(self.fake.calls, [])

    def test_missing_script_path_is_an_error(self):
        os.environ["SUBETHA_SEND_MJS"] = str(self.root / "nope.mjs")
        with self.assertRaises(telegram.SendError) as cm:
            telegram.send(self.root, "hi")
        self.assertIn("send.mjs not found", str(cm.exception))

    @needs_node
    def test_location_from_dotenv(self):
        script = os.environ.pop("SUBETHA_SEND_MJS")
        with (self.root / ".env").open("a") as fh:
            fh.write(f"SUBETHA_SEND_MJS={script}\n")
        telegram.send(self.root, "hi")
        self.assertEqual(len(self.fake.calls), 1)

    @needs_node
    def test_agent_name_gives_the_default_path(self):
        home = Path(tempfile.mkdtemp(prefix="k11-home-"))
        try:
            dest = home / ".config" / "kata-1" / "sub-etha"
            dest.mkdir(parents=True)
            shutil.copy(self.fake.script, dest / "send.mjs")
            os.environ.pop("SUBETHA_SEND_MJS")
            os.environ["SUBETHA_AGENT"] = "kata-1"
            real, os.environ["HOME"] = os.environ["HOME"], str(home)
            try:
                telegram.send(self.root, "hi")
            finally:
                os.environ["HOME"] = real
            self.assertEqual(len(self.fake.calls), 1)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_bad_agent_name_is_refused(self):
        os.environ.pop("SUBETHA_SEND_MJS")
        for bad in ("../x", "A b", "-x", "a/b", ""):
            os.environ["SUBETHA_AGENT"] = bad
            with self.assertRaises(telegram.SendError):
                telegram.send(self.root, "hi")


class TestNoDirectApi(unittest.TestCase):
    def test_no_bot_api_in_src(self):
        src = Path(__file__).parent.parent / "src"
        for f in src.rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn("api.telegram.org", text, f)
            self.assertNotIn("getUpdates", text, f)

if __name__ == "__main__":
    unittest.main()
