"""clock — the agent's local time: what "07:00" and "today" mean.

A box usually runs on UTC; the person it serves does not. The engine's clock
is wall time in the agent's timezone, read from (first wins):

  ANYTIME_TZ                              e.g. Europe/Budapest
  mentat.json components.engine.timezone  recorded by `anytime_engine.setup`
  (neither)                               the machine's local time, as before

Times are naive datetimes in that zone, like every timestamp the state already
holds. An unknown zone is a ClockError — a guessed time is worse than a stop.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

ENV = "ANYTIME_TZ"


class ClockError(ValueError):
    """The configured timezone does not exist on this machine."""


def _utcnow() -> datetime:   # the single wall-clock read (tests pin it)
    return datetime.now(timezone.utc)


def tz_name() -> str | None:
    if os.environ.get(ENV):
        return os.environ[ENV]
    from . import engine_manifest, mentat_manifest as mm
    try:
        return engine_manifest.section().get("timezone") or None
    except mm.ManifestError:   # the tick refuses such a manifest on its own
        return None


def zone(name: str | None = None):
    """ZoneInfo for `name` (default: the configured one), or None = machine local."""
    name = name if name is not None else tz_name()
    if not name:
        return None
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ClockError(f"unknown timezone {name!r} (an IANA name like Europe/Budapest; "
                         f"on a slim box install tzdata)") from e


def now() -> datetime:
    """Wall time in the agent's timezone, naive."""
    z = zone()
    utc = _utcnow()
    return (utc.astimezone(z) if z else utc.astimezone()).replace(tzinfo=None)


def parse(text: str) -> datetime:
    """`--now` values: "now", or an ISO time. A naive time is already agent
    local; one with an offset is converted into the agent's zone."""
    if text in ("", "now"):
        return now()
    t = datetime.fromisoformat(text)
    if t.tzinfo is None:
        return t
    z = zone()
    return (t.astimezone(z) if z else t.astimezone()).replace(tzinfo=None)


def stamp(t: datetime | None = None) -> str:
    """A stamp the agent reads ("2026-10-19T13:17:03+02:00"): agent-local time
    WITH its offset, so neither the agent nor a reader takes it for the box's
    UTC (`ls` shows UTC mtimes on a box). `parse` reads it back as local time."""
    t = now() if t is None else t
    if t.tzinfo is None:
        z = zone()
        t = t.replace(tzinfo=z) if z else t.astimezone()
    return t.isoformat(timespec="seconds")
