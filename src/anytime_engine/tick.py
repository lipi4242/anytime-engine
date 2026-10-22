"""tick — the engine-owned entry point a scheduler calls, and the fleet contract.

    python3 -m anytime_engine.tick hourly [--exec CMD] [--dry-run]
    python3 -m anytime_engine.tick --mark <concern>      # executor: "I did it"

One tick: validate -> load state -> reduce -> save -> hand the plan to the
executor -> ONLY THEN stamp. The stamps are the fleet contract:

  data/state/orchestrator-heartbeat.json   every non-dry tick (process alive)
  data/state/last-tick.json                scheduled triggers only (hourly/review)

Both are written after the work succeeded. A tick that fails validation, whose
executor exits non-zero, or that crashes, leaves the previous stamps untouched —
so fleet supervision sees it as missed, which is the truth. (Four consumers had
hand-written this with the stamp at the START of the tick; a tick that died
mid-work still looked landed.)

The engine never calls a model. `--exec CMD` is the agent's own command (a
headless agent run, a message into a live session, ...); it gets the plan JSON
on stdin and its path in ANYTIME_PLAN_PATH. Without --exec the tick only
decides: the plan is printed and written to data/state/last-plan.json.
With no --exec, a real tick uses mentat.json components.engine.exec (recorded
by `anytime_engine.setup`), so whoever schedules the tick — the engine's timer
or the fleet's — runs the same executor.

Without --exec the plan is printed as JSON; with --exec stdout is the executor's
log plus one summary line. `--dry-run` decides and prints but writes nothing — use it while setting up, so
the setup never consumes the first real tick.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import clock, config, heartbeat
from . import engine_manifest
from . import mentat_manifest as mm
from .plugins import PluginError
from .reducer import reduce
from .registry import discover, validate
from . import lasttick, receipts
from .state import State, StateUnavailable

SCHEDULED_TRIGGERS = frozenset({"hourly", "review"})
TRIGGERS = ("hourly", "review", "startup", "telegram", "webhook")

Executor = Callable[[dict[str, Any]], int]


class TickError(Exception):
    """The tick did not land; no stamp was written."""


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    os.replace(tmp, path)


def run_tick(trigger: str, *, executor: Executor | None = None,
             dry_run: bool = False, owner_token: str | None = None,
             now: datetime | None = None) -> dict[str, Any]:
    """Run one tick for already-registered concerns. Returns the plan.

    Raises TickError (registry invalid, executor non-zero) — or whatever the
    executor raised — and in every such case writes no stamp.
    """
    errors = validate()
    if errors:
        raise TickError("registry invalid: " + "; ".join(errors))

    try:
        state = State.load(migrate=not dry_run)
    except StateUnavailable as e:
        raise TickError(f"state unavailable, failing closed: {e}") from e
    plan = reduce(trigger, state, now=now)
    if dry_run:
        return plan

    # Recorded before the work on purpose: it is not a completion stamp, and the
    # executor may load+save state itself (mark_run) — we must not overwrite that.
    state.save()
    _atomic_write_json(config.plan_path(), plan)
    lasttick.write(plan)

    if executor is not None and plan["actions"]:
        rc = executor(plan)
        if rc != 0:
            raise TickError(f"executor exited {rc}; tick not stamped")

    # ── the work is done: now, and only now, stamp ──
    token = owner_token or heartbeat.current_owner_token() or heartbeat.generate_owner_token()
    heartbeat.write_heartbeat(token)
    if trigger in SCHEDULED_TRIGGERS:
        _atomic_write_json(config.last_tick_path(), {
            "trigger": trigger,
            "at": clock.stamp(),
            "actions": len(plan["actions"]),
        })
    return plan


def shell_executor(cmd: str) -> Executor:
    """Run `cmd` through the shell with the plan on stdin, from the repo root."""
    def run(plan: dict[str, Any]) -> int:
        env = dict(os.environ, ANYTIME_PLAN_PATH=str(config.plan_path()))
        payload = json.dumps(plan, ensure_ascii=False, default=str)
        return subprocess.run(cmd, shell=True, input=payload, text=True,
                              cwd=config.repo_root(), env=env).returncode
    return run


def _mark(names: list[str], result: str) -> int:
    """The receipt is written FIRST and is what counts: the work is done, so a
    broken state file must not make the executor believe it failed (and retry
    an outbound action). The state update is best effort on top."""
    try:
        state = State.load()
    except StateUnavailable as e:
        now = clock.now()
        for name in names:
            receipts.append(name, trigger=None, result=result, at=now)
        print(f"[tick] receipts recorded; state NOT updated ({e})", file=sys.stderr)
        return 0
    for name in names:
        state.mark_run(name, result)
    state.save()
    print(f"marked done: {', '.join(names)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m anytime_engine.tick",
                                description="Run one anytime-engine tick. (A day's message without ticking: "
                                            "python3 -m anytime_engine preview --at 2026-11-10)")
    p.add_argument("trigger", nargs="?", choices=TRIGGERS)
    p.add_argument("--exec", dest="exec_cmd", help="executor command (plan on stdin)")
    p.add_argument("--dry-run", "--print", action="store_true",
                   help="decide and print the plan; write no state and no stamp")
    p.add_argument("--now", nargs="?", const="now", metavar="ISO",
                   help="decide as of this time, in the agent's timezone (mentat.json "
                        "components.engine.timezone / ANYTIME_TZ). Bare --now: right now, "
                        "also for a real tick; a given time only with --dry-run")
    p.add_argument("--plugins", help="concern/provider packages (else ANYTIME_PLUGINS)")
    p.add_argument("--no-discover", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--mark", metavar="CONCERN", action="append",
                   help="record that the executor finished this concern (repeatable)")
    p.add_argument("--result", default="ok", help="result recorded with --mark")
    args = p.parse_args(argv)

    if args.mark:
        return _mark(args.mark, args.result)
    if not args.trigger:
        p.error("a trigger is required (or --mark CONCERN)")
    if args.now not in (None, "now") and not args.dry_run:
        p.error("--now <time> only with --dry-run: a real tick at a made-up time would "
                "stamp that day as done. For a real tick right now: bare --now")

    try:
        # mentat.json rule 6: a manifest we cannot read (or a newer schema)
        # means no tick at all — before any concern code is imported.
        exec_cmd = args.exec_cmd or (None if args.dry_run else
                                     engine_manifest.section().get("exec"))
        now = clock.parse(args.now) if args.now else None
        if not args.no_discover:
            plugins = [s.strip() for s in args.plugins.split(",")] if args.plugins else None
            discover(plugins)
    except (mm.ManifestError, PluginError, ValueError) as e:   # ClockError too
        print(f"[tick] NOT landed: {e}", file=sys.stderr)
        return 1
    executor = shell_executor(exec_cmd) if exec_cmd else None
    try:
        plan = run_tick(args.trigger, executor=executor, dry_run=args.dry_run, now=now)
    except TickError as e:
        print(f"[tick] NOT landed: {e}", file=sys.stderr)
        return 1
    if executor is None:
        print(json.dumps(plan, indent=2, ensure_ascii=False, default=str))
    else:   # stdout belongs to the executor's log; the plan is in last-plan.json
        print(f"[tick] {args.trigger} landed: {len(plan['actions'])} action(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
