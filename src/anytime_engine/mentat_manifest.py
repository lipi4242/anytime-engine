"""mentat.json + .mentat/local.json — minimal reader/writer (LG1 contract).

VENDORED STOPGAP. The canonical `mentat_manifest.py` and its conformance
fixtures live in mentat-ai-bootstrap; replace this file with that one once
it is released (same function names on purpose).

Implements the parts the engine needs:
  rule 2  one writer at a time: exclusive fcntl.flock on .mentat/lock around
          read -> merge own key (unknown fields of the section kept) -> tmp+rename
  rule 3  committed paths are repo-relative (no absolute, no `..`)
  rule 6  schema newer than known -> SchemaTooNew: read for diagnostics only,
          never written
  rule 7  unknown keys are tolerated and preserved
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

SCHEMA = 1
LOCAL_SECTIONS = {"installed", "fleet", "admin"}   # these live in .mentat/local.json


class ManifestError(Exception):
    """Unreadable or invalid manifest."""


class SchemaTooNew(ManifestError):
    """Written for a newer contract: diagnostics only (rule 6)."""


def manifest_path(root: Path) -> Path:
    return Path(root) / "mentat.json"


def local_path(root: Path) -> Path:
    return Path(root) / ".mentat" / "local.json"


def _read(p: Path) -> dict[str, Any] | None:
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        raise ManifestError(f"{p}: unreadable ({e})") from e
    if not isinstance(data, dict):
        raise ManifestError(f"{p}: not a JSON object")
    schema = data.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool):
        raise ManifestError(f"{p}: missing or invalid 'schema'")
    if schema > SCHEMA:
        raise SchemaTooNew(f"{p}: schema {schema} is newer than {SCHEMA}; diagnostics only")
    return data


def load(root: Path) -> dict[str, Any] | None:
    """mentat.json, or None when the agent has none (standalone element)."""
    return _read(manifest_path(root))


def local(root: Path) -> dict[str, Any] | None:
    return _read(local_path(root))


def present(elem: str, root: Path) -> bool:
    m = load(root)
    return bool(m) and elem in (m.get("components") or {})


def check_relative(path: str) -> str:
    """Rule 3: a committed path is repo-relative and stays inside the repo."""
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or "\\" in path:
        raise ManifestError(f"path {path!r} must be repo-relative (no absolute, no '..')")
    return path


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    lock = Path(root) / ".mentat" / "lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def update(elem: str, section: str, data: Any, root: Path) -> dict[str, Any]:
    """Merge `data` into `<file>[section][elem]` under the lock and return the
    file. A dict merges (the section's other fields are kept), anything else
    replaces. mentat.json must already exist (the brain installer creates it,
    rule 1); local.json is created on first write."""
    is_local = section in LOCAL_SECTIONS
    p = local_path(root) if is_local else manifest_path(root)
    with _locked(root):
        doc = _read(p)
        if doc is None:
            if not is_local:
                raise ManifestError(f"{p} does not exist; the brain installer creates it")
            doc = {"schema": SCHEMA}
        sec = doc.setdefault(section, {})
        cur = sec.get(elem)
        sec[elem] = {**cur, **data} if isinstance(cur, dict) and isinstance(data, dict) else data
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, p)
    return doc
