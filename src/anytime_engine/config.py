"""Engine configuration — per-repo paths and review schedule.

The engine is agent-agnostic: it does not know which repo it runs in.
The hosting repo configures it either by calling `set_repo_root()` early
(e.g. in its entry point or local package __init__), or via env vars:

  ANYTIME_REPO_ROOT      — repo root (default: cwd)
  ANYTIME_REVIEW_TIMES   — comma-separated HH:MM list (default: "08:30,17:30")
  ANYTIME_REVIEW_WINDOWS — named windows "name:HH:MM,name:HH:MM" (overrides the
                           auto-naming of ANYTIME_REVIEW_TIMES; lets a repo pin
                           exact names like morning/midday/evening/end_of_day)
  THUFIR_STATE_PATH      — state file override (kept for back-compat; tests use it)
"""
from __future__ import annotations

import os
from pathlib import Path

_repo_root: Path | None = None


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
    raw = os.environ.get("ANYTIME_REVIEW_TIMES", "08:30,17:30")
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


def state_path() -> Path:
    """The orchestrator state file. THUFIR_STATE_PATH wins (test isolation)."""
    env = os.environ.get("THUFIR_STATE_PATH")
    if env:
        return Path(env)
    return repo_root() / "scripts" / "anytime" / "anytime-state-v2.json"


def heartbeat_path() -> Path:
    return repo_root() / "data" / "state" / "orchestrator-heartbeat.json"


def review_state_path() -> Path:
    """The scan-cache (calendar/email) written by scan concerns."""
    return repo_root() / "scripts" / "review-state" / "current.json"
