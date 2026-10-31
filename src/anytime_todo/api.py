"""The Mentat Admin todo API (mentat-admin docs/plugins/todo/INSTALL.md), the
four calls this pack needs:

    GET  /tasks?ball=<handle>&status=open&due_before=YYYY-MM-DD   -> [task]
    GET  /tasks/<id>                                              -> task (+children...)
    POST /tasks/<id>/complete  {expected_rev}     a repeating task rolls forward
    POST /tasks/<id>/comments  {body, expected_rev}

Header `X-Mentat-Token`; a custom User-Agent is mandatory (Cloudflare answers
the default Python-urllib one with 403). 409 carries {error, current}.
Every failure is a TodoApiError with the HTTP status (None = unreachable).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from anytime_engine import __version__ as ENGINE_VERSION

TIMEOUT_S = 10
USER_AGENT = f"mentat-anytime-todo/{ENGINE_VERSION}"


class TodoApiError(Exception):
    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class Client:
    def __init__(self, api: str, token: str):
        self.api = api.rstrip("/")
        self._token = token

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"X-Mentat-Token": self._token, "Accept": "application/json",
                   "User-Agent": USER_AGENT}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.api + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read() or b"null")
            except (ValueError, OSError):   # an unreadable error body is still this error
                err = None
            msg = err.get("error") if isinstance(err, dict) else None
            raise TodoApiError(f"todo API refused {method} {path.split('?')[0]}: HTTP {e.code}"
                               + (f" ({msg})" if msg else ""), e.code, err) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise TodoApiError(f"todo API unreachable: {e}") from None

    def due(self, handle: str, before: str) -> list[dict[str, Any]]:
        q = urllib.parse.urlencode({"ball": handle, "status": "open", "due_before": before})
        rows = self._call("GET", "/tasks?" + q)
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise TodoApiError("todo API answered /tasks with something other than a list")
        return rows

    def get(self, task_id: str) -> dict[str, Any]:
        row = self._call("GET", "/tasks/" + urllib.parse.quote(task_id, safe=""))
        if not isinstance(row, dict):
            raise TodoApiError("todo API answered /tasks/<id> with something other than a task")
        return row

    def complete(self, task_id: str, rev: int) -> dict[str, Any]:
        return self._call("POST", f"/tasks/{urllib.parse.quote(task_id, safe='')}/complete",
                          {"expected_rev": rev})

    def comment(self, task_id: str, body: str, rev: int) -> dict[str, Any]:
        return self._call("POST", f"/tasks/{urllib.parse.quote(task_id, safe='')}/comments",
                          {"body": body, "expected_rev": rev})
