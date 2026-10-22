#!/usr/bin/env python3
"""The telegram channel hands the text to the sub-etha bridge's send.mjs (fake node script)."""
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


class TestSend(Base):
    @needs_node
    def test_text_goes_on_stdin_and_token_in_env(self):
        telegram.send(self.root, "Szia\nvilág")
        (call,) = self.fake.calls
        self.assertEqual(call["argv"], ["--chat", "42", "--text-stdin", "--why", telegram.WHY])
        self.assertEqual(call["stdin"], "Szia\nvilág")
        self.assertEqual(call["token"], TOKEN)

    @needs_node
    def test_long_text_is_one_call_the_bridge_splits_it(self):
        telegram.send(self.root, "x" * 9000)
        self.assertEqual(len(self.fake.calls), 1)

    @needs_node
    def test_why_is_always_passed_for_the_length_gate(self):
        telegram.send(self.root, "x" * 2000)
        argv = self.fake.calls[0]["argv"]
        self.assertGreaterEqual(len(argv[argv.index("--why") + 1]), 15)

    @needs_node
    def test_exit_3_is_sent(self):
        os.environ["FAKE_EXIT"] = "3"
        telegram.send(self.root, "hi")

    @needs_node
    def test_failure_codes_raise_with_code_and_masked_stderr(self):
        for code in (1, 4, 64):
            os.environ["FAKE_EXIT"] = str(code)
            os.environ["FAKE_STDERR"] = f"boom {TOKEN} " + "y" * 400
            with self.assertRaises(telegram.SendError) as cm:
                telegram.send(self.root, "hi")
            msg = str(cm.exception)
            self.assertIn(str(code), msg)
            self.assertNotIn(TOKEN, msg)
            self.assertIn("***", msg)
            self.assertLess(len(msg), 500)

    @needs_node
    def test_exit_5_says_uncertain(self):
        os.environ["FAKE_EXIT"] = "5"
        with self.assertRaises(telegram.SendError) as cm:
            telegram.send(self.root, "hi")
        self.assertIn("lehet, hogy kiment", str(cm.exception))

    @needs_node
    def test_timeout_says_uncertain(self):
        os.environ["FAKE_SLEEP"] = "3000"
        old, telegram.TIMEOUT_S = telegram.TIMEOUT_S, 1
        try:
            with self.assertRaises(telegram.SendError) as cm:
                telegram.send(self.root, "hi")
        finally:
            telegram.TIMEOUT_S = old
        self.assertIn("lehet, hogy kiment", str(cm.exception))

    def test_no_node_is_a_send_error(self):
        real, telegram.shutil.which = telegram.shutil.which, lambda _n: None
        try:
            with self.assertRaises(telegram.SendError) as cm:
                telegram.send(self.root, "hi")
        finally:
            telegram.shutil.which = real
        self.assertIn("node", str(cm.exception))

    def test_missing_token_and_chat(self):
        (self.root / ".env").write_text("TELEGRAM_CHAT_ID=42\n")
        with self.assertRaises(telegram.SendError) as cm:
            telegram.send(self.root, "hi")
        self.assertIn("TELEGRAM_BOT_TOKEN", str(cm.exception))
        self.assertEqual(self.fake.calls, [])
        (self.root / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\n")
        with self.assertRaises(telegram.SendError) as cm:
            telegram.send(self.root, "hi")
        self.assertIn("TELEGRAM_CHAT_ID", str(cm.exception))

if __name__ == "__main__":
    unittest.main()
