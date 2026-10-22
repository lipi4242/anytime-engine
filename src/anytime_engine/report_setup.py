"""The short report `anytime_engine.setup` prints (the full plan is --verbose)."""
from __future__ import annotations

import re
from datetime import timedelta

from . import clock


def summary(args, data: dict, selftest: str) -> list[str]:
    head = (f"setup {'done' if args.install else 'dry run (nothing written)'}: tz={args.tz}, "
            f"morning={args.morning}, delivery={args.deliver}/{args.lang}, "
            f"quiet={args.quiet_hours}")
    lines = [head, selftest]
    if args.verbose:
        lines.append(f"components.engine {'=' if args.install else 'would be'} {data}")
    return lines


def timer_line(args, captured: str) -> str:
    if args.cron:
        return "cron line:\n" + captured.strip()
    found = re.search(r"anytime-[^\s/]*-hourly\.timer", captured)
    timer = found.group(0) if found else "the hourly timer"
    enabled = next((l for l in captured.splitlines() if l.startswith("enabled ")), None)
    if args.install:
        return enabled or f"timer: unit files written ({timer}), not enabled"
    return f"timer: would install {timer} (hourly)"


def done(lines: list[str], args, rc: int) -> int:
    day = (clock.now() + timedelta(days=1)).date().isoformat()
    if not args.install:
        lines.append("next: re-run with --install (add --verbose for the full plan)")
    else:
        lines.append("headless box without a login session: loginctl enable-linger $USER")
    lines.append(f"then: python3 -m anytime_engine preview --at {day}   (tomorrow's message, "
                 "sends nothing) | python3 -m anytime_engine last")
    print("\n".join(lines))
    return rc
