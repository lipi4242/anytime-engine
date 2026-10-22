"""When the weekly full reconciliation is due, from its stamp
{"at": iso, "ok": bool, "unresolved": [...]} (kept per business in the engine
State cache by the concern): none yet -> due; after a clean check -> 7 days
later; after a failed one -> the next day (retried at most once a day).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

FULL_EVERY = timedelta(days=7)


def weekly_due(stamp: dict[str, Any] | None, now: datetime) -> bool:
    try:
        last = datetime.fromisoformat(stamp["at"])
    except (KeyError, TypeError, ValueError):
        return True
    if (last.tzinfo is None) != (now.tzinfo is None):
        last, now = last.replace(tzinfo=None), now.replace(tzinfo=None)
    if stamp.get("ok") is True:
        return now - last >= FULL_EVERY
    return last.date() < now.date()     # a failed check: at most once a day
