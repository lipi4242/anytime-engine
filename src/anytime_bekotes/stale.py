"""Deterministic stale marking: a line of the business map that cites a deleted
ref gets " [elavult <day>]" at its end — once (a marked line is never marked
again, and refs.citations no longer reports it).

    stale.mark(biz_dir, refs, day) -> number of lines marked

memoria/ is not part of the map and is never touched; a file that is not
valid UTF-8 is left alone rather than rewritten with replacement characters.
The rewrite is atomic (tmp + os.replace).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable

from .refs import STALE, line_refs, map_files, read_map


def mark(biz_dir: str | Path, refs: Iterable[str], day: str) -> int:
    wanted, total = set(refs), 0
    if not wanted:
        return 0
    for p in map_files(Path(biz_dir)):
        text = read_map(p)
        if text is None:
            continue
        lines = text.splitlines(keepends=True)
        n = 0
        for i, line in enumerate(lines):
            body = line.rstrip("\r\n")
            if STALE in body or not wanted.intersection(line_refs(body)):
                continue
            lines[i] = f"{body}{STALE}{day}]{line[len(body):]}"
            n += 1
        if n:
            _write(p, "".join(lines).encode("utf-8"))
            total += n
    return total


def _write(p: Path, data: bytes) -> None:
    """tmp in the same folder + os.replace: a failed write leaves the map intact."""
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}-", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
