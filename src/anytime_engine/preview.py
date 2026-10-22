"""preview — what will the tick say on a given day? One command, sends and writes nothing.

    python3 -m anytime_engine preview --at 2026-11-10            # that morning (07:00 or `morning`)
    python3 -m anytime_engine preview --at 2026-11-10T07:30      # as of that local time

It decides an hourly tick as of --at (a dry run: no state, no stamp, no outbox),
then lets the cases executor print its messages (`deliver --preview`). Without
the cases pack it prints the planned concerns instead.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from datetime import datetime

from . import clock, engine_manifest, mentat_manifest as mm, tick
from .plugins import PluginError
from .registry import all_concerns, discover


def _at(text: str) -> datetime:
    if "T" in text or " " in text.strip():
        return clock.parse(text.strip().replace(" ", "T"))
    hh, mm_ = (engine_manifest.section().get("morning") or "07:00").split(":")
    return clock.parse(text).replace(hour=int(hh), minute=int(mm_))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python3 -m anytime_engine preview",
        description="Show the message(s) the morning summary sends on a given day "
                    "(preview --at 2026-11-10): sends nothing, writes nothing.")
    p.add_argument("--at", required=True, metavar="DATE|ISO",
                   help="a day (the morning time of that day) or a local time, 2026-11-10T07:30")
    p.add_argument("--json", action="store_true", help="the plan as JSON instead of the messages")
    args = p.parse_args(argv)
    try:
        now = _at(args.at)
        if not all_concerns():   # a library caller may have loaded the packs already
            discover()
        with contextlib.redirect_stdout(io.StringIO()):   # the dry tick prints its plan
            plan = tick.run_tick("hourly", dry_run=True, now=now)
    except (mm.ManifestError, PluginError, tick.TickError, ValueError) as e:
        print(f"preview: NOT done — {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False, default=str))
        return 0
    when = now.strftime("%Y-%m-%d %H:%M")
    if not plan["actions"]:
        print(f"preview {when}: nothing is planned (before the morning time, or that "
              "morning is already delivered)")
        return 0
    try:
        from anytime_cases import deliver
    except ImportError:
        print(f"preview {when}: planned " + ", ".join(a["concern"] for a in plan["actions"]))
        return 0
    return deliver.run(plan, preview=True)


if __name__ == "__main__":
    raise SystemExit(main())
