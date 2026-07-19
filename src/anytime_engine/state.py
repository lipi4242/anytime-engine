"""Thin state model — timers, flags, and caches only.

No duplicated data from external systems — the sources of truth are the
agent's own integrations (task list, calendar, registries). This file only
tracks session state and cached summaries.

`STATE_PATH` resolves to `THUFIR_STATE_PATH` if set, otherwise to the
canonical production file under the configured repo root (see config.py).
Tests MUST set this env var (the conftest fixture does this automatically)
so that test runs do not clobber the orchestrator's live state.

Unknown top-level keys in the state file are preserved across load/save
(forward compatibility: an agent-specific field written by a newer or
sibling build is carried, not dropped).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import config

STATE_PATH = config.state_path()
STATE_SCHEMA_VERSION = 1


# ── Shared corruption-tolerance helpers ────────────────────────────────
#
# Used by State.load() (here), heartbeat.read_heartbeat(), and
# developer_state._token() so all three behave consistently when their
# JSON files are corrupted. Lifted out of State so they are reachable
# from sibling modules without circular imports.


class CorruptStateFile(Exception):
    """Raised when a state file exists but is unreadable, unparseable,
    or has an unrecognized schema. The corrupt file is quarantined to
    `{path}.bak.{stamp}` before this is raised — the operator should
    investigate the backup before letting the system overwrite the path.

    Callers may catch this if "treat corruption as missing" is the
    desired behavior (State does this to keep ticks running). Callers
    that own correctness-critical state — heartbeat, connect token —
    must NOT catch it: silently re-creating those files masks bugs and,
    in heartbeat's case, can let two orchestrator instances race.
    """


def quarantine_file(path: Path, *, label: str, reason: str) -> None:
    """Move a corrupt state file aside so the path is free for a fresh write.

    `label` is a short tag used in the stderr message (e.g. "state",
    "heartbeat", "connect-token") so the operator can tell which file
    tripped during a tick log review.
    """
    import sys
    from datetime import datetime as _dt
    if not path.exists():
        return
    stamp = _dt.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{stamp}")
    try:
        path.rename(backup)
        print(f"[{label}] quarantined {path} -> {backup} ({reason})", file=sys.stderr)
    except OSError as e:
        print(f"[{label}] failed to quarantine {path}: {e}", file=sys.stderr)


def read_json_or_quarantine(
    path: Path,
    *,
    label: str,
    expected_schema_version: int | None = None,
) -> dict[str, Any] | None:
    """Read JSON from `path`. Quarantine + raise on corruption.

    Returns:
      - `None` if path does not exist
      - parsed dict if readable (and schema_version matches when checked)

    Raises `CorruptStateFile` if:
      - File exists but JSON parsing fails (any `OSError` or `JSONDecodeError`)
      - `expected_schema_version` is set and `data["schema_version"]` does
        not match it
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        quarantine_file(path, label=label, reason=f"unreadable ({type(e).__name__}: {e})")
        raise CorruptStateFile(f"{path} unreadable: {e}") from e

    if expected_schema_version is not None:
        version = data.get("schema_version")
        if version != expected_schema_version:
            quarantine_file(
                path,
                label=label,
                reason=f"schema_version={version!r} (expected {expected_schema_version})",
            )
            raise CorruptStateFile(
                f"{path} has schema_version={version!r}, expected {expected_schema_version}"
            )
    return data

# Default staleness threshold (minutes) — used when no concern-specific
# threshold is provided. Concerns should set staleness_minutes in their
# Concern dataclass; this fallback is for is_stale() calls outside the
# concern system (e.g., transitive dependency checks in resolve()).
DEFAULT_STALENESS_MINUTES = 60

