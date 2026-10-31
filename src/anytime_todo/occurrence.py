"""Pure rules: is a task's current occurrence due, and what is owed for it.

A task is due when, in the TASK's timezone (task.tz, default Europe/Budapest),
its due_date has passed, or it is today and its due_time ("HH:MM", optional)
has been reached — on the task's wall clock, so a DST change (2026-10-25:
03:00 CEST -> 02:00 CET) does not fire an hour early, a skipped time (spring)
fires at the jump, and a repeated hour (autumn) fires on its first pass.

Owed, per occurrence (receipts, marks.py):
    (steps before a `completed` are history: open again on the same date
     means someone reopened it, and it is owed afresh)
    worked                       -> complete_pending (never redo the work)
    held, younger than retry     -> nothing (it waits; the comment says why)
    started, not held after it   -> interrupted (check before repeating)
    otherwise                    -> due
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from anytime_engine import clock

DEFAULT_TZ = "Europe/Budapest"


def utc_now(state) -> datetime:
    """state.now() is naive agent-local time; make it an aware UTC instant."""
    t = state.now()
    z = clock.zone()
    t = t.replace(tzinfo=z) if z else t.astimezone()
    return t.astimezone(timezone.utc)


def query_cutoff(now_utc: datetime) -> str:
    """The latest local date anywhere on Earth (UTC+14): the server filter is
    by date only, the exact per-task check happens here."""
    return (now_utc + timedelta(hours=14)).date().isoformat()


def is_due(task: dict[str, Any], now_utc: datetime) -> bool:
    """Raises ValueError on an unreadable date, time or zone."""
    if task.get("status") != "open" or task.get("archived") or not task.get("due_date"):
        return False
    try:
        zone = ZoneInfo(task.get("tz") or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown tz {task.get('tz')!r}") from None
    local = now_utc.astimezone(zone)
    due = date.fromisoformat(str(task["due_date"]))
    if local.date() != due:
        return local.date() > due
    if not task.get("due_time"):
        return True
    at = time.fromisoformat(str(task["due_time"]))
    # Wall clock: a skipped hour (spring) fires at the jump. Instant of the
    # first pass (fold=0): the repeated hour (autumn) cannot un-fire it.
    first = datetime.combine(due, at, tzinfo=zone)
    return (local.hour, local.minute) >= (at.hour, at.minute) or now_utc >= first


def item(task: dict[str, Any]) -> dict[str, Any]:
    """What the agent needs from a task: the instruction and the completion key."""
    return {k: task.get(k) for k in ("id", "title", "description", "due_date", "due_time",
                                     "tz", "repeat_rule", "rev")}


def owed(steps: dict[str, datetime], now: datetime, retry: timedelta) -> str | None:
    """The bucket of one occurrence (module doc); None = nothing owed now."""
    done = steps.get("completed")
    if done:   # completed, yet open on the same date: someone reopened it — a new run
        steps = {k: v for k, v in steps.items() if v > done}
    if "worked" in steps:
        return "complete_pending"
    held = steps.get("held")
    if held and now - held < retry:
        return None
    started = steps.get("started")
    if started and (not held or started > held):
        return "interrupted"
    return "due"
