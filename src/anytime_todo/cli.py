"""The agent's side of a recurring duty — run from the agent repo root.

    python3 -m anytime_todo.cli list                          # what is owed now (JSON, read only)
    python3 -m anytime_todo.cli start <id> --due D            # before the work
    python3 -m anytime_todo.cli done  <id> --due D [--rev N]  # ONLY after the work happened
    python3 -m anytime_todo.cli note  <id> --due D --text T   # cannot do it: comment, keep open

Exit codes: 0 ok · 1 refused/failed (nothing recorded) · 2 usage · 3 the work is
recorded but the completion did not land (the next tick lists it as
complete_pending; run `done` again, never the work).

`done` guards the occurrence by its date, not only by its rev: a 409 whose
current task is no longer open on D means this occurrence is already closed
(a lost response, or someone else) — success, not a retry. Still open on D
(only the rev moved, e.g. a comment) -> one retry with the current rev; that
cannot complete the NEXT occurrence, because D would have moved.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Any

from anytime_engine import config
from anytime_engine.state import State

from . import due, marks, settings
from .api import Client, TodoApiError


def _client() -> tuple[Client, settings.Settings]:
    s = settings.load(config.repo_root().resolve())
    if s is None:
        raise settings.TodoConfigError("the todo pack is not configured (TODO_API + TODO_HANDLE)")
    return Client(s.api, s.token()), s


def _closed(task: dict[str, Any], due_date: str) -> bool:
    return (task.get("status") != "open" or bool(task.get("archived"))
            or str(task.get("due_date")) != due_date)


def _current(e: TodoApiError, c: Client, task_id: str) -> dict[str, Any]:
    cur = e.body.get("current") if isinstance(e.body, dict) else None
    return cur if isinstance(cur, dict) else c.get(task_id)


def cmd_done(task_id: str, due_date: str, rev: int | None) -> int:
    marks.record(task_id, due_date, "worked")      # first: the work is a fact now
    try:
        c, _ = _client()
        if rev is None:
            task = c.get(task_id)
            if _closed(task, due_date):
                return _already(task_id, due_date)
            rev = int(task["rev"])
        try:
            c.complete(task_id, rev)
        except TodoApiError as e:
            if e.status is None or e.status >= 500:
                raise
            cur = _current(e, c, task_id)
            if _closed(cur, due_date):
                return _already(task_id, due_date)
            if e.status != 409:
                raise
            c.complete(task_id, int(cur["rev"]))   # still open on D: only the rev moved
    except (TodoApiError, settings.TodoConfigError) as e:
        print(f"work recorded, completion NOT confirmed: {e}\n"
              f"run again later: python3 -m anytime_todo.cli done {task_id} --due {due_date}",
              file=sys.stderr)
        return 3
    marks.record(task_id, due_date, "completed")
    print(f"completed {task_id} ({due_date})")
    return 0


def _already(task_id: str, due_date: str) -> int:
    marks.record(task_id, due_date, "completed")
    print(f"already completed: {task_id} ({due_date} is closed on the server)")
    return 0


def cmd_note(task_id: str, due_date: str, text: str) -> int:
    c, s = _client()
    body = f"{text.strip()}\n\n({s.handle}, {due_date})"
    for attempt in (1, 2):
        task = c.get(task_id)
        try:
            c.comment(task_id, body, int(task["rev"]))
            break
        except TodoApiError as e:
            if e.status != 409 or attempt == 2:
                raise
    marks.record(task_id, due_date, "held")
    print(f"noted on {task_id}; it stays open and comes back in {due.retry_hours():g} h")
    return 0


def cmd_list() -> int:
    r = due.compute(State.load(migrate=False))
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    return 0 if r.get("status") != "error" else 1


def _day(text: str) -> str:
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}") from None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m anytime_todo.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("start", "done", "note"):
        sp = sub.add_parser(name)
        sp.add_argument("id")
        sp.add_argument("--due", required=True, type=_day, help="the occurrence's due_date (YYYY-MM-DD)")
        if name == "done":
            sp.add_argument("--rev", type=int)
        if name == "note":
            sp.add_argument("--text", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "list":
            return cmd_list()
        if a.cmd == "start":
            marks.record(a.id, a.due, "started")
            print(f"started {a.id} ({a.due})")
            return 0
        if a.cmd == "done":
            return cmd_done(a.id, a.due, a.rev)
        return cmd_note(a.id, a.due, a.text)
    except (settings.TodoConfigError, TodoApiError) as e:
        print(f"[anytime_todo] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
