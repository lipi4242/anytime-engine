"""The in-flight run: `<business dir>/.pending-kurzor.json`, written by
`frissit --begin`, consumed by `frissit --advance <run_id>`.

    {"run_id", "started_at", "next": <cursor to save>, "changes", "deleted"}

It is git-ignored (`<business dir>/.gitignore`). A pending younger than
FRESH means a run is under way: the concern plans nothing and `--begin`
refuses; an older one is an interrupted run and is simply replaced.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import cursor

NAME = ".pending-kurzor.json"
FRESH = timedelta(hours=2)


def path(biz_dir: str | Path) -> Path:
    return Path(biz_dir) / NAME


def load(biz_dir: str | Path) -> dict[str, Any] | None:
    """The pending run, or None (none, or unreadable: an unreadable one never
    advances anything, so it is as good as absent)."""
    try:
        data = json.loads(path(biz_dir).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("run_id") else None


def fresh(p: dict[str, Any] | None, now: datetime) -> bool:
    if not p:
        return False
    try:
        started = datetime.fromisoformat(p["started_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if (started.tzinfo is None) != (now.tzinfo is None):
        started, now = started.replace(tzinfo=None), now.replace(tzinfo=None)
    return now - started < FRESH


def today(p: dict[str, Any] | None, now: datetime) -> bool:
    """A run begun today: a failed --advance must not replan the same day."""
    try:
        return bool(p) and datetime.fromisoformat(p["started_at"]).date() == now.date()
    except (KeyError, TypeError, ValueError):
        return False


def save(biz_dir: str | Path, data: dict[str, Any]) -> None:
    _ignore(Path(biz_dir))
    cursor.save_as(path(biz_dir), data)


def clear(biz_dir: str | Path) -> None:
    try:
        path(biz_dir).unlink()
    except FileNotFoundError:
        pass


def _ignore(biz_dir: Path) -> None:
    gi = biz_dir / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if NAME not in lines:
        gi.write_text("\n".join([*lines, NAME]) + "\n")
