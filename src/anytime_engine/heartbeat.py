"""Orchestrator heartbeat / lease helpers.

The heartbeat file at data/state/orchestrator-heartbeat.json is the lease
the running orchestrator holds. Each tick verifies it still owns the lease
(owner_token matches) before performing side effects, then renews it.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .state import read_json_or_quarantine
from . import config


def heartbeat_path() -> Path:
    """data/state/ at the repo root — resolved lazily via config."""
    return config.heartbeat_path()

DEFAULT_FRESHNESS_MIN = 90
HEARTBEAT_SCHEMA_VERSION = 1


def generate_owner_token() -> str:
    """Return a 12-character hex token (~48 bits of entropy)."""
    return secrets.token_hex(6)


def read_heartbeat() -> dict[str, Any] | None:
    """Return the heartbeat dict, or None if missing.

    Raises `CorruptStateFile` (from state.py) if the heartbeat exists but
    is unreadable. A corrupt heartbeat MUST NOT be silently treated as
    "no lease" — that would let a second orchestrator instance start
    while the corrupt-but-presumably-still-running one renews its lease,
    breaking the single-instance guarantee. The corrupt file is
    quarantined first; the operator must investigate before the
    orchestrator can resume.
    """
    return read_json_or_quarantine(heartbeat_path(), label="heartbeat")


def write_heartbeat(owner_token: str, started_at: str | None = None, tty: str | None = None) -> dict[str, Any]:
    """Atomically write the heartbeat with the given owner_token.

    started_at: if None, looked up from existing heartbeat (when token matches)
                or set to now.
    Returns the written dict.
    """
    hb_path = heartbeat_path()
    hb_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()

    # Preserve started_at across renewals (same owner)
    if started_at is None:
        existing = read_heartbeat()
        if existing and existing.get("owner_token") == owner_token:
            started_at = existing.get("started_at", now)
        else:
            started_at = now

    data = {
        "schema_version": HEARTBEAT_SCHEMA_VERSION,
        "pid": os.getpid(),
        "owner_token": owner_token,
        "started_at": started_at,
        "last_tick_at": now,
    }
    if tty:
        data["tty"] = tty

    payload = json.dumps(data, indent=2)
    fd, tmp_path = tempfile.mkstemp(
        dir=hb_path.parent, suffix=".tmp", prefix=".heartbeat-"
    )
    try:
        with open(fd, "w") as f:
            f.write(payload)
        Path(tmp_path).replace(hb_path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return data


def is_stale(threshold_min: int = DEFAULT_FRESHNESS_MIN) -> bool:
    """True if heartbeat is missing or last_tick_at is older than threshold_min."""
    data = read_heartbeat()
    if not data:
        return True
    last = data.get("last_tick_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except (ValueError, TypeError):
        return True
    return datetime.now() - last_dt > timedelta(minutes=threshold_min)


def current_owner_token() -> str | None:
    """Return the owner_token from disk, or None if missing."""
    data = read_heartbeat()
    return data.get("owner_token") if data else None
