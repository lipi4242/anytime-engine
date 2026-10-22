#!/usr/bin/env python3
"""setup --install writes a short engine block at the end of the agent's AGENTS.md.

The acceptance run (KJ 0.3.0, h1 10/11) showed the agent rediscovering the engine
every session: it built "the morning summary for a day" by hand from cases_cli
instead of `preview --at`, and told the user "we talk on Telegram" while the
delivery was a file. The block is always in context; it is idempotent and
keeps everything outside its markers.
Compatible with both pytest and direct execution (stdlib unittest).
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
from test_setup import SetupCase  # noqa: E402

START, END = "<!-- anytime-engine:begin -->", "<!-- anytime-engine:end -->"


class TestAgentsBlock(SetupCase):
    def agents(self) -> str:
        p = self.root / "AGENTS.md"
        return p.read_text() if p.exists() else ""

    def test_install_writes_the_block_with_preview_and_the_real_channel(self):
        (self.root / "AGENTS.md").write_text("# Persona\n\nkeep me\n")
        rc, out = self.run_setup("--tz", "Europe/Budapest", "--install")
        self.assertEqual(rc, 0, out)
        text = self.agents()
        self.assertTrue(text.startswith("# Persona\n\nkeep me\n"))
        block = text[text.index(START):text.index(END)]
        self.assertIn("preview --at", block)
        self.assertIn("file", block)
        self.assertIn("data/outbox/", block)
        self.assertIn("not on Telegram", block)
        self.assertIn("Europe/Budapest", block)
        self.assertLessEqual(len(block.splitlines()), 8)

    def test_dry_run_writes_nothing(self):
        (self.root / "AGENTS.md").write_text("# Persona\n")
        rc, out = self.run_setup("--tz", "Europe/Budapest")
        self.assertEqual(rc, 0, out)
        self.assertNotIn(START, self.agents())

    def test_rerun_replaces_the_block_once(self):
        (self.root / "AGENTS.md").write_text("# Persona\n")
        self.run_setup("--tz", "Europe/Budapest", "--install")
        self.run_setup("--tz", "Europe/Lisbon", "--install")
        text = self.agents()
        self.assertEqual(text.count(START), 1)
        self.assertIn("Europe/Lisbon", text)
        self.assertNotIn("Europe/Budapest", text)


if __name__ == "__main__":
    unittest.main()
