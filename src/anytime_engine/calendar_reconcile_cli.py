"""calendar_reconcile_cli — normalize raw gws output, reconcile current.json, print the diff.

The scan (Claude-driven gws) writes its raw output to a temp file and calls this;
it never hand-edits current.json. Pure reconcile logic lives in calendar_reconcile.py.

Usage (repo gyökeréből):
   python3 -m anytime_engine.calendar_reconcile_cli \\
       --fresh /tmp/scan.json --window-start ... --window-end ...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .calendar_reconcile import Change, reconcile
from . import config


def _normalize_gws_event(raw: dict) -> dict:
    """Map a raw Google Calendar event to the flat cache shape."""
    start = raw.get("start", {}) or {}
    end = raw.get("end", {}) or {}
    return {
        "id": raw.get("id"),
        "summary": raw.get("summary", ""),
        "start": start.get("dateTime") or start.get("date", ""),
        "end": end.get("dateTime") or end.get("date", ""),
        "location": raw.get("location", ""),
        "attendees": [a.get("email") for a in raw.get("attendees", []) if a.get("email")],
    }


def _prune(feed: list[dict], now: datetime, days: int = 30) -> list[dict]:
    """Drop change-feed entries older than `days`; keep unparseable rows."""
    cutoff = now.timestamp() - days * 86400
    out = []
    for c in feed:
        try:
            if datetime.fromisoformat(c["detected_at"]).timestamp() >= cutoff:
                out.append(c)
        except (ValueError, KeyError, TypeError):
            out.append(c)
    return out


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def _print_diff(changes: list[Change]) -> None:
    if not changes:
        print("Calendar reconciled: no changes.")
        return
    icon = {"added": "✅ Added", "removed": "❌ Removed",
            "moved": "🔀 Moved", "updated": "✏️  Updated"}
    print("Calendar changes:")
    for c in changes:
        print(f"  {icon.get(c.type, c.type)}: {c.summary or '(no title)'} ({c.start})")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Reconcile the calendar cache against a scan.")
    p.add_argument("--fresh", required=True, help="Path to raw gws events JSON")
    p.add_argument("--window-start", required=True)
    p.add_argument("--window-end", required=True)
    p.add_argument("--state", default=str(config.review_state_path()))
    p.add_argument("--now", default=None, help="ISO timestamp (tests only)")
    p.add_argument("--scanned-calendars", default=None,
                   help="Comma-separated source_calendar ids actually scanned "
                        "this run. Cached events from a calendar NOT listed are "
                        "preserved, not removed (soft-skip an inaccessible cal).")
    args = p.parse_args(argv)

    # Load fresh FIRST — never touch state on bad input (never delete on failure).
    try:
        raw = json.loads(Path(args.fresh).read_text())
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: cannot read fresh scan: {e}", file=sys.stderr)
        return 2
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        print("ERROR: fresh scan is not a list of events", file=sys.stderr)
        return 2
    fresh = [_normalize_gws_event(r) for r in items if isinstance(r, dict) and r.get("id")]

    state_path = Path(args.state)
    try:
        data = json.loads(state_path.read_text())
        if not isinstance(data, dict):
            data = {}
    except Exception:  # noqa: BLE001 — missing/corrupt -> empty cache
        data = {}

    cached = data.get("calendar_events", {}) or {}
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()

    scanned = None
    if args.scanned_calendars:
        scanned = {c.strip() for c in args.scanned_calendars.split(",") if c.strip()}

    updated, changes = reconcile(fresh, cached, args.window_start, args.window_end,
                                 now, scanned_calendars=scanned)

    data["calendar_events"] = updated
    data["calendar_scanned_window"] = {"start": args.window_start, "end": args.window_end}
    feed = data.get("calendar_changes", []) or []
    feed.extend(asdict(c) for c in changes)
    data["calendar_changes"] = _prune(feed, now, days=30)

    _atomic_write(state_path, data)
    _print_diff(changes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