class State:
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
        # Preserve unknown keys (agent-specific or future fields) verbatim.
        self._extra = {
            k: v for k, v in d.items()
            if k not in self._FIELDS and k != "schema_version"
        }

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
        return datetime.now() - last_dt > timedelta(minutes=threshold)

    def mark_run(self, concern_name: str, result: str = "ok") -> None:
        """Record that a concern just ran."""
        now = datetime.now().isoformat()
        self.concern_last_run[concern_name] = now
        self.concern_last_result[concern_name] = result

    def set_cache(self, key: str, value: Any) -> None:
        """Update a cache entry with timestamp."""
        self.cache[key] = value
        self.cache_timestamps[key] = datetime.now().isoformat()

    def get_cache(self, key: str, max_age_minutes: int = 60) -> Any | None:
        """Get cached value if fresh enough, else None."""
        ts = self.cache_timestamps.get(key)
        if not ts:
            return None
        age = datetime.now() - datetime.fromisoformat(ts)
        if age > timedelta(minutes=max_age_minutes):
            return None
        return self.cache.get(key)

    @staticmethod
    def _current_window(when: datetime | None = None) -> tuple[str, str] | None:
        """The review window in effect at `when`: the latest window whose open
        time is <= now. None before the day's first window.

        Windows come from config.review_windows() so review_due() and
        review_type() derive from ONE source and can never drift (the pre-window
        bug: review_type used broad hour-bands while review_due keyed off exact
        open-times, so a review sent early in a band did not "service" the window
        and review_due flipped True again, risking a duplicate)."""
        when = when or datetime.now()
        cur = when.strftime("%H:%M")
        active: tuple[str, str] | None = None
        for name, open_time in config.review_windows():
            if cur >= open_time:
                active = (name, open_time)
        return active

    def _serviced_today(self, today: str) -> set[str]:
        """Window names already serviced today. Falls back to last_review_at for
        state written before reviews_serviced existed (smooth migration)."""
        serviced = set(self.reviews_serviced.get(today, []))
        if not serviced and self.last_review_at:
            try:
                last = datetime.fromisoformat(self.last_review_at)
            except (ValueError, TypeError):
                return serviced
            if last.strftime("%Y-%m-%d") == today:
                w = self._current_window(last)
                if w:
                    serviced.add(w[0])
                elif self.last_review_type:
                    serviced.add(self.last_review_type)
        return serviced

    def review_due(self, now: datetime | None = None) -> bool:
        """True if the CURRENT review window has opened and isn't serviced today.

        Keyed off the window, not a raw timestamp: once a window is serviced it
        stays serviced until the next window opens — so an early send counts and
        review_due won't re-trigger a duplicate within the same window."""
        now = now or datetime.now()
        w = self._current_window(now)
        if not w:
            return False
        name, _ = w
        today = now.strftime("%Y-%m-%d")
        return name not in self._serviced_today(today)

    def review_type(self, now: datetime | None = None) -> str:
        """The current review window's name. Shares config.review_windows() with
        review_due() so the two can't disagree. Before the first window, reports
        the day's first (upcoming) window name."""
        w = self._current_window(now or datetime.now())
        if w:
            return w[0]
        windows = config.review_windows()
        return windows[0][0] if windows else "morning"

    def missed_review_windows(self, now: datetime | None = None) -> list[str]:
        """Earlier windows that opened today but were never serviced (excludes the
        current window). Lets a catch-up review say how many windows it missed."""
        now = now or datetime.now()
        today = now.strftime("%Y-%m-%d")
        cur = now.strftime("%H:%M")
        serviced = self._serviced_today(today)
        current = self._current_window(now)
        current_name = current[0] if current else None
        return [
            name for name, open_time in config.review_windows()
            if open_time <= cur           # window has opened today
            and name != current_name      # exclude the current window
            and name not in serviced      # and it was never serviced
        ]

    def mark_review_serviced(self, window_name: str | None = None,
                             when: datetime | None = None) -> str:
        """Record that the given (or current) review window was serviced. Also
        updates last_review_at/type for display + audit compatibility. Returns
        the window name serviced."""
        when = when or datetime.now()
        today = when.strftime("%Y-%m-%d")
        if window_name is None:
            w = self._current_window(when)
            window_name = w[0] if w else self.review_type(when)
        self.reviews_serviced.setdefault(today, [])
        if window_name not in self.reviews_serviced[today]:
            self.reviews_serviced[today].append(window_name)
        # Prune entries older than yesterday to keep the dict bounded.
        cutoff = (when - timedelta(days=2)).strftime("%Y-%m-%d")
        for d in [d for d in self.reviews_serviced if d < cutoff]:
            del self.reviews_serviced[d]
        self.last_review_at = when.isoformat()
        self.last_review_type = window_name
        return window_name

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
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "last_trigger": self.last_trigger,
            "last_trigger_at": self.last_trigger_at,
            "review_due": self.review_due(),
            "review_type": self.review_type(),
            "reviews_serviced_today": sorted(self._serviced_today(today)),
            "stale_concerns": stale,
            "concerns_run": len(self.concern_last_run),
        }

    @classmethod
    def load(cls) -> State:
        # State preserves "treat corruption as missing" semantics — a corrupt
        # state file is quarantined (loudly) and we tick on with a fresh one,
        # rather than crashing the orchestrator. heartbeat + connect-token
        # callers do NOT catch CorruptStateFile because their corruption
        # cannot be safely papered over (see CorruptStateFile docstring).
        try:
            data = read_json_or_quarantine(STATE_PATH, label="state")
        except CorruptStateFile:
            return cls()
        if data is None:
            return cls()

        version = data.get("schema_version")
        if version is None:
            # v0 file (legacy, no schema_version field) — auto-upgrade to v1.
            # Preserve all data; the next save() will add schema_version: 1.
            # This is the safe migration path: deploying Task 4 against the
            # live state file does NOT reset it.
            return cls(data)
        if version != STATE_SCHEMA_VERSION:
            # Recognized field but unknown value — likely a future build wrote
            # this file. Don't risk misinterpreting it; quarantine and reset.
            quarantine_file(
                STATE_PATH,
                label="state",
                reason=f"schema_version={version!r} (expected {STATE_SCHEMA_VERSION})",
            )
            return cls()
        return cls(data)

    def save(self) -> None:
        """Persist state to disk atomically with a rolling 3-deep backup.

        Order is rotate-AFTER-write so a failed write never destroys the
        previous current. The sequence is:
          1. Write new content to a tmp file in STATE_PATH.parent.
          2. Rotate backups (drop oldest, demote prev.{i} -> prev.{i+1},
             current -> prev.1).
          3. Atomic rename tmp -> current.

        Rolling backups give the operator a recovery path for accidental
        resets. They live next to STATE_PATH and are gitignored along
        with the main file.
        """
        data = json.dumps(self.to_dict(), indent=2)
        fd, tmp_path = tempfile.mkstemp(
            dir=STATE_PATH.parent, suffix=".tmp", prefix=".state-"
        )
        try:
            with open(fd, "w") as f:
                f.write(data)
            # Tmp is on disk and complete. Now rotate the existing backups
            # and current. If rotation partially fails, the tmp file is
            # still here and the atomic rename below will land it on top
            # of (whatever's left of) the current.
            self._rotate_backups(STATE_PATH)
            Path(tmp_path).replace(STATE_PATH)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    @staticmethod
    def _rotate_backups(path: Path, keep: int = 3) -> None:
        """Rotate path.prev.{keep-1..1} and demote current to prev.1.

        Robust to missing intermediates — a missing prev.N just skips
        that rotation step. Never raises. Failures are logged to stderr
        so the operator notices a missed rotation in the tick log.
        """
        import sys
        # Drop the oldest if it exists
        oldest = path.with_suffix(path.suffix + f".prev.{keep}")
        oldest.unlink(missing_ok=True)
        # Demote prev.{i} -> prev.{i+1} for i in keep-1 .. 1
        for i in range(keep - 1, 0, -1):
            src = path.with_suffix(path.suffix + f".prev.{i}")
            dst = path.with_suffix(path.suffix + f".prev.{i + 1}")
            if src.exists():
                try:
                    src.rename(dst)
                except OSError as e:
                    print(
                        f"[state] backup rotate failed {src} -> {dst}: {e}",
                        file=sys.stderr,
                    )
        # Demote current -> prev.1 (only if current exists)
        if path.exists():
            try:
                path.rename(path.with_suffix(path.suffix + ".prev.1"))
            except OSError as e:
                print(
                    f"[state] backup rotate failed {path} -> .prev.1: {e}",
                    file=sys.stderr,
                )

    @classmethod
    def reset(cls) -> State:
        """Create fresh state and persist it."""
        s = cls()
        s.save()
        return s
