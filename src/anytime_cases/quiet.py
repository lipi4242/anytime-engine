"""Quiet hours — when a phone message must not go out (agent-local time).

mentat.json components.engine.quiet_hours: "HH:MM-HH:MM" (default 22:00-07:00;
it may wrap midnight; the end is not quiet any more), or "off". Inside the
window the executor sends no Telegram message and marks nothing, so the
messages stay owed and the first tick after the window sends them (from the
morning time on, the morning summary lists them in one message). A file
delivery is not a phone ping: it is never held.
"""
from __future__ import annotations

from datetime import datetime

DEFAULT = "22:00-07:00"
OFF = ("off", "", "none")


def parse(raw: str | None) -> tuple[str, str] | None:
    """("22:00", "07:00"), or None when switched off. ValueError on nonsense."""
    raw = DEFAULT if raw is None else str(raw).strip()
    if raw.lower() in OFF:
        return None
    start, sep, end = raw.partition("-")
    if not sep:
        raise ValueError(f"quiet_hours {raw!r}: expected HH:MM-HH:MM or off")
    fmt = lambda t: datetime.strptime(t.strip(), "%H:%M").strftime("%H:%M")  # noqa: E731
    return fmt(start), fmt(end)


def is_quiet(raw: str | None, when: datetime) -> bool:
    window = parse(raw)
    if window is None:
        return False
    start, end = window
    now = when.strftime("%H:%M")
    if start <= end:
        return start <= now < end
    return now >= start or now < end    # wraps midnight
