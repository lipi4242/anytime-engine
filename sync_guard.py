#!/usr/bin/env python3
"""sync-to.sh's guard against overwriting a NEWER vendored engine.

The version string alone cannot tell: during development many commits carry
the same "0.3.0". So every sync records its source in the target —
`anytime_engine/.sync-source.json` {"version", "commit", "commit_date"} (from
the source checkout's git, else release.json) — and the next sync compares:

    record newer than this source            -> STOP (lists what would change)
    no usable record, same version, core differs -> STOP ("azonos verzió, eltérő
                                                 tartalom — újabb lehet")
    otherwise (incl. identical content)      -> go on

    sync_guard.py check  SRC_RELEASE TARGET_PKG     exit 1 = stop
    sync_guard.py record SRC_RELEASE TARGET_PKG     write the record
    sync_guard.py pack-ok SRC_RELEASE TARGET_PKG PACK   exit 1 = engine outside the pack's range
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RECORD = ".sync-source.json"


def _git(src: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(src), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def version_of(init: Path) -> str | None:
    try:
        return re.search(r'__version__ = "([^"]+)"', init.read_text())[1]
    except (OSError, TypeError):
        return None


def source_record(src: Path) -> dict:
    """The source checkout's identity; a non-git copy falls back to release.json."""
    rec = {"version": version_of(src / "src" / "anytime_engine" / "__init__.py"),
           "commit": None, "commit_date": None}
    if _git(src, "ls-files", "--error-unmatch", "sync-to.sh") is not None:
        out = _git(src, "log", "-1", "--format=%H%x00%cI")
        if out:
            rec["commit"], rec["commit_date"] = out.split("\0")
    else:
        try:
            rel = json.loads((src / "release.json").read_text())
            rec["commit_date"] = rel.get("date") or None
        except (OSError, ValueError):
            pass
    return rec


def changed_core(src: Path, pkg: Path) -> list[str]:
    """Core files the sync would add or change (module and test files)."""
    pairs = [(f, pkg / f.name) for f in sorted((src / "src" / "anytime_engine").glob("*.py"))]
    pairs += [(f, pkg / "tests" / f.name) for f in sorted((src / "tests").glob("*.py"))]
    return [dst.relative_to(pkg.parent).as_posix() for s, dst in pairs
            if not dst.is_file() or dst.read_bytes() != s.read_bytes()]


def _when(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def check(src: Path, pkg: Path) -> int:
    if not (pkg / "__init__.py").is_file():
        return 0                                    # nothing vendored yet
    changed = changed_core(src, pkg)
    if not changed:
        return 0                                    # same content: harmless
    here = source_record(src)
    try:
        had = json.loads((pkg / RECORD).read_text())
    except (OSError, ValueError):
        had = None
    then, now = _when((had or {}).get("commit_date")), _when(here["commit_date"])
    if then and now:
        try:
            newer = then > now
        except TypeError:                           # naive vs aware
            newer = then.replace(tzinfo=None) > now.replace(tzinfo=None)
        if not newer:
            return 0
        why = (f"a cél újabb forrásból jött ({had.get('commit_date')}, {had.get('commit')}); "
               f"ez a forrás: {here['commit_date']} ({here['commit']})")
    elif version_of(pkg / "__init__.py") == here["version"]:
        why = f"azonos verzió ({here['version']}), eltérő tartalom — újabb lehet"
    else:
        return 0                                    # a different version: the version gate decides
    print(f"ERROR: {why}. Nothing was changed. These files would change:", file=sys.stderr)
    for f in changed:
        print(f"  {f}", file=sys.stderr)
    print("Pass --allow-downgrade if you mean it, or --only-pack to add a pack only.",
          file=sys.stderr)
    return 1


def record(src: Path, pkg: Path) -> int:
    (pkg / RECORD).write_text(json.dumps(source_record(src), indent=2) + "\n")
    return 0


def pack_ok(src: Path, pkg: Path, pack: str) -> int:
    installed = version_of(pkg / "__init__.py")
    decl = re.search(r'"engine":\s*"([^"]+)"', (src / "src" / pack / "__init__.py").read_text())
    if installed is None or decl is None:
        print(f"ERROR: no installed engine in {pkg} (or {pack} declares no engine range)",
              file=sys.stderr)
        return 1
    sys.path.insert(0, str(src / "src"))
    from anytime_engine.versions import satisfies
    if not satisfies(installed, decl[1]):
        print(f"ERROR: {pack} needs engine {decl[1]}; installed is {installed}. Nothing was "
              "changed — sync the engine first.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    cmd, src, pkg, *rest = sys.argv[1:]
    fn = {"check": check, "record": record, "pack-ok": pack_ok}[cmd]
    raise SystemExit(fn(Path(src), Path(pkg), *rest))
