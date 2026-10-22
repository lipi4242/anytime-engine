"""recover — the operator's way out of a fail-closed state.

    python3 -m anytime_engine.recover status          # what is there, what is usable
    python3 -m anytime_engine.recover restore 2       # prev.2 becomes the state
    python3 -m anytime_engine.recover reset --yes     # start empty (receipts kept)

Every action keeps what it replaces (quarantined to `.bak.<stamp>`), and the
receipts file is never touched: after a reset the concerns already marked done
still count as done, so no outbound action repeats.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime

from . import receipts
from .state import State, state_path
from .state_files import (BACKUPS_KEPT, CorruptStateFile, backup_path,
                          parse_json_file, quarantine_file)
from .state_load import StateSchemaTooNew, upgrade


def _describe(p) -> str:
    if not p.exists():
        return "missing"
    age = (datetime.now().timestamp() - p.stat().st_mtime) / 60
    try:
        upgrade(p, parse_json_file(p), write=False)
        verdict = "ok"
    except (CorruptStateFile, StateSchemaTooNew) as e:
        verdict = f"UNUSABLE: {e}"
    return f"{verdict} (written {age:.0f} min ago)"


def status() -> int:
    path = state_path()
    print(f"state    {path}: {_describe(path)}")
    for n in range(1, BACKUPS_KEPT + 1):
        print(f"prev.{n}   {_describe(backup_path(path, n))}")
    latest = receipts.latest()
    print(f"receipts {receipts.path()}: {len(latest)} concern(s) on record")
    return 0


def restore(n: int) -> int:
    path, src = state_path(), backup_path(state_path(), n)
    upgrade(src, parse_json_file(src), write=False)  # refuse an unusable backup
    quarantine_file(path, label="recover", reason=f"replaced by prev.{n}")
    shutil.copy2(src, path)
    print(f"restored {src.name} -> {path}")
    return 0


def reset() -> int:
    path = state_path()
    quarantine_file(path, label="recover", reason="operator reset")
    State().save()
    print(f"fresh state at {path}; {len(receipts.latest())} receipt(s) still count as done")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m anytime_engine.recover")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("status")
    r = sub.add_parser("restore")
    r.add_argument("n", type=int, choices=range(1, BACKUPS_KEPT + 1))
    z = sub.add_parser("reset")
    z.add_argument("--yes", action="store_true", required=True)
    args = p.parse_args(argv)
    if args.cmd == "restore":
        return restore(args.n)
    if args.cmd == "reset":
        return reset()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
