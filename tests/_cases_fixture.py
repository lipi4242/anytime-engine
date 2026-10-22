"""Shared fixture for the cases pack tests: a temp agent repo with a vendored
copy of the pack (copied exactly as an operator would by hand) and a brain.

The pack is optional. In the source tree it is `src/anytime_cases`; in an agent
repo it is vendored next to the engine (`<repo>/anytime_cases`, sync-to.sh
--pack cases). Where neither is present the cases tests skip, like the
calendar pack's do."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import unittest
from pathlib import Path

from _engine_isolation import IsolatedTestCase
from anytime_engine import plugins
from anytime_engine.assembler import clear_providers
from anytime_engine.registry import clear

_HOME = Path(__file__).resolve().parent.parent   # release/ or the vendored anytime_engine/
PACK_SRC = next((p for p in (_HOME / "src" / "anytime_cases", _HOME.parent / "anytime_cases")
                 if (p / "__init__.py").is_file()), None)
if PACK_SRC is None:   # pack not vendored into this repo
    raise unittest.SkipTest("anytime_cases pack not present")

GAZ = """---
type: case
case_id: 01JAB6Z9Q3M8K7T2V5W4X1Y0RS   # ULID, generated once
title: Gázszámla
status: open
description: A havi gázszámla
next_action: Átutalni, amint megjön a számla
due_at: 2026-09-10
recurrence: monthly:10
anchor_at: 2026-08-10
occurrences:
  - { due_at: 2026-08-10, status: done, done_at: 2026-08-08, note: átutalva }
extra: {}
tags: [háztartás, pénzügy]
---

**Kontextus:** átutalással fizetjük.
"""
ADO = ("---\ntype: case\ncase_id: ADO1\ntitle: \"Adóbevallás\"\nstatus: open\n"
       "next_action: Beküldeni\ndue_at: 2026-10-17\n---\n")
KAR = ("---\ntype: case\ncase_id: KAR1\ntitle: Kárigény\nstatus: waiting\n"
       "waiting_on: a biztosító\ndue_at: 2026-10-15\n---\n")
KESZ = "---\ntype: case\ncase_id: KESZ1\ntitle: Lezárt\nstatus: done\ndue_at: 2026-10-01\n---\n"
PROJEKT = "---\ntype: project\ntitle: Gondolkodás\n---\n"
ROSSZ = "---\ntype: case\ncase_id: ROSSZ1\ntitle: Horgony nélkül\nstatus: open\nrecurrence: monthly:10\n---\n"


class CasesCase(IsolatedTestCase):
    backend = "markdown"
    files = {"gaz.md": GAZ, "ado.md": ADO, "kar.md": KAR, "kesz.md": KESZ,
             "projekt.md": PROJEKT, "rossz.md": ROSSZ}

    def setUp(self):
        super().setUp()
        clear()
        clear_providers()
        shutil.copytree(PACK_SRC, self.root / "anytime_cases",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / "mentat.json").write_text(json.dumps({
            "schema": 1, "components": {"brain": {"root": "agy"},
                                        "engine": {"plugins": ["anytime_cases"]}},
            "cases": {"backend": self.backend}}))
        cases = self.root / "agy" / "cases"
        cases.mkdir(parents=True)
        for name, text in self.files.items():
            (cases / name).write_text(text)
        sys.path.insert(0, str(self.root))
        self._purge()
        with contextlib.redirect_stderr(io.StringIO()):
            plugins.load(["anytime_cases"])

    def tearDown(self):
        sys.path.remove(str(self.root))
        self._purge()
        clear()
        clear_providers()
        super().tearDown()

    @staticmethod
    def _purge():
        for name in list(sys.modules):
            if name.split(".")[0] == "anytime_cases":
                del sys.modules[name]

    def local(self, admin: dict | None):
        (self.root / ".mentat").mkdir(exist_ok=True)
        doc = {"schema": 1}
        if admin is not None:
            doc["admin"] = admin
        (self.root / ".mentat" / "local.json").write_text(json.dumps(doc))
