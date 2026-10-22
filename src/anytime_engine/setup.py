"""setup — everything after `sync-to.sh`, in one command (a dry run unless --install).

    python3 -m anytime_engine.setup --tz Europe/Budapest [--morning 07:00]
        [--deliver file|telegram] [--lang en|hu] [--install] [--cron] [--verbose]

Prints ~8 lines (what was recorded, selftest, timer, next step); --verbose adds the
settings and the full unit files. A refusal or a red selftest is printed whole.

1. checks the timezone exists (ask the user; never assume the box's UTC)
2. telegram: needs Node.js on PATH; checks TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (env or the repo .env;
   names only, never values) — `python3 -m anytime_cases.deliver --find-chat --save`;
   --quiet-hours (default 22:00-07:00, or off): no Telegram message in that window
3. runs the selftest
4. records timezone, morning, delivery and the executor in mentat.json
   components.engine (with --install)
5. installs the hourly timer (schedule.py) — unless the fleet owns the schedule:
   then the fleet's tick picks up the recorded executor by itself

The morning summary goes out on the first tick at/after `morning` in `--tz`;
the default channel is a file (data/outbox/<date>.md).
"""
from __future__ import annotations

import argparse
import shutil
import contextlib
import io
import subprocess
import sys

from . import agents_block, config, engine_manifest as em, mentat_manifest as mm, report_setup as report, schedule, clock

CASES = "anytime_cases"
DELIVER = "python3 -m anytime_cases.deliver"


def _missing_telegram_keys() -> list[str]:
    from anytime_cases import telegram   # the pack's own lookup: env, then the repo .env
    return [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
            if not telegram.secret(em.root(), k)]


def _quiet_ok(raw: str) -> None:
    import importlib
    try:
        importlib.import_module("anytime_cases.quiet").parse(raw)
    except ImportError:   # no cases pack: nothing sends to a phone
        pass


def _settings(args, plugins: list[str]) -> dict:
    data = {"timezone": args.tz, "morning": args.morning,
            "delivery": {"channel": args.deliver, "lang": args.lang},
            "quiet_hours": args.quiet_hours}
    if CASES in plugins:
        data["exec"] = DELIVER
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m anytime_engine.setup",
                                description="Install the engine's schedule and delivery.")
    p.add_argument("--tz", required=True, help="IANA timezone of the user, e.g. Europe/Budapest")
    p.add_argument("--morning", default="07:00", help="local time of the morning summary")
    p.add_argument("--deliver", choices=("file", "telegram"), default="file")
    p.add_argument("--lang", choices=("en", "hu"), default="en")
    p.add_argument("--quiet-hours", default="22:00-07:00",
                   help="local HH:MM-HH:MM when no Telegram message goes out, or off")
    p.add_argument("--install", action="store_true", help="record + install (else: dry run)")
    p.add_argument("--cron", action="store_true", help="a crontab line instead of systemd")
    p.add_argument("--verbose", action="store_true", help="also print the settings and the schedule plan")
    p.add_argument("--unit-dir", default=None, help=argparse.SUPPRESS)
    p.add_argument("--no-enable", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--no-selftest", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    def refuse(msg: str) -> int:
        print(f"setup: NOT done — {msg}", file=sys.stderr)
        return 2

    try:
        clock.zone(args.tz)
        _quiet_ok(args.quiet_hours)
        if mm.load(em.root()) is None:
            return refuse("no mentat.json here: run from the agent repo (the brain creates it)")
        plugins, owner = em.plugins(), em.schedule_owner()
    except (ValueError, mm.ManifestError) as e:   # ClockError is a ValueError
        return refuse(str(e))
    if not plugins:
        return refuse("components.engine.plugins is empty: sync with --pack cases, "
                      "or list your own concern package")
    if args.deliver == "telegram":
        missing = _missing_telegram_keys() if CASES in plugins else ["the anytime_cases pack"]
        if missing:
            return refuse(f"telegram needs {', '.join(missing)} first: put the bot token in "
                          ".env, message the bot once, then run "
                          "`python3 -m anytime_cases.deliver --find-chat --save`")
        if not shutil.which("node"):
            return refuse("the telegram channel needs Node.js >= 20 (the sub-etha send.mjs "
                          "runs on it): install it, or use --deliver file")
    selftest = "selftest: skipped"
    if not args.no_selftest:
        r = subprocess.run([sys.executable, "-m", "anytime_engine.selftest"],
                           cwd=config.repo_root(), capture_output=True, text=True)
        if r.returncode != 0:   # the failing tests, whole: names, reasons, rerun commands
            return refuse("the selftest is not green:\n" + (r.stdout + r.stderr).rstrip())
        selftest = (r.stdout.strip().splitlines() or ["selftest: OK"])[-1].split(" (")[0]

    data = _settings(args, plugins)
    if args.install:
        em.record_settings(data)
        agents = agents_block.upsert(em.root() / "AGENTS.md", agents_block.text(data))
    sched = ["--plugins", ",".join(plugins)] + (["--cron"] if args.cron else [])
    sched += ["--install"] if args.install and not args.cron else []
    sched += ["--unit-dir", args.unit_dir] if args.unit_dir else []
    sched += ["--no-enable"] if args.no_enable else []
    lines = report.summary(args, data, selftest)
    if args.install:
        lines.append(f"AGENTS.md engine block: {agents}")
    if owner == "fleet":
        lines.append("schedule: the fleet runs this agent's tick (components.engine.exec); "
                     "no engine timer installed")
        return report.done(lines, args, 0)
    cap_out, cap_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(cap_out), contextlib.redirect_stderr(cap_err):
        rc = schedule.main(sched)
    captured = cap_out.getvalue() + cap_err.getvalue()
    if rc != 0:   # an error is shown whole
        print("\n".join(lines) + "\n" + captured.rstrip(), file=sys.stderr)
        return rc
    lines.append(report.timer_line(args, captured))
    if args.verbose:
        lines.append(captured.rstrip())
    return report.done(lines, args, 0)


if __name__ == "__main__":
    raise SystemExit(main())
