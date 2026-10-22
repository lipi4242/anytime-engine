"""Fixture for the bekotes concern tests: the pack copied into the temp agent
repo and loaded through plugins.load (as an agent loads it), the engine clock
patched for the `frissit` CLI."""
from __future__ import annotations

import contextlib
import importlib
import io
import re
import shutil
import sys
from datetime import datetime, timedelta
from unittest import mock

from _bekotes_fixture import PACK_SRC, BekotesCase
from anytime_engine import plugins
from anytime_engine.assembler import clear_providers
from anytime_engine.reducer import reduce
from anytime_engine.registry import clear
from anytime_engine.state import State

T = datetime(2026, 10, 15, 8, 30)
DAY, HOUR = timedelta(days=1), timedelta(hours=1)


def action(plan, name):
    return next((a for a in plan["actions"] if a["concern"] == name), None)


class ConcernCase(BekotesCase):

    def setUp(self):
        super().setUp()
        clear()
        clear_providers()
        shutil.copytree(PACK_SRC, self.root / "anytime_bekotes",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self._mods = {n: m for n, m in sys.modules.items() if n.split(".")[0] == "anytime_bekotes"}
        self._purge()
        sys.path.insert(0, str(self.root))
        with contextlib.redirect_stderr(io.StringIO()):
            plugins.load(["anytime_bekotes"])
        self.frissit = importlib.import_module("anytime_bekotes.frissit")
        self.kurzor = self.root / "agy" / "business" / "zoldag" / "kurzor.json"
        self.now = T

    def tearDown(self):
        sys.path.remove(str(self.root))
        self._purge()
        sys.modules.update(self._mods)
        clear()
        clear_providers()
        super().tearDown()

    @staticmethod
    def _purge():
        for name in list(sys.modules):
            if name.split(".")[0] == "anytime_bekotes":
                del sys.modules[name]

    def plan(self, trigger, when):
        return reduce(trigger, State(), now=when)

    def cli(self, *argv, when=None):
        out = io.StringIO()
        with mock.patch("anytime_engine.clock.now", return_value=when or self.now), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = self.frissit.main(list(argv))
        return rc, out.getvalue()

    def begin(self, when=None):
        rc, out = self.cli("--begin", when=when)
        self.assertEqual(rc, 0, out)
        self.last_begin = out
        return re.search(r"run_id: (\S+)", out).group(1)
