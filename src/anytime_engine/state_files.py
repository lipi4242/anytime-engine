"""File mechanics shared by the state, heartbeat and receipts: quarantine,
corruption-aware JSON reads, atomic writes, and the rolling prev.N backups.

No policy lives here — what to DO about a corrupt file is decided by the
caller (state_load.py for the state: restore or fail closed; heartbeat: raise).
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

BACKUPS_KEPT = 3


class CorruptStateFile(Exception):
    """A state file exists but is unreadable, unparseable, or has an
    unexpected schema. When raised by read_json_or_quarantine the file has
    already been moved to `{path}.bak.{stamp}`.

    Correctness-critical callers (heartbeat, connect token) must NOT treat this
    as "missing": silently re-creating those files masks bugs and, for the
    heartbeat, lets two orchestrators race.
    """


def _warn(label: str, msg: str) -> None:
    print(f"[{label}] {msg}", file=sys.stderr)


def quarantine_file(path: Path, *, label: str, reason: str) -> Path | None:
    """Move a file aside to `{path}.bak.{stamp}`; return where it went."""
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{stamp}")
    try:
        path.rename(backup)
        _warn(label, f"quarantined {path} -> {backup} ({reason})")
        return backup
    except OSError as e:
        _warn(label, f"failed to quarantine {path}: {e}")
        return None


def parse_json_file(path: Path) -> dict[str, Any]:
    """Parse a JSON object from `path`; CorruptStateFile on any failure."""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise CorruptStateFile(f"{path} unreadable ({type(e).__name__}: {e})") from e
    if not isinstance(data, dict):
        raise CorruptStateFile(f"{path} holds {type(data).__name__}, not an object")
    return data


def read_json_or_quarantine(path: Path, *, label: str,
                            expected_schema_version: int | None = None) -> dict[str, Any] | None:
    """None if missing; the dict if readable (and schema matches when checked);
    otherwise quarantine the file and raise CorruptStateFile."""
    if not path.exists():
        return None
    try:
        data = parse_json_file(path)
    except CorruptStateFile as e:
        quarantine_file(path, label=label, reason=str(e))
        raise
    if expected_schema_version is not None:
        version = data.get("schema_version")
        if version != expected_schema_version:
            quarantine_file(path, label=label,
                            reason=f"schema_version={version!r} (expected {expected_schema_version})")
            raise CorruptStateFile(
                f"{path} has schema_version={version!r}, expected {expected_schema_version}")
    return data


def backup_path(path: Path, n: int) -> Path:
    return path.with_suffix(path.suffix + f".prev.{n}")


def rotate_backups(path: Path, keep: int = BACKUPS_KEPT) -> None:
    """Drop prev.{keep}, demote prev.i -> prev.i+1, current -> prev.1.
    Never raises; a failed step is logged so the tick log shows it."""
    backup_path(path, keep).unlink(missing_ok=True)
    for i in range(keep - 1, 0, -1):
        src, dst = backup_path(path, i), backup_path(path, i + 1)
        if src.exists():
            try:
                src.rename(dst)
            except OSError as e:
                _warn("state", f"backup rotate failed {src} -> {dst}: {e}")
    if path.exists():
        try:
            path.rename(backup_path(path, 1))
        except OSError as e:
            _warn("state", f"backup rotate failed {path} -> .prev.1: {e}")


def write_json_atomic(path: Path, data: dict[str, Any], *, rotate: bool = False) -> None:
    """tmp write -> (optional backup rotation) -> atomic rename.
    Rotation happens AFTER the tmp is complete, so a failed write never
    destroys the current file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp", prefix=".state-")
    try:
        with open(fd, "w") as f:
            f.write(json.dumps(data, indent=2))
        if rotate:
            rotate_backups(path)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
