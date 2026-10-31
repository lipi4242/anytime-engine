"""Per-occurrence receipts: what the agent did with (task id, due_date).

An occurrence is one due_date of a task; completing a repeating task moves it
to the next date, so (id, due_date) names exactly one run. The steps are
appended to the engine's receipts file (fsynced, append-only, survives a lost
or restored state — receipts.py), under the delivery prefix, which the engine
never overlays on its concern timers:

    started    the agent began the work (`cli start`)
    worked     the work happened; completion may still be owed (`cli done`, first)
    completed  the API confirmed the completion (`cli done`, after the POST)
    held       it could not be done; a comment says why (`cli note`)

The provider reads them back so a crash between "work" and "complete" never
runs the same occurrence twice (worked -> only the completion is retried).
"""
from __future__ import annotations

from datetime import datetime

from anytime_engine import clock, receipts

PREFIX = receipts.DELIVERY_PREFIX + "todo:"
STEPS = ("started", "worked", "completed", "held")
OUTAGE = receipts.DELIVERY_PREFIX + "todo-outage:"


def name(task_id: str, due: str, step: str) -> str:
    if step not in STEPS:
        raise ValueError(f"unknown step {step!r}")
    return f"{PREFIX}{task_id}:{due}:{step}"


def record(task_id: str, due: str, step: str, at: datetime | None = None) -> None:
    receipts.append(name(task_id, due, step), trigger=None, result="ok",
                    at=at or clock.now())


def lookup() -> dict[tuple[str, str], dict[str, datetime]]:
    """{(task id, due_date): {step: when}} from the receipts file."""
    out: dict[tuple[str, str], dict[str, datetime]] = {}
    for key, rec in receipts.latest().items():
        if not key.startswith(PREFIX) or rec.get("result") != "ok":
            continue
        body = key[len(PREFIX):]
        head, _, step = body.rpartition(":")
        task_id, _, due = head.rpartition(":")
        if step in STEPS and task_id and due:
            out.setdefault((task_id, due), {})[step] = clock.parse(rec["at"])
    return out


def outage_name(day: str) -> str:
    return OUTAGE + day


def outage_reported(day: str) -> bool:
    rec = receipts.latest().get(outage_name(day))
    return bool(rec and rec.get("result") == "ok")
