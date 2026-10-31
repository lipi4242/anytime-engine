"""Provider `todo.due`: the agent's due recurring duties, read from the todo API.

One read per reduction instant (should_run and the provider share it). Never
raises into the tick: an API or token failure becomes {"status": "error"} and
a backoff in the state cache (5, 10, 20, 40, then 60 min between attempts), so
a dead API is not hammered. An outage longer than ANYTIME_TODO_ALERT_HOURS
(default 6) is reported to the owner once per day (`outage` in the result),
because a silent scheduler is the failure the owner cannot see.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from typing import Any

from anytime_engine import clock, config
from anytime_engine.assembler import register_provider

from . import marks, occurrence, settings
from .api import Client, TodoApiError

HEALTH = "anytime_todo.api"
BUCKETS = ("due", "complete_pending", "interrupted")


def retry_hours() -> float:
    return float(os.environ.get("ANYTIME_TODO_RETRY_HOURS", "6"))


def alert_hours() -> float:
    return float(os.environ.get("ANYTIME_TODO_ALERT_HOURS", "6"))


def _backoff_minutes(failures: int) -> int:
    return min(5 * 2 ** (max(failures, 1) - 1), 60)


def _failed(state, error: str) -> dict[str, Any]:
    now = state.now()
    h = dict(state.cache.get(HEALTH) or {})
    h["failures"] = int(h.get("failures") or 0) + 1
    h.setdefault("since", clock.stamp(now))
    h["error"] = error
    h["retry_at"] = clock.stamp(now + timedelta(minutes=_backoff_minutes(h["failures"])))
    state.set_cache(HEALTH, h)
    print(f"[anytime_todo] {error} (attempt {h['failures']}, next try {h['retry_at']})",
          file=sys.stderr)
    return h


def _error(state, h: dict[str, Any]) -> dict[str, Any]:
    day = state.now().date().isoformat()
    long_out = state.now() - clock.parse(h["since"]) >= timedelta(hours=alert_hours())
    owed = long_out and not marks.outage_reported(day)
    return {"configured": True, "status": "error", "error": h.get("error"),
            "since": h.get("since"), "failures": h.get("failures"), "retry_at": h.get("retry_at"),
            "outage": {"mark": marks.outage_name(day)} if owed else None}


def _classify(tasks: list[dict[str, Any]], state) -> dict[str, Any]:
    now_utc = occurrence.utc_now(state)
    done = marks.lookup()
    retry = timedelta(hours=retry_hours())
    out: dict[str, Any] = {b: [] for b in BUCKETS}
    out.update(held=[], invalid=[])
    for t in tasks:
        try:
            if not occurrence.is_due(t, now_utc):
                continue
        except ValueError as e:
            out["invalid"].append({"id": t.get("id"), "title": t.get("title"), "error": str(e)})
            continue
        steps = done.get((str(t.get("id")), str(t.get("due_date"))), {})
        bucket = occurrence.owed(steps, state.now(), retry)
        out[bucket or "held"].append(occurrence.item(t))
    return out


def compute(state) -> dict[str, Any]:
    memo = getattr(state, "_todo_memo", None)
    if memo and memo[0] == state.now():
        return memo[1]
    result = _compute(state)
    state._todo_memo = (state.now(), result)
    return result


def _compute(state) -> dict[str, Any]:
    s = settings.load(config.repo_root().resolve())
    if s is None:
        return {"configured": False}
    h = state.cache.get(HEALTH) or {}
    if h.get("retry_at") and state.now() < clock.parse(h["retry_at"]):
        return _error(state, h)
    try:
        tasks = Client(s.api, s.token()).due(s.handle, occurrence.query_cutoff(
            occurrence.utc_now(state)))
    except (TodoApiError, settings.TodoConfigError) as e:
        return _error(state, _failed(state, str(e)))
    state.cache.pop(HEALTH, None)
    state.cache_timestamps.pop(HEALTH, None)
    return {"configured": True, "status": "ok", "handle": s.handle,
            "as_of": clock.stamp(state.now()), **_classify(tasks, state)}


def owed(state) -> bool:
    """should_run: work owed, or an outage to report. Never raises."""
    try:
        r = compute(state)
    except Exception as e:   # noqa: BLE001 — a pack must not break the tick
        print(f"[anytime_todo] skipped: {type(e).__name__}: {e}", file=sys.stderr)
        return False
    if not r.get("configured"):
        return False
    if r["status"] != "ok":
        return bool(r.get("outage"))
    for bad in r["invalid"]:   # rides along with real work; alone it is not worth a run
        print(f"[anytime_todo] unreadable task {bad['id']}: {bad['error']}", file=sys.stderr)
    return any(r[b] for b in BUCKETS)


def provide(state) -> dict[str, Any]:
    return compute(state)


register_provider("todo.due", provide)
