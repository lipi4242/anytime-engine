"""`python3 -m anytime_engine <command>` — the short way to the engine's commands."""
from __future__ import annotations

import importlib
import sys

COMMANDS = {"last": "lasttick", "status": "status", "tick": "tick", "setup": "setup",
            "selftest": "selftest", "verify": "verify", "preview": "preview"}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print("usage: python3 -m anytime_engine {" + "|".join(COMMANDS) + "} [args]\n"
              "  last      what did the last tick find?\n"
              "  preview   the morning message on a given day: preview --at 2026-11-10", file=sys.stderr)
        return 2
    return int(importlib.import_module(f"anytime_engine.{COMMANDS[argv[0]]}").main(argv[1:]) or 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
