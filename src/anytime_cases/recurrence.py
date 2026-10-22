"""Anchored recurrence — the v1 rule set of the cases plugin.

    monthly:<1..31>   the given day; in a shorter month its last day
    quarterly:<1..31> the same, every third month from the anchor's month
    yearly:<MM-DD>    that date; Feb 29 is Feb 28 in a common year
    weekly:<mon..sun> that weekday

The series is every rule date on or after `anchor_at` (the first due date).
Occurrences are computed when read — nothing is pre-generated, so an unpaid
month never disappears behind a later one. Pure functions, no clock.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class RecurrenceError(ValueError):
    """A rule outside the v1 set."""


def _clamped(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _parse(rule: str) -> tuple[str, object]:
    kind, _, arg = str(rule).partition(":")
    try:
        if kind in ("monthly", "quarterly") and 1 <= int(arg) <= 31:
            return kind, int(arg)
        if kind == "yearly":
            mm, dd = (int(x) for x in arg.split("-"))
            date(2028, mm, dd)          # leap year: validates 02-29 too
            return kind, (mm, dd)
        if kind == "weekly" and arg in WEEKDAYS:
            return kind, WEEKDAYS.index(arg)
    except ValueError:
        pass
    raise RecurrenceError(f"unknown recurrence {rule!r} "
                          f"(monthly:<day> | quarterly:<day> | yearly:<MM-DD> | weekly:<mon..sun>)")


def occurrences(rule: str, anchor: date, until: date) -> list[date]:
    """Every due date of the series from `anchor` to `until`, both inclusive."""
    kind, arg = _parse(rule)
    out: list[date] = []
    if kind == "weekly":
        d = anchor + timedelta(days=(arg - anchor.weekday()) % 7)
        while d <= until:
            out.append(d)
            d += timedelta(days=7)
        return out
    year, month = anchor.year, anchor.month
    while True:
        if kind in ("monthly", "quarterly"):
            d = _clamped(year, month, arg)
            step = 3 if kind == "quarterly" else 1
            year, month = year + (month - 1 + step) // 12, (month - 1 + step) % 12 + 1
        else:
            d = _clamped(year, arg[0], arg[1])
            year += 1
        if d > until:
            return out
        if d >= anchor:
            out.append(d)
