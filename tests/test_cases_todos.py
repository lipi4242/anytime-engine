#!/usr/bin/env python3
"""Todos with a `due:` date are read as one-off cases (agy/todos/*.md), read only.

2026-10-16 (04/10): the pack read only agy/cases/, so a todo due tomorrow was
never mentioned. Compatible with pytest and direct execution (stdlib unittest).
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
TODOS = {
    "hivas.md": "---\ntype: todo\nstatus: open\npriority: high\ndue: 2026-10-17\n---\n\n"
                "**Feladat:** Felhívni Kovács Bencét.\n",
    "folyamatban.md": "---\ntype: todo\nstatus: in-progress\ndue: 2026-10-10\ntitle: Szerviz\n---\n",
    "hatarido-nelkul.md": "---\ntype: todo\nstatus: open\n---\n**Feladat:** Valamikor.\n",
    "kesz.md": "---\ntype: todo\nstatus: done\ndue: 2026-10-01\n---\n",
    "rossz-datum.md": "---\ntype: todo\nstatus: open\ndue: holnap\n---\n",
    "_meta.md": "# todos\n",
}


class TestTodoDeadlines(CasesCase):
    files = {}

    def setUp(self):
        super().setUp()
        folder = self.root / "agy" / "todos"
        folder.mkdir()
        for name, text in TODOS.items():
            (folder / name).write_text(text)

    def due(self):
        plan = reduce("review", State(), now=T)
        return next(a for a in plan["actions"] if a["concern"] == "cases_morning"
                    )["context"]["cases.due"]

    def test_todos_with_a_due_date_are_listed(self):
        due = self.due()
        self.assertEqual([(o["title"], o["due_at"]) for o in due["overdue"]],
                         [("Szerviz", "2026-10-10")])
        self.assertEqual([(o["title"], o["next_action"], o["case_id"]) for o in due["week"]],
                         [("Felhívni Kovács Bencét.", "Felhívni Kovács Bencét.",
                           "todo:agy/todos/hivas.md")])

    def test_no_due_done_and_meta_are_not_deadlines_and_a_bad_date_is_invalid(self):
        due = self.due()
        listed = {o["case_id"] for k in ("overdue", "today", "week") for o in due[k]}
        self.assertEqual(listed, {"todo:agy/todos/hivas.md", "todo:agy/todos/folyamatban.md"})
        self.assertEqual([i["file"] for i in due["invalid"]], ["agy/todos/rossz-datum.md"])

    def test_a_signal_is_owed_and_the_todo_file_is_never_written(self):
        before = {p: p.read_text() for p in (self.root / "agy" / "todos").glob("*.md")}
        plan = reduce("hourly", State(), now=T)
        sig = next(a for a in plan["actions"] if a["concern"] == "cases_deadline")
        self.assertIn("todo:agy/todos/hivas.md", {s["case_id"] for s in sig["context"]["cases.signals"]})
        self.assertEqual(before, {p: p.read_text() for p in (self.root / "agy" / "todos").glob("*.md")})


if __name__ == "__main__":
    unittest.main()
