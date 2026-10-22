"""verify — is the vendored engine what the sync wrote, and is it the only one?

    python3 -m anytime_engine.verify                 # from the consumer repo root
    python3 -m anytime_engine.verify --root . --pkg anytime_engine

Checks, exit 1 on any problem:
  1. `anytime_engine/VERSION` exists (written by sync-to.sh) and matches
     `__version__`;
  2. the content hash still matches — no hand edits, no half-finished sync;
  3. no OTHER engine copy lives in the repo: another `anytime_engine/` with a
     registry, or any directory holding both `registry.py` and `reducer.py`
     (a hand-rolled or older reducer). Two registries split the concerns
     silently (registry.find_foreign_registries catches it only at runtime).

`stamp(pkg)` writes VERSION; sync-to.sh calls it so the hash has one owner.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from . import __version__, config

UNHASHED = {"VERSION", "VENDORED.md"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".tox",
             "site-packages", "dist", "build", ".pytest_cache", ".mypy_cache"}


def content_hash(pkg: Path) -> str:
    h = hashlib.sha256()
    files = sorted(p for p in pkg.rglob("*") if p.is_file()
                   and p.name not in UNHASHED and p.suffix != ".pyc"
                   and not SKIP_DIRS.intersection(p.relative_to(pkg).parts))
    for p in files:
        h.update(p.relative_to(pkg).as_posix().encode() + b"\0")
        h.update(p.read_bytes() + b"\0")
    return h.hexdigest()


def stamp(pkg: Path, version: str = __version__) -> Path:
    out = Path(pkg) / "VERSION"
    out.write_text(f"version={version}\nsha256={content_hash(Path(pkg))}\n")
    return out


def read_stamp(pkg: Path) -> dict[str, str] | None:
    p = Path(pkg) / "VERSION"
    if not p.exists():
        return None
    return dict(line.split("=", 1) for line in p.read_text().splitlines() if "=" in line)


def other_copies(root: Path, own: Path) -> list[Path]:
    own, found = own.resolve(), []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        d, names = Path(dirpath), set(filenames)
        is_engine = d.name == "anytime_engine" and "registry.py" in names
        if (is_engine or {"registry.py", "reducer.py"} <= names) and d.resolve() != own:
            found.append(d)
    return sorted(found)


def problems(pkg: Path, root: Path) -> list[str]:
    out: list[str] = []
    st = read_stamp(pkg)
    if st is None:
        out.append(f"{pkg}: no VERSION — not a stamped vendored copy (pre-0.3 sync, or a "
                   f"hand copy); re-run sync-to.sh")
    else:
        if st.get("version") != __version__:
            out.append(f"VERSION says {st.get('version')}, the code says {__version__}")
        if st.get("sha256") != content_hash(pkg):
            out.append(f"{pkg}: content differs from the stamped {st.get('version')} — "
                       f"hand-edited or partially synced; fix upstream and re-sync")
    for d in other_copies(root, pkg):
        out.append(f"second engine copy: {d.relative_to(root).as_posix()} — keep ONE "
                   f"(make it a re-export shim of anytime_engine, or delete it)")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m anytime_engine.verify")
    p.add_argument("--pkg", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--root", type=Path, default=None,
                   help="repo to scan (default: ANYTIME_REPO_ROOT, else the cwd)")
    p.add_argument("--stamp", action="store_true", help="write VERSION for --pkg and exit")
    args = p.parse_args(argv)
    if args.stamp:
        print(f"stamped {stamp(args.pkg)}")
        return 0
    root = (args.root or config.repo_root()).resolve()
    found = problems(args.pkg.resolve(), root)
    for msg in found:
        print(f"PROBLEM: {msg}")
    if not found:
        print(f"ok: anytime-engine {__version__}, unmodified, the only copy in {root}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
