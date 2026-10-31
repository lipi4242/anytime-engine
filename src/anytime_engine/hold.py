"""hold — the outward hold (kifelé-tartás): while it is on, nothing leaves the agent.

A developer building into a live agent must not let that agent talk to people
mid-build (H5, 2026-10: a live `tick hourly` sent a real reminder to the team
group). A procedure line ("only --dry-run during build") did not hold, so the
STATE is guarded instead: while the marker is active every tick is a dry run
(no executor, no state, no stamp), the cases executor only previews, and the
Telegram channel refuses to send.

Marker: <repo>/data/state/kifele-tartas.json (beside the heartbeat; gitignored)

    {"until": "2026-10-29T18:00:00+01:00",   required, ISO (naive = agent-local)
     "reason": "Vilma építése", "set_by": "fleet hold-outward", "set_at": "..."}

Written by `fleet hold-outward <agent> --until +4h`, removed by
`fleet release-outward <agent>`. Rules:
  - past `until`                  -> ignored, one stderr line says so
  - at most MAX_HOURS after it was written, whatever `until` says, so a forgotten
    hold cannot silence an agent for good. "Written" is `set_at` when present (the
    writer's own clock, so a faked or skewed box clock stays consistent; H2 harness
    2026-10-30), else the file's mtime
  - unreadable / no `until`       -> held (fail closed) for MAX_HOURS from mtime
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import clock, config

MAX_HOURS = 24
FILENAME = "kifele-tartas.json"


def path(root: Path | None = None) -> Path:
    return (root or config.repo_root()) / "data" / "state" / FILENAME


def _local(t: datetime) -> datetime:
    return clock.read(t.isoformat())


def active(now: datetime | None = None, root: Path | None = None) -> dict[str, Any] | None:
    """The hold in force right now ({until, reason, set_by, broken}), or None."""
    p = path(root)
    try:
        mtime = p.stat().st_mtime
    except FileNotFoundError:
        return None
    now = now or clock.now()
    written = _local(datetime.fromtimestamp(mtime, tz=timezone.utc))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        written = clock.read(str(data["set_at"])) if data.get("set_at") else written
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    cap = written + timedelta(hours=MAX_HOURS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        until = clock.read(str(data["until"]))
        info = {"reason": str(data.get("reason") or ""), "set_by": str(data.get("set_by") or "")}
        broken = False
    except (OSError, ValueError, TypeError, KeyError) as e:
        until, broken = cap, True
        info = {"reason": f"olvashatatlan jelző ({type(e).__name__}) — biztonságból tartva",
                "set_by": ""}
    until = min(until, cap)
    if until <= now:
        config.warn_once("hold-expired",
                         f"kifelé-tartás lejárt ({clock.stamp(until)}) — figyelmen kívül; "
                         f"a jelző törölhető: {p}")
        return None
    return {"until": clock.stamp(until), "broken": broken, **info}


def banner(h: dict[str, Any]) -> str:
    """The one line every held run prints."""
    extra = "; ".join(x for x in (h.get("reason"), h.get("set_by")) if x)
    return f"kifelé-tartás aktív — dry-run, eddig: {h['until']}" + (f" ({extra})" if extra else "")
