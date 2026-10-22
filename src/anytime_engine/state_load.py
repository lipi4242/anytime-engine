"""Load policy for the state file — fail closed, never reset silently.

Before 0.3 a corrupt or unknown-schema state file was quarantined and the
engine ticked on with an EMPTY state: every concern looked never-run, so work
already done (an e-mail sent) could run again. The policy now
(README: "A lost state never repeats work"):

  file readable, schema == current      -> use it
  known older schema (0 .. current-1)   -> pre-migration backup, then the
                                           explicit MIGRATIONS chain
  newer / unrecognised schema           -> StateSchemaTooNew; file untouched
  unreadable, or missing while prev.N   -> newest intact prev.N whose gap to the
  backups exist                            lost write is <= the restore gap;
                                           corrupt file quarantined (kept)
  none of that possible                 -> StateUnavailable; no tick runs
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import config
from .state_files import (BACKUPS_KEPT, CorruptStateFile, backup_path,
                          parse_json_file, quarantine_file)

STATE_SCHEMA_VERSION = 1


class StateUnavailable(Exception):
    """The state cannot be trusted; the engine must not tick on it."""


class StateSchemaTooNew(StateUnavailable):
    """Written by a newer engine (or unrecognised). Not touched, not reset."""


def _v0_to_v1(data: dict[str, Any]) -> dict[str, Any]:
    # v0 had no schema_version field; v1 is the same shape with the field.
    return dict(data)


# from_version -> function producing from_version + 1. Add one per schema bump.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {0: _v0_to_v1}

RECOVER_HINT = "inspect with: python3 -m anytime_engine.recover status"


def _schema(data: dict[str, Any]) -> int | None:
    v = data.get("schema_version", 0)
    if v is None:
        return 0
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def upgrade(source: Path, data: dict[str, Any], *, write: bool) -> dict[str, Any]:
    """Return `data` at the current schema, or raise StateSchemaTooNew."""
    v = _schema(data)
    if v == STATE_SCHEMA_VERSION:
        return data
    if v is None or v > STATE_SCHEMA_VERSION:
        raise StateSchemaTooNew(
            f"{source} has schema_version={data.get('schema_version')!r}; this engine "
            f"knows <= {STATE_SCHEMA_VERSION}. Not touching it (a newer engine wrote it, "
            f"or it is foreign). Upgrade the engine, or roll the state back from a "
            f"pre-migrate backup; {RECOVER_HINT}")
    if write:
        keep = source.with_name(f"{source.name}.pre-migrate-v{v}.{_stamp()}")
        shutil.copy2(source, keep)
        print(f"[state] migrating {source} v{v} -> v{STATE_SCHEMA_VERSION} "
              f"(backup: {keep})", file=sys.stderr)
    while v < STATE_SCHEMA_VERSION:
        data = MIGRATIONS[v](data)
        v += 1
    data["schema_version"] = STATE_SCHEMA_VERSION
    return data


def _restore(path: Path, reason: str, ref: datetime, *, write: bool) -> dict[str, Any]:
    gap_max = config.restore_max_gap_minutes()
    tried: list[str] = []
    for n in range(1, BACKUPS_KEPT + 1):
        b = backup_path(path, n)
        if not b.exists():
            continue
        gap = (ref - datetime.fromtimestamp(b.stat().st_mtime)).total_seconds() / 60
        if gap > gap_max:
            tried.append(f"prev.{n}: {gap:.0f} min older than the lost write (max {gap_max})")
            break  # older ones are older still
        try:
            data = upgrade(b, parse_json_file(b), write=write)
        except (CorruptStateFile, StateSchemaTooNew) as e:
            tried.append(f"prev.{n}: {e}")
            continue
        if write:
            quarantine_file(path, label="state", reason=reason)
        print(f"[state] {reason} — restored from {b.name} ({gap:.0f} min gap)", file=sys.stderr)
        return data
    detail = "; ".join(tried) or "no prev.N backup"
    raise StateUnavailable(f"{path}: {reason}; no usable backup ({detail}). "
                           f"Refusing to tick on an empty state; {RECOVER_HINT}")


def load_data(path: Path, *, write: bool = True,
              now: datetime | None = None) -> dict[str, Any] | None:
    """The state dict at the current schema; None on a genuine first run."""
    if path.exists():
        try:
            data = parse_json_file(path)
        except CorruptStateFile as e:
            ref = datetime.fromtimestamp(path.stat().st_mtime)
            return _restore(path, str(e), ref, write=write)
        return upgrade(path, data, write=write)
    if any(backup_path(path, n).exists() for n in range(1, BACKUPS_KEPT + 1)):
        return _restore(path, "state file missing but backups exist",
                        now or datetime.now(), write=write)
    return None
