"""Thin state model — timers, flags, and caches only.

No duplicated data from external systems — the sources of truth are the
agent's own integrations (task list, calendar, registries). This file only
tracks session state and cached summaries.

The state file is resolved lazily on every load/save (see `state_path()`):
`STATE_PATH` if a caller pinned it, else `config.state_path()` —
`ANYTIME_STATE_PATH`, or `<root>/data/state/anytime-state.json`. Resolving
lazily means `config.set_repo_root()` works even when called after import.
Tests MUST isolate it (tests/_engine_isolation.py, or the conftest fixture) so
that test runs do not clobber the orchestrator's live state.

Unknown top-level keys in the state file are preserved across load/save
(forward compatibility: an agent-specific field written by a newer or
sibling build is carried, not dropped).

Loading is fail-closed (state_load.py): a corrupt or
unknown-schema file is restored from a backup or refuses the tick — never
replaced by an empty state. Finished concerns are also kept as durable
receipts (receipts.py), overlaid on every load.
"""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from . import clock, config, receipts
from .state_files import (CorruptStateFile, quarantine_file,  # noqa: F401 (re-export)
                          read_json_or_quarantine, write_json_atomic)
from .state_load import (STATE_SCHEMA_VERSION, StateSchemaTooNew,  # noqa: F401
                         StateUnavailable, load_data)
from .state_reviews import ReviewWindowsMixin

# Optional pin (tests, embedding). None = resolve via config on every call.
STATE_PATH: Path | None = None


def state_path() -> Path:
    return STATE_PATH if STATE_PATH is not None else config.state_path()


def _migrate_legacy_state(path: Path, *, write: bool = True) -> Path:
    """Copy the pre-0.3 default state file forward, once. Returns the path to read.

    Only when `path` IS the new default (an explicit override never migrates),
    the new file does not exist yet, and the old one does. The old file is left
    in place so a rollback to 0.2.x still finds its state. With write=False
    (a dry run) nothing is copied; the legacy file is simply read in place.
    """
    import sys
    if path != config.default_state_path() or path.exists():
        return path
    legacy = config.legacy_state_path()
    if not legacy.exists():
        return path
    if not write:
        return legacy
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, path)
    print(f"[state] migrated {legacy} -> {path} (old file kept; "
          f"delete it once you are sure you will not roll back)", file=sys.stderr)
    return path


# Default staleness threshold (minutes) — used when no concern-specific
# threshold is provided. Concerns should set staleness_minutes in their
# Concern dataclass; this fallback is for is_stale() calls outside the
# concern system (e.g., transitive dependency checks in resolve()).
DEFAULT_STALENESS_MINUTES = 60

