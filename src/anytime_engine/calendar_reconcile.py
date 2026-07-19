"""calendar_reconcile — authoritative window reconciliation of the calendar cache.

Pure logic only. The scan stays Claude-driven (gws); this module owns the
set-diff so it is deterministic and tested. This removes the historic bug where
the scan only ever *added* events and never noticed deletions or moves (an event
deleted-and-recreated keeps a new id, so the old one lingered).

The CLI (normalize raw gws output, reconcile current.json, print the diff) lives
in calendar_reconcile_cli.py to keep this module pure and import-cheap for the
providers/concerns that only need reconcile()/changes_since().

Spec: docs/superpowers/specs/2026-06-08-calendar-reconciliation-design.md
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional


@dataclass
class Change:
    type: str            # added | removed | moved | updated
    id: str
    summary: str
    start: str
    previously: Optional[dict]
    detected_at: str


def _to_utc(value: str) -> Optional[datetime]:
    """Parse an ISO date/datetime to a tz-aware UTC datetime, or None.

    All-day events ('YYYY-MM-DD') -> UTC midnight (consistent on both sides).
    Naive datetimes are assumed UTC. Comparisons must use the parsed instant,
    never the raw string — two offsets ('+02:00' vs 'Z') can denote the same
    instant yet differ as strings.
    """
    if not value:
        return None
    try:
        if len(value) == 10 and value[4] == "-" and value[7] == "-":
            d = date.fromisoformat(value)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, IndexError):
        return None


def _instant_changed(a: dict, b: dict, key: str) -> bool:
    return _to_utc(a.get(key, "")) != _to_utc(b.get(key, ""))


def _fields_changed(a: dict, b: dict) -> bool:
    return a.get("summary") != b.get("summary") or a.get("location") != b.get("location")


def _prev(ev: dict) -> dict:
    return {"start": ev.get("start"), "end": ev.get("end"),
            "summary": ev.get("summary"), "location": ev.get("location")}


def reconcile(fresh: list[dict], cached: dict[str, dict],
              window_start: str, window_end: str, now: datetime,
              scanned_calendars: set[str] | None = None):
    """Reconcile the cache to match the scan for [window_start, window_end].

    Returns (updated_cache: dict[id->event], changes: list[Change]).
    `now` stamps detected_at only; window membership uses parsed instants.
    Events whose start falls outside the scanned window are never removed.

    `scanned_calendars`: when given, a cached event is only eligible for removal
    if its `source_calendar` was actually scanned this run. This lets a caller
    skip an inaccessible calendar (e.g. a cross-domain 404) without wrongly
    deleting its previously-cached events — the reconcile still runs for the
    calendars that were reachable, instead of aborting entirely.
    """
    ws, we = _to_utc(window_start), _to_utc(window_end)
    stamp = now.isoformat()
    fresh_by_id = {e["id"]: e for e in fresh if e.get("id")}
    updated = dict(cached)
    changes: list[Change] = []

    for eid, fev in fresh_by_id.items():
        if eid not in cached:
            updated[eid] = fev
            changes.append(Change("added", eid, fev.get("summary", ""),
                                  fev.get("start", ""), None, stamp))
            continue
        cev = cached[eid]
        # Merge-preserve: overwrite only the scanned fields, keep any extra cached
        # keys (prep_notes, discussed, conflicts, first_seen, smoke_window_impact,
        # source_calendar, …) that downstream enrichment maintains.
        merged = {**cev, **fev}
        if _instant_changed(cev, fev, "start") or _instant_changed(cev, fev, "end"):
            updated[eid] = merged
            changes.append(Change("moved", eid, fev.get("summary", ""),
                                  fev.get("start", ""), _prev(cev), stamp))
        elif _fields_changed(cev, fev):
            updated[eid] = merged
            changes.append(Change("updated", eid, fev.get("summary", ""),
                                  fev.get("start", ""), _prev(cev), stamp))

    for eid, cev in cached.items():
        if eid in fresh_by_id:
            continue
        if scanned_calendars is not None:
            src = cev.get("source_calendar")
            if src is not None and src not in scanned_calendars:
                continue
        cstart = _to_utc(cev.get("start", ""))
        if cstart is not None and ws is not None and we is not None and ws <= cstart <= we:
            updated.pop(eid, None)
            changes.append(Change("removed", eid, cev.get("summary", ""),
                                  cev.get("start", ""), _prev(cev), stamp))

    return updated, changes


def changes_since(feed: list[dict], cutoff_iso: Optional[str]) -> list[dict]:
    """Return feed entries with detected_at >= cutoff_iso.

    String comparison on same-format naive-local isoformat is chronological.
    A falsy cutoff returns the whole feed.
    """
    if not cutoff_iso:
        return list(feed)
    return [c for c in feed if c.get("detected_at", "") >= cutoff_iso]
