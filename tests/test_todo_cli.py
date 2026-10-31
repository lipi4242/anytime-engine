#!/usr/bin/env python3
"""anytime_todo.cli: completion only after the work, exactly one occurrence per
run — rev conflicts, a lost answer, the API down mid-completion, notes.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _todo_fixture import TodoCase, rolled, task  # noqa: E402
from anytime_engine import clock  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.state import State  # noqa: E402


class CliCase(TodoCase):
    def setUp(self):
        super().setUp()
        os.environ["ANYTIME_TZ"] = "Europe/Budapest"
        self.configure()
        self.day = (clock.now().date() - timedelta(days=1)).isoformat()   # always due
        self.srv.tasks["A"] = task("A", self.day, rev=3)

    def cli(self, *argv) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = self.mod("cli").main(list(argv))
        return rc, out.getvalue() + err.getvalue()

    def owed(self) -> dict:
        a = next((a for a in reduce("hourly", State())["actions"]
                  if a["concern"] == "todo_esedekes"), None)
        ctx = a["context"]["todo.due"] if a else {}
        return {b: [i["id"] for i in ctx.get(b, [])] for b in ("due", "complete_pending", "interrupted")}

    def posts(self) -> list[str]:
        return [p for m, p in self.srv.calls if m == "POST"]

    def next_day(self) -> str:
        return rolled(self.day)


class TestDone(CliCase):
    def test_start_alone_completes_nothing(self):
        self.assertEqual(self.cli("start", "A", "--due", self.day)[0], 0)
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.srv.tasks["A"]["due_date"], self.day)
        self.assertEqual(self.owed(), {"due": [], "complete_pending": [], "interrupted": ["A"]})

    def test_done_rolls_the_repeating_task_once(self):
        self.cli("start", "A", "--due", self.day)
        rc, out = self.cli("done", "A", "--due", self.day, "--rev", "3")
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.srv.tasks["A"]["due_date"], self.srv.tasks["A"]["rev"]),
                         (self.next_day(), 4))
        self.assertEqual(self.owed(), {"due": [], "complete_pending": [], "interrupted": []})

    def test_rev_moved_but_same_occurrence_retries_once(self):
        self.srv.tasks["A"]["rev"] = 5                       # e.g. someone commented
        rc, out = self.cli("done", "A", "--due", self.day, "--rev", "3")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.posts()), 2)
        self.assertEqual(self.srv.tasks["A"]["due_date"], self.next_day())

    def test_lost_answer_then_rerun_does_not_complete_the_next_occurrence(self):
        self.srv.lose_next = True                            # lands, answer lost (502)
        rc, out = self.cli("done", "A", "--due", self.day, "--rev", "3")
        self.assertEqual(rc, 3, out)
        self.assertEqual(self.srv.tasks["A"]["due_date"], self.next_day())
        rc, out = self.cli("done", "A", "--due", self.day, "--rev", "3")
        self.assertEqual(rc, 0, out)
        self.assertIn("already completed", out)
        self.assertEqual(self.srv.tasks["A"]["due_date"], self.next_day())   # moved ONCE

    def test_api_down_keeps_the_work_and_owes_only_the_completion(self):
        self.cli("start", "A", "--due", self.day)
        self.srv.down = True
        rc, out = self.cli("done", "A", "--due", self.day, "--rev", "3")
        self.assertEqual(rc, 3, out)
        self.assertNotIn(TOKEN_SNIPPET, out)
        self.srv.down = False
        self.assertEqual(self.owed(), {"due": [], "complete_pending": ["A"], "interrupted": []})
        self.assertEqual(self.cli("done", "A", "--due", self.day)[0], 0)  # rev read fresh
        self.assertEqual(self.srv.tasks["A"]["due_date"], self.next_day())

    def test_not_configured_records_the_work_and_says_so(self):
        os.environ.pop("TODO_API")
        rc, out = self.cli("done", "A", "--due", self.day, "--rev", "3")
        self.assertEqual(rc, 3)
        self.assertIn("not configured", out)
        self.assertEqual(self.srv.calls, [])

    def test_bad_date_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as e, contextlib.redirect_stderr(io.StringIO()):
            self.mod("cli").main(["done", "A", "--due", "tegnap"])
        self.assertEqual(e.exception.code, 2)


class TestNote(CliCase):
    def test_note_comments_keeps_it_open_and_holds_it(self):
        self.cli("start", "A", "--due", self.day)
        self.srv.tasks["A"]["rev"] = 4
        rc, out = self.cli("note", "A", "--due", self.day, "--text", "Hiányzik a számla.")
        self.assertEqual(rc, 0, out)
        (tid, body), = self.srv.comments
        self.assertEqual(tid, "A")
        self.assertIn("Hiányzik a számla.", body)
        self.assertEqual((self.srv.tasks["A"]["status"], self.srv.tasks["A"]["due_date"]),
                         ("open", self.day))
        self.assertEqual(self.owed(), {"due": [], "complete_pending": [], "interrupted": []})
        os.environ["ANYTIME_TODO_RETRY_HOURS"] = "0"         # the hold has passed
        self.assertEqual(self.owed(), {"due": ["A"], "complete_pending": [], "interrupted": []})

    def test_note_failure_holds_nothing(self):
        self.srv.down = True
        self.assertEqual(self.cli("note", "A", "--due", self.day, "--text", "x")[0], 1)
        self.srv.down = False
        self.assertEqual(self.owed()["due"], ["A"])


class TestList(CliCase):
    def test_list_is_read_only_json(self):
        rc, out = self.cli("list")
        self.assertEqual(rc, 0, out)
        self.assertEqual([i["id"] for i in json.loads(out)["due"]], ["A"])
        self.assertEqual(self.posts(), [])


TOKEN_SNIPPET = "test-token-not-a-secret"

if __name__ == "__main__":
    unittest.main()