class State(ReviewWindowsMixin):
    """Minimal session state for the reducer."""

    # Schema: name -> default-factory. Add a field here AND only here.
    # __init__ and to_dict both iterate this dict, so a new attribute
    # automatically participates in serialization.
    _FIELDS: dict[str, Any] = {
        "last_trigger": lambda: None,
        "last_trigger_at": lambda: None,
        "concern_last_run": dict,
        "concern_last_result": dict,
        "cache": dict,
        "cache_timestamps": dict,
        "last_review_at": lambda: None,
        "last_review_type": lambda: None,
        # Per-day record of which review windows were serviced:
        # {"2026-07-10": ["morning", "midday"]}. Authoritative for review_due();
        # additive field (defaults to {} for old state files — no schema bump).
        "reviews_serviced": dict,
    }

    def __init__(self, data: dict[str, Any] | None = None):
        d = data or {}
        for name, default_factory in self._FIELDS.items():
            value = d.get(name)
            if value is None:
                value = default_factory()
            setattr(self, name, value)
        self._frozen_now: datetime | None = None  # see at(); never serialized
        # Preserve unknown keys (agent-specific or future fields) verbatim.
        self._extra = {
            k: v for k, v in d.items()
            if k not in self._FIELDS and k != "schema_version"
        }

    def now(self) -> datetime:
        """The time every State method uses: the instant pinned by at() (the
        reducer pins one per reduction), else the wall clock. Concerns and
        providers should read time through this, not the system clock."""
        return self._frozen_now or clock.now()

    @contextmanager
    def at(self, when: datetime) -> Iterator[State]:
        """Pin now() to `when` for the block (re-entrant; restores on exit)."""
        prev, self._frozen_now = self._frozen_now, when
        try:
            yield self
        finally:
            self._frozen_now = prev

    def is_stale(self, concern_name: str, threshold_minutes: int | None = None) -> bool:
        """Check if a concern's last run is older than a threshold.

        Args:
            concern_name: The concern to check.
            threshold_minutes: Override threshold. If None, uses DEFAULT_STALENESS_MINUTES.
                Concerns should pass their own staleness_minutes here.
        """
        last = self.concern_last_run.get(concern_name)
        if not last:
            return True
        threshold = threshold_minutes if threshold_minutes is not None else DEFAULT_STALENESS_MINUTES
        last_dt = datetime.fromisoformat(last)
        return self.now() - last_dt > timedelta(minutes=threshold)

    def mark_run(self, concern_name: str, result: str = "ok", *, durable: bool = True) -> None:
        """Record that a concern just ran — in memory AND, unless durable=False,
        as an fsynced receipt, so the record survives a crash before save() or
        the loss of the state file."""
        now = self.now()
        if concern_name.startswith(receipts.DELIVERY_PREFIX):  # a message, not a concern
            receipts.append(concern_name, trigger=self.last_trigger, result=result, at=now)
            return
        self.concern_last_run[concern_name] = now.isoformat()
        self.concern_last_result[concern_name] = result
        if durable:
            receipts.append(concern_name, trigger=self.last_trigger, result=result, at=now)

    def set_cache(self, key: str, value: Any) -> None:
        """Update a cache entry with timestamp."""
        self.cache[key] = value
        self.cache_timestamps[key] = self.now().isoformat()

    def get_cache(self, key: str, max_age_minutes: int = 60) -> Any | None:
        """Get cached value if fresh enough, else None."""
        ts = self.cache_timestamps.get(key)
        if not ts:
            return None
        age = self.now() - datetime.fromisoformat(ts)
        if age > timedelta(minutes=max_age_minutes):
            return None
        return self.cache.get(key)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = dict(self._extra)
        out["schema_version"] = STATE_SCHEMA_VERSION
        for name in self._FIELDS:
            out[name] = getattr(self, name)
        return out

    def summary(self) -> dict[str, Any]:
        """Compact summary for display."""
        stale = [
            name for name in self.concern_last_run
            if self.is_stale(name)
        ]
        now = self.now()
        today = now.strftime("%Y-%m-%d")
        return {
            "last_trigger": self.last_trigger,
            "last_trigger_at": self.last_trigger_at,
            # Quiet when unconfigured: an agent without reviews is not an error.
            "review_due": self.review_due(now) if config.review_windows() else False,
            "review_type": self.review_type(now),
            "reviews_serviced_today": sorted(self._serviced_today(today)),
            "stale_concerns": stale,
            "concerns_run": len(self.concern_last_run),
        }


    @classmethod
    def load(cls, *, migrate: bool = True) -> State:
        """Load state (fail-closed; raises StateUnavailable — see state_load.py),
        then overlay the receipts. migrate=False (dry runs) never writes: no
        legacy copy, no migration backup, no quarantine."""
        path = _migrate_legacy_state(state_path(), write=migrate)
        s = cls(load_data(path, write=migrate))
        receipts.overlay(s)
        return s

    def save(self) -> None:
        """Atomic write with a rolling 3-deep backup (rotate AFTER the tmp
        write, so a failed write never destroys the current file)."""
        write_json_atomic(state_path(), self.to_dict(), rotate=True)

    @classmethod
    def reset(cls) -> State:
        """Create fresh state and persist it (receipts are kept)."""
        s = cls()
        s.save()
        return s
