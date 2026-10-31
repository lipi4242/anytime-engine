#!/usr/bin/env python3
"""The outward hold reaches the cases executor and the Telegram channel too:
a manual `python3 -m anytime_cases.deliver` only previews, and telegram.send
refuses — the last gate before a phone. Compatible with pytest and unittest.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from test_cases_deliver import T, TOKEN, DeliverCase, names  # noqa: E402
from _fake_sendmjs import FakeSend, needs_node  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.state import State  # noqa: E402
from test_hold import put  # noqa: E402


class TestHeldDelivery(DeliverCase):
    delivery = {"channel": "telegram"}

    def setUp(self):
        super().setUp()
        (self.root / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=42\n")
        self.fake = FakeSend()

    def tearDown(self):
        self.fake.stop()
        super().tearDown()

    @needs_node
    def test_manual_deliver_only_previews_and_marks_nothing(self):
        put(self.root)
        rc, out, err = self.run_plan(reduce("review", State(), now=T))
        self.assertEqual((rc, self.fake.sent), (0, []))
        self.assertIn("kifelé-tartás aktív", err)
        self.assertIn("Gázszámla", out)                     # shown, not sent
        self.assertIn("cases_morning", names(reduce("review", State.load(), now=T)))

    @needs_node
    def test_telegram_send_refuses_whoever_calls_it(self):
        put(self.root)
        with self.assertRaises(self.telegram.SendError) as cm:
            self.telegram.send(self.root, "emlékeztető a csapatnak")
        self.assertIn("kifelé-tartás aktív", str(cm.exception))
        self.assertEqual(self.fake.calls, [])

    @needs_node
    def test_after_release_it_sends_again(self):
        put(self.root).unlink()
        self.telegram.send(self.root, "szia")
        self.assertEqual(len(self.fake.calls), 1)


if __name__ == "__main__":
    unittest.main()
