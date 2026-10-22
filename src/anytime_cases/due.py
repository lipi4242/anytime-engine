"""Providers `cases.due` and `cases.signals` — open occurrences as of the
engine's clock (state.now(), pinned per reduction; no wall-clock read here).

An occurrence is open while the case is open/waiting and that date is not
closed: one-off cases have one (due_at); a recurring case has every anchored
date (recurrence.py) not listed as done/skipped in `occurrences`. A case that
cannot be read goes to `invalid` and the rest still count.

A signal is one message the deadline concern owes: `upcoming` when an open
occurrence is 1..WARN_DAYS away, `due` from its day on. It is owed until a
`delivered:<key>` receipt with result ok exists (delivery.py).
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

from anytime_engine import config
from anytime_engine.assembler import register_provider

from . import delivery, source
from .recurrence import RecurrenceError, occurrences

WEEK = 7
OPEN = ("open", "waiting")


def warn_days() -> int:
    return int(os.environ.get("ANYTIME_CASES_WARN_DAYS", "3"))


def _iso(v: Any) -> date:
    return date.fromisoformat(str(v)[:10])


def open_dates(case: dict[str, Any], until: date) -> list[date]:
    if case["status"] not in OPEN:
        return []
    if not case.get("recurrence"):
        if not case.get("due_at"):
            raise ValueError("an open case needs due_at")
        return [_iso(case["due_at"])]
    if not case.get("anchor_at"):
        raise ValueError("a recurring case needs anchor_at")
    closed = {str(o.get("due_at"))[:10] for o in case.get("occurrences") or []
              if isinstance(o, dict) and o.get("status") in ("done", "skipped")}
    moved = _iso(case["due_at"]) if case.get("due_at") else None
    dates = [d for d in occurrences(case["recurrence"], _iso(case["anchor_at"]), max(until, moved or until))
             if d.isoformat() not in closed]
    # The earliest open one may be moved later inside its own period (October
    # due on the 20th of a monthly:10 series) — the admin's rule (mentat-admin
    # cases resolve.ts). A due_at outside that period is ignored.
    if moved and dates and dates[0] < moved and (len(dates) == 1 or moved < dates[1]):
        dates[0] = moved
    return [d for d in dates if d <= until]


def _occ(c: dict[str, Any], d: date, today: date) -> dict[str, Any]:
    return {"case_id": c["case_id"], "title": c["title"], "status": c["status"],
            "description": c.get("description"), "next_action": c.get("next_action"),
            "due_at": d.isoformat(), "days": (d - today).days, "ref": c["ref"]}


def _waiting(c: dict[str, Any]) -> dict[str, Any]:
    return {k: c.get(k) for k in ("case_id", "title", "description", "next_action")}


def _from_markdown(root, today: date, until: date) -> dict[str, Any]:
    name, cases, invalid = source.load(root)
    occ: list[dict[str, Any]] = []
    for c in cases:
        try:
            occ += [_occ(c, d, today) for d in open_dates(c, until)]
        except (ValueError, RecurrenceError) as e:
            invalid.append({"file": c["ref"] or c["case_id"], "error": str(e)})
    todos = sum(1 for c in cases if c.get("kind") == "todo")
    return {"backend": name, "as_of": today.isoformat(), "occ": occ, "invalid": invalid,
            "scanned": {"cases": len(cases) - todos, "todos_with_due": todos},
            "waiting": [_waiting(c) for c in cases if c["status"] == "waiting"]}


def _from_admin(root, today: date, until: date) -> dict[str, Any]:
    """The admin computes the series; each item is already one open occurrence."""
    from . import admin
    items, waiting = admin.fetch(root, until)
    try:
        occ = [_occ({**i, "ref": i.get("brain_ref")}, _iso(i["due_at"]), today) for i in items
               if i.get("status") in OPEN]
    except (KeyError, ValueError) as e:
        raise source.CasesUnavailable(f"admin answered a due item without a date: {e}") from None
    return {"backend": "admin", "as_of": today.isoformat(), "occ": occ, "invalid": [],
            "waiting": [_waiting({**w, "case_id": w.get("id")}) for w in waiting]}


def compute(state) -> dict[str, Any]:
    """Memoised per reduction instant: should_run and assembly share one read."""
    memo = getattr(state, "_cases_memo", None)
    if memo and memo[0] == state.now():
        return memo[1]
    today = state.now().date()
    until = today + timedelta(days=max(WEEK, warn_days()))
    root = config.repo_root().resolve()
    if source.backend(root) == "admin":
        result = _from_admin(root, today, until)
    else:
        result = _from_markdown(root, today, until)
    result["occ"].sort(key=lambda o: (o["due_at"], o["case_id"]))
    state._cases_memo = (state.now(), result)
    return result


def due(state) -> dict[str, Any]:
    r = compute(state)
    return {"backend": r["backend"], "as_of": r["as_of"], "scanned": r.get("scanned"),
            "overdue": [o for o in r["occ"] if o["days"] < 0],
            "today": [o for o in r["occ"] if o["days"] == 0],
            "week": [o for o in r["occ"] if 0 < o["days"] <= WEEK],
            "waiting": r["waiting"], "invalid": r["invalid"],
            "mark": delivery.mark_name(f"cases_morning:{r['as_of']}")}


def signals(state) -> list[dict[str, Any]]:
    done = delivery.delivered()
    out = []
    for o in compute(state)["occ"]:
        kind = "due" if o["days"] <= 0 else "upcoming" if o["days"] <= warn_days() else None
        mark = delivery.mark_name(f"cases:{o['case_id']}:{o['due_at']}:{kind}")
        if kind and mark not in done:
            out.append({**o, "kind": kind, "mark": mark})
    return out


register_provider("cases.due", due)
register_provider("cases.signals", signals)
