"""Shared fixture for the todo pack tests: a temp agent repo with a vendored copy
of the pack and a fake todo API (mentat-admin worker/src/plugins/todo: read.ts,
complete.ts, comments.ts — the parts the pack uses). Where the pack is not
vendored the todo tests skip, like the other packs'."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import sys
import threading
import unittest
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from _engine_isolation import IsolatedTestCase
from anytime_engine import plugins
from anytime_engine.assembler import clear_providers
from anytime_engine.registry import clear

_HOME = Path(__file__).resolve().parent.parent
PACK_SRC = next((p for p in (_HOME / "src" / "anytime_todo", _HOME.parent / "anytime_todo")
                 if (p / "__init__.py").is_file()), None)
if PACK_SRC is None:
    raise unittest.SkipTest("anytime_todo pack not present")

TOKEN = "test-token-not-a-secret"
BASE = "/api/todo/v1"
_ENV = ("TODO_API", "TODO_HANDLE", "TODO_TOKEN_FILE", "ANYTIME_TODO_RETRY_HOURS",
        "ANYTIME_TODO_ALERT_HOURS", "ANYTIME_RECEIPTS_PATH")


def task(tid: str, due: str, *, time: str | None = None, tz: str = "Europe/Budapest",
         rev: int = 1, repeat: str | None = "daily", title: str = "Reggeli kör") -> dict:
    return {"id": tid, "title": title, "description": "Nézd át a nyitott ügyeket.",
            "status": "open", "due_date": due, "due_time": time, "tz": tz, "repeat_rule": repeat,
            "rev": rev, "owner_id": "P-AGENT", "assignee_id": None, "archived": 0}


def rolled(due: str) -> str:
    """complete.ts nextDate for `daily`: the first date after max(due, today in tz)."""
    today = datetime.now(ZoneInfo("Europe/Budapest")).date()
    return (max(date.fromisoformat(due), today) + timedelta(days=1)).isoformat()


class FakeTodo(BaseHTTPRequestHandler):
    """State lives on the server object: tasks {id: task}, calls [(method, path)]."""

    def _send(self, status: int, out) -> None:
        body = json.dumps(out).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _auth(self) -> bool:
        srv = self.server
        n = int(self.headers.get("Content-Length") or 0)
        self.body = json.loads(self.rfile.read(n)) if n else None   # read before any answer
        srv.calls.append((self.command, self.path))
        if self.headers.get("User-Agent", "").startswith("Python-urllib"):
            self._send(403, {"error": "cloudflare"})   # the edge blocks the default agent
        elif srv.down:
            self._send(503, {"error": "down"})
        elif self.headers.get("X-Mentat-Token") != TOKEN:
            self._send(403, {"error": "forbidden"})
        else:
            return True
        return False

    def do_GET(self):  # noqa: N802
        if not self._auth():
            return
        u = urlparse(self.path)
        tasks = self.server.tasks
        if u.path == BASE + "/tasks":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if q.get("ball") != "rocky":
                return self._send(422, {"error": "ball must be a known handle"})
            rows = [t for t in tasks.values() if t["status"] == q.get("status", t["status"])
                    and t["due_date"] and t["due_date"] <= q.get("due_before", "9999")]
            return self._send(200, rows)
        tid = u.path.rsplit("/", 1)[-1]
        return self._send(200, tasks[tid]) if tid in tasks else self._send(404, {"error": "no"})

    def do_POST(self):  # noqa: N802
        if not self._auth():
            return
        body = self.body
        parts = urlparse(self.path).path.split("/")
        t = self.server.tasks.get(parts[-2])
        if t is None:
            return self._send(404, {"error": "no"})
        if body.get("expected_rev") != t["rev"]:
            return self._send(409, {"error": "stale rev", "current": copy.deepcopy(t)})
        if self.server.lose_next:          # the write lands, the answer is lost
            self.server.lose_next = False
            self._apply(parts[-1], t, body)
            return self._send(502, {"error": "bad gateway"})
        self._apply(parts[-1], t, body)
        return self._send(200, t)

    def _apply(self, verb: str, t: dict, body: dict) -> None:
        t["rev"] += 1
        if verb == "comments":
            self.server.comments.append((t["id"], body["body"]))
        elif t["repeat_rule"]:        # roll the same row forward (daily), beyond today
            t["due_date"] = rolled(t["due_date"])
        else:
            t["status"] = "done"

    def log_message(self, *a):
        pass


class TodoCase(IsolatedTestCase):
    handle = "rocky"

    def setUp(self):
        super().setUp()
        self._saved = {k: os.environ.pop(k, None) for k in _ENV}
        clear()
        clear_providers()
        shutil.copytree(PACK_SRC, self.root / "anytime_todo",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.srv = HTTPServer(("localhost", 0), FakeTodo)
        self.srv.tasks, self.srv.calls, self.srv.comments = {}, [], []
        self.srv.down, self.srv.lose_next = False, False
        threading.Thread(target=self.srv.serve_forever, args=(0.05,), daemon=True).start()
        sys.path.insert(0, str(self.root))
        self._purge()
        with contextlib.redirect_stderr(io.StringIO()):
            plugins.load(["anytime_todo"])

    def configure(self, *, api: str | None = None, mode: int = 0o600) -> None:
        tok = self.root / "todo.token"
        tok.write_text(TOKEN + "\n")
        tok.chmod(mode)
        os.environ.update(TODO_API=api or f"http://localhost:{self.srv.server_port}{BASE}",
                          TODO_HANDLE=self.handle, TODO_TOKEN_FILE=str(tok))

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        sys.path.remove(str(self.root))
        self._purge()
        clear()
        clear_providers()
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    @staticmethod
    def _purge():
        for name in list(sys.modules):
            if name.split(".")[0] == "anytime_todo":
                del sys.modules[name]

    def mod(self, name: str):
        return sys.modules["anytime_todo." + name]
