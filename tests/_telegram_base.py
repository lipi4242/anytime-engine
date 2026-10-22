"""Shared base for the telegram send.mjs tests: a repo .env, a fake send.mjs, clean env."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _fake_sendmjs import FakeSend

TOKEN = "123456:SECRET-test-token"
ENV_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "BRIDGE_STATE_DIR", "HOME")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="k11-"))
        (self.root / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=42\n")
        self._env = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS[:3]:
            os.environ.pop(k, None)
        self.fake = FakeSend()

    def tearDown(self):
        self.fake.stop()
        for k, v in self._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.fake.dir, ignore_errors=True)
