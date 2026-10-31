#!/usr/bin/env python3
"""anytime_todo in a tick: off when not configured, the due list from the API
(custom User-Agent, ball/status/due_before), API errors with backoff and a
once-a-day outage report — never an exception into the tick.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _todo_fixture import TodoCase, task  # noqa: E402
from anytime_engine.prompts import get_prompt  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.state import State  # noqa: E402

T = datetime(2026, 10, 28, 8, 30)          # agent-local (Europe/Budapest)


class PackCase(TodoCase):
    def setUp(self):
        super().setUp()
        os.environ["ANYTIME_TZ"] = "Europe/Budapest"
        self.state = State()

    def plan(self, now=T, trigger="hourly"):
        return reduce(trigger, self.state, now=now)

    def action(self, now=T):
        return next((a for a in self.plan(now)["actions"] if a["concern"] == "todo_esedekes"), None)

    def gets(self):
        return [p for m, p in self.srv.calls if m == "GET"]


class TestOff(PackCase):
    def test_not_configured_is_silent(self):
        self.srv.tasks["A"] = task("A", "2026-10-27")
        plan = self.plan()
        self.assertEqual([a["concern"] for a in plan["actions"]], [])
        self.assertEqual(plan["context_errors"], [])
        self.assertEqual(self.srv.calls, [])

    def test_handle_without_api_is_still_off(self):
        os.environ["TODO_HANDLE"] = "rocky"
        self.assertIsNone(self.action())
        self.assertEqual(self.srv.calls, [])


class TestDue(PackCase):
    def setUp(self):
        super().setUp()
        self.configure()
        self.srv.tasks.update({
            "A": task("A", "2026-10-27", title="Heti emlékeztető"),         # overdue
            "B": task("B", "2026-10-28", time="08:00", rev=4),              # due 08:00 today
            "C": task("C", "2026-10-28", time="20:00"),                     # later today
            "D": {**task("D", "2026-10-20"), "archived": 1}})

    def test_due_items_and_the_request(self):
        ctx = self.action()["context"]["todo.due"]
        self.assertEqual(ctx["status"], "ok")
        self.assertEqual([(i["id"], i["rev"]) for i in ctx["due"]], [("A", 1), ("B", 4)])
        self.assertEqual(ctx["complete_pending"] + ctx["interrupted"], [])
        (path,) = self.gets()
        q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
        self.assertEqual(q, {"ball": "rocky", "status": "open", "due_before": "2026-10-28"})

    def test_nothing_due_yet_means_no_action(self):
        self.srv.tasks = {"C": self.srv.tasks["C"]}
        self.assertIsNone(self.action())

    def test_prompt_is_the_instruction_and_the_completion_contract(self):
        a = self.action()
        text = get_prompt(a["action"], a["context"])
        for needle in ("Heti emlékeztető", "python3 -m anytime_todo.cli start <id> --due <due_date>",
                       "ONLY after it really happened", "note <id>", "Never skip silently"):
            self.assertIn(needle, text)

    def test_worked_receipt_asks_only_for_the_completion(self):
        self.mod("marks").record("A", "2026-10-27", "worked", at=T - timedelta(minutes=5))
        ctx = self.action()["context"]["todo.due"]
        self.assertEqual([i["id"] for i in ctx["complete_pending"]], ["A"])
        self.assertEqual([i["id"] for i in ctx["due"]], ["B"])


class TestApiDown(PackCase):
    def setUp(self):
        super().setUp()
        self.configure()
        self.srv.tasks["A"] = task("A", "2026-10-27")
        self.srv.down = True

    def test_error_backs_off_and_does_not_raise(self):
        self.assertIsNone(self.action())                          # alert threshold not reached
        self.assertEqual(len(self.gets()), 1)
        h = self.state.cache["anytime_todo.api"]
        self.assertEqual((h["failures"], "503" in h["error"]), (1, True))
        self.assertIsNone(self.action(T + timedelta(minutes=3)))  # inside the 5 min backoff
        self.assertEqual(len(self.gets()), 1)
        self.action(T + timedelta(minutes=6))
        self.assertEqual((len(self.gets()), self.state.cache["anytime_todo.api"]["failures"]), (2, 2))

    def test_recovery_clears_the_backoff(self):
        self.action()
        self.srv.down = False
        a = self.action(T + timedelta(minutes=6))
        self.assertEqual([i["id"] for i in a["context"]["todo.due"]["due"]], ["A"])
        self.assertNotIn("anytime_todo.api", self.state.cache)

    def test_long_outage_is_reported_once_a_day(self):
        os.environ["ANYTIME_TODO_ALERT_HOURS"] = "0"
        a = self.action()
        ctx = a["context"]["todo.due"]
        self.assertEqual(ctx["outage"]["mark"], "delivered:todo-outage:2026-10-28")
        self.assertIn("todo API is DOWN", get_prompt(a["action"], a["context"]))
        self.state.last_trigger = "hourly"
        self.state.mark_run(ctx["outage"]["mark"])
        self.assertIsNone(self.action(T + timedelta(minutes=10)))

    def test_insecure_token_file_is_an_error_without_a_request(self):
        self.srv.down = False
        self.configure(mode=0o644)
        os.environ["ANYTIME_TODO_ALERT_HOURS"] = "0"
        ctx = self.action()["context"]["todo.due"]
        self.assertIn("chmod 600", ctx["error"])
        self.assertEqual(self.srv.calls, [])

    def test_default_user_agent_would_be_refused(self):
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        self.srv.down = False
        with self.assertRaises(HTTPError) as e:
            urlopen(Request(os.environ["TODO_API"] + "/tasks?ball=rocky"), timeout=5)
        self.assertEqual(e.exception.code, 403)          # so the pack's success above is its own UA
        self.assertEqual(self.action(T + timedelta(minutes=6))["context"]["todo.due"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
