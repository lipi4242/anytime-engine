"""A fake sub-etha send.mjs: records argv, stdin and the token env, exits as told."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPT = """\
import fs from 'node:fs';
const stdin = fs.readFileSync(0, 'utf8');
fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify({
  argv: process.argv.slice(2), stdin, token: process.env.TELEGRAM_BOT_TOKEN || null}) + '\\n');
if (process.env.FAKE_STDERR) process.stderr.write(process.env.FAKE_STDERR);
if (process.env.FAKE_SLEEP) { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, +process.env.FAKE_SLEEP); }
process.exit(+(process.env.FAKE_EXIT || 0));
"""

# the telegram channel hands the text to send.mjs, so these tests need a real node
needs_node = unittest.skipUnless(
    shutil.which("node"), "node nincs a PATH-on — a telegram-csatorna tesztjei kimaradnak")


class FakeSend:
    """Install with start(); the env points the engine at the fake. stop() undoes it."""
    KEYS = ("SUBETHA_SEND_MJS", "SUBETHA_AGENT", "FAKE_LOG", "FAKE_EXIT", "FAKE_STDERR", "FAKE_SLEEP")

    def __init__(self, exit_code: int = 0, stderr: str = ""):
        self.dir = Path(tempfile.mkdtemp(prefix="fake-sendmjs-"))
        self.script, self.log = self.dir / "send.mjs", self.dir / "calls.jsonl"
        self.script.write_text(SCRIPT)
        self._old = {k: os.environ.get(k) for k in self.KEYS}
        for k in ("SUBETHA_AGENT", "FAKE_SLEEP"):
            os.environ.pop(k, None)
        os.environ.update(SUBETHA_SEND_MJS=str(self.script), FAKE_LOG=str(self.log),
                          FAKE_EXIT=str(exit_code), FAKE_STDERR=stderr)

    @property
    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(ln) for ln in self.log.read_text().splitlines()]

    @property
    def sent(self) -> list[dict]:
        return [{"chat_id": c["argv"][c["argv"].index("--chat") + 1], "text": c["stdin"]}
                for c in self.calls]

    def stop(self) -> None:
        for k, v in self._old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
