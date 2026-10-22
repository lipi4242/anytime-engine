#!/usr/bin/env python3
"""cases.backend: admin. The admin API is the only source:
not connected, unreachable or refusing -> an error in the plan, never a quiet
fall-back to the markdown files lying next to it (mentat.json rule 4).

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _cases_fixture import CasesCase  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.state import State  # noqa: E402

T = datetime(2026, 10, 15, 8, 30)
TOKEN = "test-token-not-a-secret"
UNTIL = "2026-10-22"     # T + max(7 days, ANYTIME_CASES_WARN_DAYS)

# The real API's answers (mentat-admin worker/src/plugins/cases/read.ts):
# GET /api/cases/due?until= -> every open occurrence, one item per date, only
# a case's first one `closable`; GET /api/cases?status=waiting -> case rows
# (no occurrences, no context).
_ITEM = {"status": "open", "description": "A havi gázszámla", "next_action": "Átutalni",
         "recurrence": "monthly:10", "brain_ref": "agy/cases/gaz.md"}
DUE = [{"case_id": "GAZ", "title": "Gázszámla", **_ITEM, "due_at": "2026-09-10", "closable": True},
       {"case_id": "GAZ", "title": "Gázszámla", **_ITEM, "due_at": "2026-10-10", "closable": False},
       {"case_id": "KAR", "title": "Kárigény", **_ITEM, "status": "waiting", "recurrence": None,
        "description": "Csőtörés", "next_action": "Várunk a biztosítóra", "due_at": "2026-10-20", "closable": True}]
WAITING = [{"id": "KAR", "title": "Kárigény", "status": "waiting", "description": "Csőtörés",
            "next_action": "Várunk a biztosítóra", "due_at": "2026-10-20", "recurrence": None, "anchor_at": None,
            "brain_ref": None, "context_hash": None, "extra": {}, "version": 3,
            "created_at": "2026-10-01 08:00:00", "updated_at": "2026-10-02 08:00:00"}]
ROUTES = {"/api/cases/due?until=" + UNTIL: DUE, "/api/cases?status=waiting": WAITING}


class _Api(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.headers.get("X-Mentat-Token") != TOKEN:
            status, out = 401, {"error": "unauthorized"}
        elif self.path in ROUTES:
            status, out = 200, ROUTES[self.path]
        else:
            status, out = 422 if self.path.startswith("/api/cases/due") else 404, {"error": self.path}
        body = json.dumps(out).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class AdminCase(CasesCase):
    backend = "admin"

    def setUp(self):
        super().setUp()
        os.environ.pop("CASES_TEST_TOKEN", None)

    def tearDown(self):
        os.environ.pop("CASES_TEST_TOKEN", None)
        super().tearDown()

    def plan(self, trigger="review"):
        return reduce(trigger, State(), now=T)

    def assert_unavailable(self, needle):
        plan = self.plan()
        morning = next(a for a in plan["actions"] if a["concern"] == "cases_morning")
        self.assertEqual(list(morning["context"]["cases.due"]), ["error"])
        self.assertIn(needle, morning["context"]["cases.due"]["error"])
        self.assertTrue([e for e in plan["context_errors"] if e["provider"] == "cases.due"])
        hourly = self.plan("hourly")
        self.assertNotIn("cases_deadline", [a["concern"] for a in hourly["actions"]])


class TestAdminDown(AdminCase):
    def test_not_connected_is_an_error_not_markdown(self):
        self.assert_unavailable("not connected")

    def test_missing_token_is_an_error(self):
        self.local({"url": "http://localhost:9", "token_env": "CASES_TEST_TOKEN"})
        self.assert_unavailable("CASES_TEST_TOKEN")

    def test_unreachable_is_an_error(self):
        with socket.socket() as s:
            s.bind(("localhost", 0))
            port = s.getsockname()[1]          # closed again: nobody listens
        self.local({"url": f"http://localhost:{port}", "token_env": "CASES_TEST_TOKEN"})
        os.environ["CASES_TEST_TOKEN"] = TOKEN
        self.assert_unavailable("unreachable")


class TestAdminUp(AdminCase):
    def setUp(self):
        super().setUp()
        self.srv = HTTPServer(("localhost", 0), _Api)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.local({"url": f"http://localhost:{self.srv.server_port}",
                    "token_env": "CASES_TEST_TOKEN"})

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def test_reads_the_due_window_and_the_waiting_list(self):
        os.environ["CASES_TEST_TOKEN"] = TOKEN
        due = next(a for a in self.plan()["actions"]
                   if a["concern"] == "cases_morning")["context"]["cases.due"]
        self.assertEqual(due["backend"], "admin")
        self.assertEqual([(o["case_id"], o["due_at"], o["days"]) for o in due["overdue"]],
                         [("GAZ", "2026-09-10", -35), ("GAZ", "2026-10-10", -5)])
        self.assertEqual([(o["case_id"], o["days"]) for o in due["week"]], [("KAR", 5)])
        self.assertEqual(due["today"], [])
        self.assertEqual([(w["case_id"], w["description"], w["next_action"]) for w in due["waiting"]],
                         [("KAR", "Csőtörés", "Várunk a biztosítóra")])
        self.assertTrue(all("waiting_on" not in o for o in due["overdue"] + due["week"] + due["waiting"]))
        self.assertEqual(due["week"][0]["description"], "Csőtörés")
        self.assertEqual(due["invalid"], [])

    def test_deadline_signals_each_overdue_month(self):
        os.environ["CASES_TEST_TOKEN"] = TOKEN
        hourly = next(a for a in self.plan("hourly")["actions"] if a["concern"] == "cases_deadline")
        sig = hourly["context"]["cases.signals"]
        self.assertEqual([(s["case_id"], s["due_at"], s["kind"]) for s in sig],
                         [("GAZ", "2026-09-10", "due"), ("GAZ", "2026-10-10", "due")])

    def test_token_from_the_repo_env_file(self):
        (self.root / ".env").write_text(f"OTHER=1\nCASES_TEST_TOKEN={TOKEN}\n")
        due = next(a for a in self.plan()["actions"]
                   if a["concern"] == "cases_morning")["context"]["cases.due"]
        self.assertEqual(due.get("backend"), "admin", due)

    def test_refused_token_is_an_error(self):
        os.environ["CASES_TEST_TOKEN"] = "wrong"
        self.assert_unavailable("401")


if __name__ == "__main__":
    unittest.main()
