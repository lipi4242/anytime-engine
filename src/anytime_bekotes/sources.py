"""Source snapshots — what the cursor remembers about each source.

    repo    {"head": sha}
    memory  {"hashes": {file: sha256}}          (files relative to the folder)
    linear  {"items": {identifier: updatedAt}, "max": iso}
    live    {"sha256": ...}
    other / declared blocked / unreachable  {"state": "blokkolt"}
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .config import source_path

BLOCKED = {"state": "blokkolt"}


def git(repo: Path, *args: str) -> subprocess.CompletedProcess | None:
    """`git -C repo ...`, or None when git itself cannot run."""
    try:
        return subprocess.run(["git", "-c", "log.showSignature=false", "-c", "color.ui=never",
                               "-C", str(repo), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def memory_files(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): _sha(p)
            for p in sorted(folder.rglob("*"))
            if p.is_file() and not any(part.startswith(".") for part in
                                       p.relative_to(folder).parts)}


def linear_export(src: dict[str, Any], root: Path) -> dict[str, Any] | None:
    """The local export {"exported_at", "complete", "issues": [...]}, or None."""
    try:
        doc = json.loads(source_path(src["export"], root).read_text())
    except (KeyError, OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("issues"), list):
        return None
    return doc


def issues(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The export's well-formed issues: dicts with a non-empty str identifier."""
    return [i for i in doc["issues"] if isinstance(i, dict)
            and isinstance(i.get("identifier"), str) and i["identifier"]]


def linear_snapshot(doc: dict[str, Any]) -> dict[str, Any]:
    items = {i["identifier"]: str(i.get("updatedAt") or "") for i in issues(doc)}
    return {"items": items, "max": max(items.values(), default=None)}


def blocked(src: dict[str, Any]) -> bool:
    """Declared blocked in bekotes.json, or a kind the pack cannot read."""
    return src.get("state") == "blokkolt" or src.get("kind") not in KINDS


def snapshot(src: dict[str, Any], root: Path) -> dict[str, Any]:
    if blocked(src):
        return dict(BLOCKED)
    try:
        return KINDS[src["kind"]](src, Path(root)) or dict(BLOCKED)
    except (KeyError, OSError):
        return dict(BLOCKED)


def _repo(src, root):
    r = git(source_path(src["path"], root), "rev-parse", "--verify", "HEAD")
    return {"head": r.stdout.strip()} if r is not None and r.returncode == 0 else None


def _memory(src, root):
    folder = source_path(src["path"], root)
    return {"hashes": memory_files(folder)} if folder.is_dir() else None


def _linear(src, root):
    doc = linear_export(src, root)
    return linear_snapshot(doc) if doc is not None else None


def _live(src, root):
    return {"sha256": _sha(source_path(src["path"], root))}


KINDS = {"repo": _repo, "memory": _memory, "linear": _linear, "live": _live}
