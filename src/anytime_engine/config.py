"""Engine configuration — per-repo paths and review schedule.

The engine is agent-agnostic: it does not know which repo it runs in.
The hosting repo configures it either by calling `set_repo_root()` early
(e.g. in its entry point or local package __init__), or via env vars:

  ANYTIME_REPO_ROOT      — repo root (default: cwd)
  ANYTIME_REVIEW_TIMES   — comma-separated HH:MM list (default: none — an agent
                           with no review configured never has a review due)
  ANYTIME_REVIEW_WINDOWS — named windows "name:HH:MM,name:HH:MM" (overrides the
                           auto-naming of ANYTIME_REVIEW_TIMES; lets a repo pin
                           exact names like morning/midday/evening/end_of_day)
  ANYTIME_STATE_PATH     — state file override
                           (default: <root>/data/state/anytime-state.json)
  THUFIR_STATE_PATH      — DEPRECATED alias of ANYTIME_STATE_PATH (0.3.x only)
  ANYTIME_RECEIPTS_PATH  — receipts file (default: beside the state file)
  ANYTIME_STATE_RESTORE_MAX_GAP_MIN — max history an automatic backup restore
                           may lose (default 180)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_repo_root: Path | None = None
_warned: set[str] = set()


def warn_once(key: str, message: str) -> None:
    """One stderr line per process per key — loud in the tick log, not spammy."""
    if key not in _warned:
        _warned.add(key)
        print(f"[anytime-engine] {message}", file=sys.stderr)


def set_repo_root(path: Path | str) -> None:
    """Pin the repo root explicitly (preferred over env/cwd inference)."""
    global _repo_root
    _repo_root = Path(path)


def repo_root() -> Path:
    if _repo_root is not None:
        return _repo_root
    env = os.environ.get("ANYTIME_REPO_ROOT")
    if env:
        return Path(env)
    return Path.cwd()


def review_times() -> list[str]:
    """Daily review times (HH:MM). Read lazily so tests/repos can override."""
    raw = os.environ.get("ANYTIME_REVIEW_TIMES", "")
    return [t.strip() for t in raw.split(",") if t.strip()]


def _name_for_time(hhmm: str) -> str:
    """Semantic window name from a HH:MM time-of-day. Domain-free heuristic so
    review_type() stays meaningful whatever times a repo configures."""
    try:
        hour = int(hhmm.split(":")[0])
    except (ValueError, IndexError):
        return "review"
    if hour < 10:
        return "morning"
    if hour < 15:
        return "midday"
    if hour < 20:
        return "evening"
    return "end_of_day"


def review_windows() -> list[tuple[str, str]]:
    """Named review windows [(name, "HH:MM"), ...] ascending by time.

    The window model (state.review_due/review_type/mark_review_serviced) keys off
    these so a review sent any time within a window services it and won't
    re-trigger a duplicate. Two sources, in priority order:

      1. ANYTIME_REVIEW_WINDOWS="morning:05:57,midday:12:27,..." — explicit names.
      2. else auto-name each ANYTIME_REVIEW_TIMES entry by time-of-day band,
         disambiguating any name collision with a numeric suffix.
    """
    raw = os.environ.get("ANYTIME_REVIEW_WINDOWS", "").strip()
    windows: list[tuple[str, str]] = []
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            name, _, t = part.partition(":")
            name, t = name.strip(), t.strip()
            if name and t:
                windows.append((name, t))
    else:
        seen: dict[str, int] = {}
        for t in review_times():
            base = _name_for_time(t)
            seen[base] = seen.get(base, 0) + 1
            name = base if seen[base] == 1 else f"{base}_{seen[base]}"
            windows.append((name, t))
    windows.sort(key=lambda w: w[1])
    return windows


def default_state_path() -> Path:
    """Where state lives when nothing overrides it: next to the heartbeat and
    last-tick.json, so one gitignore line (data/state/) covers all runtime files."""
    return repo_root() / "data" / "state" / "anytime-state.json"


def legacy_state_path() -> Path:
    """The pre-0.3 default. Read once by State.load() to migrate forward."""
    return repo_root() / "scripts" / "anytime" / "anytime-state-v2.json"


def state_path() -> Path:
    """The orchestrator state file. ANYTIME_STATE_PATH wins; THUFIR_STATE_PATH is
    honoured for one more minor release, with a warning."""
    env = os.environ.get("ANYTIME_STATE_PATH")
    if env:
        return Path(env)
    old = os.environ.get("THUFIR_STATE_PATH")
    if old:
        warn_once("THUFIR_STATE_PATH",
                  "THUFIR_STATE_PATH is deprecated and will be removed in 0.4 — "
                  "rename it to ANYTIME_STATE_PATH.")
        return Path(old)
    return default_state_path()


def heartbeat_path() -> Path:
    return repo_root() / "data" / "state" / "orchestrator-heartbeat.json"


def last_tick_path() -> Path:
    """Fleet contract: mtime = when a SCHEDULED tick last landed (after its work)."""
    return repo_root() / "data" / "state" / "last-tick.json"


def plan_path() -> Path:
    """The most recent plan a tick produced (input for the executor, not a stamp)."""
    return repo_root() / "data" / "state" / "last-plan.json"


def review_state_path() -> Path:
    """DEPRECATED (0.3): the calendar scan-cache path of the assistant this engine
    was extracted from. Kept one release so an un-cleaned vendored
    calendar_reconcile_cli keeps importing; the calendar pack takes --state."""
    warn_once("review_state_path",
              "config.review_state_path() is deprecated and will be removed in 0.4 — "
              "the calendar pack (anytime_calendar) takes an explicit --state path.")
    return repo_root() / "scripts" / "review-state" / "current.json"


def receipts_path() -> Path:
    """Durable operation receipts (receipts.py) — beside the state file, so the
    test isolation of the state path isolates them too."""
    env = os.environ.get("ANYTIME_RECEIPTS_PATH")
    return Path(env) if env else state_path().parent / "anytime-receipts.jsonl"


def restore_max_gap_minutes() -> float:
    """How much history a backup restore may lose: the gap between the lost
    write and the backup's mtime (default 180 min = three hourly ticks)."""
    try:
        return float(os.environ.get("ANYTIME_STATE_RESTORE_MAX_GAP_MIN", "180"))
    except ValueError:
        return 180.0
