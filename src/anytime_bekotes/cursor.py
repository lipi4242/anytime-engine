"""The ingest cursor: `<business dir>/kurzor.json`.

    {"schema": 1, "sources": {name: <snapshot>}, "advanced_at": iso}

Saved atomically (tmp in the same folder + os.replace): a failed save leaves
the previous cursor untouched, so a crashed run simply repeats its diff.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

NAME = "kurzor.json"


def path(biz_dir: str | Path) -> Path:
    return Path(biz_dir) / NAME


class CursorError(ValueError):
    """kurzor.json exists but cannot be read — never guessed, never overwritten
    silently: the fix is an explicit `frissit --baseline`."""


def load(biz_dir: str | Path) -> dict[str, Any] | None:
    """The saved cursor, or None when there is none yet (-> baseline).
    Raises CursorError for an unreadable / malformed file."""
    p = path(biz_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        raise CursorError(f"{p}: hibás kurzor ({e}) — futtasd: frissit --baseline") from e
    if not isinstance(data, dict) or not isinstance(data.get("sources"), dict) \
            or not all(isinstance(v, dict) for v in data["sources"].values()):
        raise CursorError(f"{p}: hibás kurzor (sources) — futtasd: frissit --baseline")
    return data


def save(biz_dir: str | Path, data: dict[str, Any]) -> None:
    save_as(path(biz_dir), data)


def save_as(p: Path, data: dict[str, Any]) -> None:
    """Atomic JSON write (also used for the pending run)."""
    fd, tmp = tempfile.mkstemp(prefix=f".{p.stem}-", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
