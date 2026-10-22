"""Operation receipts — a durable, append-only record that a concern ran.

The state file is rewritten every tick and can be lost, corrupted or rolled
back. A receipt is appended (and fsynced) the moment a concern is marked done,
in a separate file, and State.load() overlays the newest receipt per concern on
whatever state it loaded. So losing or restoring the state never makes a
finished outbound action (an e-mail) look undone.

One JSON object per line: {"concern", "trigger", "at", "result"}. A torn last
line (crash mid-append) is skipped with a warning. The file is compacted to the
newest receipt per name once it passes COMPACT_BYTES.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import clock, config

COMPACT_BYTES = 1 << 20
REVIEW_PREFIX = "review-window:"
# A delivery receipt ("this message was confirmed sent", e.g. by a concern
# pack's executor): kept and compacted like any receipt, read by the pack via
# latest(), but never overlaid on the concern timers — it is not a concern.
DELIVERY_PREFIX = "delivered:"


def path() -> Path:
    return config.receipts_path()


def append(concern: str, *, trigger: str | None, result: str, at: datetime) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"concern": concern, "trigger": trigger,
                       "at": clock.stamp(at), "result": result}, ensure_ascii=False)
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    if p.stat().st_size > COMPACT_BYTES:
        _compact(p)


def latest() -> dict[str, dict[str, Any]]:
    """Newest receipt per concern name ({} when there are none)."""
    p = path()
    if not p.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with open(p, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            try:
                rec = json.loads(raw)
                name, at = rec["concern"], clock.parse(rec["at"])
            except (ValueError, KeyError, TypeError):
                if raw.strip():
                    print(f"[receipts] skipped unreadable line {lineno} in {p}", file=sys.stderr)
                continue
            prev = out.get(name)
            if prev is None or at >= clock.parse(prev["at"]):
                out[name] = rec
    return out


def _compact(p: Path) -> None:
    keep = latest()
    tmp = p.with_name(p.name + ".compact")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep.values()))
    os.replace(tmp, p)


def overlay(state: Any) -> None:
    """Make `state` at least as new as the receipts (newer receipt wins)."""
    for name, rec in latest().items():
        if name.startswith(DELIVERY_PREFIX):
            continue
        at = clock.parse(rec["at"])   # old naive or new offset stamp -> local
        if name.startswith(REVIEW_PREFIX):
            window = name[len(REVIEW_PREFIX):]
            day = state.reviews_serviced.setdefault(at.strftime("%Y-%m-%d"), [])
            if window not in day:
                day.append(window)
            continue
        cur = state.concern_last_run.get(name)
        if cur is None or clock.parse(cur) < at:
            state.concern_last_run[name] = at.isoformat()
            state.concern_last_result[name] = rec.get("result", "ok")

