#!/usr/bin/env python3
"""A case file with `due:` (the todo's field name) instead of the canonical `due_at:`.

h1 run 20261022-192041, stage 04: the brain wrote four cases by hand with `due:`, the
cases pack did not see their deadlines, and the agent renamed the field with sed during
the install. `due_at` stays canonical; `due` is read as its alias, never over it.
Compatible with pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _cases_fixture import CasesCase  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.state import State  # noqa: E402

T = datetime(2026, 10, 16, 8, 30)
CASES = {
    "regi-nev.md": "---\ntype: case\ncase_id: c-due\ntitle: Lisztszámla\nstatus: open\n"
                   "next_action: utalni\ndue: 2026-10-15\n---\n",
    "kanonikus.md": "---\ntype: case\ncase_id: c-due-at\ntitle: Napelem\nstatus: open\n"
                    "next_action: hívni\ndue_at: 2026-10-14\n---\n",
    "mindketto.md": "---\ntype: case\ncase_id: c-both\ntitle: Tábor\nstatus: open\n"
                    "next_action: fizetni\ndue_at: 2026-10-13\ndue: 2027-01-01\n---\n",
}


class TestDueAlias(CasesCase):
    files = {}

    def setUp(self):
        super().setUp()
        folder = self.root / "agy" / "cases"
        folder.mkdir(exist_ok=True)
        for name, text in CASES.items():
            (folder / name).write_text(text)

    def test_due_is_read_as_due_at_and_never_over_it(self):
        plan = reduce("review", State(), now=T)
        due = next(a for a in plan["actions"] if a["concern"] == "cases_morning")["context"]["cases.due"]
        got = {o["title"]: o["due_at"] for o in due["overdue"]}
        self.assertEqual(got.get("Lisztszámla"), "2026-10-15")  # the alias
        self.assertEqual(got.get("Napelem"), "2026-10-14")      # the canonical name still works
        self.assertEqual(got.get("Tábor"), "2026-10-13")        # due_at wins over due


if __name__ == "__main__":
    unittest.main()
