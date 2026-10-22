"""The cases pack's executor — renders, sends, and marks only what was confirmed.

    python3 -m anytime_engine.tick hourly --exec 'python3 -m anytime_cases.deliver'
    python3 -m anytime_engine.tick review --dry-run --now 2026-12-10T08:00 \\
        | python3 -m anytime_cases.deliver --preview     # the text, nothing sent
    python3 -m anytime_cases.deliver --find-chat [--save] # Telegram chat id -> .env

`anytime_engine.setup` records it as components.engine.exec, so a tick without
--exec runs it. The plan comes on stdin (or --plan FILE). Channel: mentat.json
components.engine.delivery.channel — `file` (default: <dir>/<date>.md, dir
default data/outbox) or `telegram` (telegram.py; held in quiet hours, quiet.py). Exit 1 when a send was not
confirmed: that tick does not land, and the message stays owed.
Other concerns in the plan are not this executor's; they are named on stderr.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from anytime_engine import config, engine_manifest, tick

from . import delivery, quiet, render, telegram

OWN = ("cases_morning", "cases_deadline")


def _settings() -> dict[str, Any]:
    return dict(engine_manifest.section().get("delivery") or {})


def _send(root: Path, cfg: dict[str, Any], day: str, text: str) -> None:
    if cfg.get("channel", "file") == "telegram":
        return telegram.send(root, text)
    out = root / str(cfg.get("dir") or "data/outbox") / f"{day}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    if text not in out.read_text(encoding="utf-8"):
        raise telegram.SendError(f"{out}: written text not found on read-back")


def _messages(action: dict[str, Any], day: str, lang: str | None,
              covered: set) -> list[tuple[str, str | None]]:
    """[(mark, text)] — text None: nothing (new) to say, the mark alone is the delivery."""
    ctx = action.get("context") or {}
    if action["concern"] == "cases_morning":
        due = ctx.get("cases.due") or {}
        if "error" in due:   # notice once a day; the morning itself stays owed
            return [(delivery.mark_name(f"cases_morning_error:{day}"),
                     render.unavailable(due["error"], lang))]
        return [(due["mark"], render.morning(due, lang))]
    return [(s["mark"], None if (s.get("case_id"), s.get("due_at")) in covered
             else render.signal(s, lang)) for s in ctx.get("cases.signals") or []]


def _listed(action: dict[str, Any]) -> set:
    """Occurrences a morning summary names: a signal for them in the same plan
    would say it twice, so it is marked without a second message."""
    due = (action.get("context") or {}).get("cases.due") or {}
    return {(o.get("case_id"), o.get("due_at"))
            for k in ("overdue", "today", "week") for o in due.get(k) or []}


def _mark(name: str) -> None:
    with contextlib.redirect_stdout(sys.stderr):
        tick.main(["--mark", name])


def run(plan: dict[str, Any], *, preview: bool = False) -> int:
    root = config.repo_root().resolve()
    cfg = _settings()
    day = str(plan.get("timestamp", ""))[:10]
    done, failed, covered = delivery.delivered(), 0, set()
    if (not preview and cfg.get("channel") == "telegram" and plan.get("timestamp")
            and quiet.is_quiet(engine_manifest.section().get("quiet_hours"),
                               datetime.fromisoformat(plan["timestamp"]))):
        print("[deliver] quiet hours: nothing sent, nothing marked — it goes out after "
              "the window", file=sys.stderr)
        return 0
    for action in sorted(plan.get("actions") or [],   # the morning first
                         key=lambda a: a.get("concern") != "cases_morning"):
        if action.get("concern") not in OWN:
            print(f"[deliver] not a cases action, left alone: {action.get('concern')}",
                  file=sys.stderr)
            continue
        for mark, text in _messages(action, day, cfg.get("lang"), covered):
            if preview:
                print(text or f"({mark}: nothing new to send)")
            elif mark not in done:
                try:
                    if text:
                        _send(root, cfg, day, text)
                except telegram.SendError as e:
                    print(f"[deliver] NOT sent ({mark}): {e}", file=sys.stderr)
                    failed += 1
                    continue
                _mark(mark)
            if action["concern"] == "cases_morning" and mark.startswith(
                    delivery.mark_name("cases_morning:")):
                covered |= _listed(action)   # said (or already said earlier today)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m anytime_cases.deliver")
    p.add_argument("--plan", help="plan JSON file (default: stdin)")
    p.add_argument("--preview", action="store_true", help="print the messages; send nothing")
    p.add_argument("--find-chat", action="store_true", help="list chats from the bridge events log")
    p.add_argument("--save", action="store_true", help="with --find-chat: write the chat id to .env")
    args = p.parse_args(argv)
    root = config.repo_root().resolve()
    if args.find_chat:
        try:
            chats = telegram.find_chats(root)
        except telegram.SendError as e:
            print(f"find-chat: {e}", file=sys.stderr)
            return 1
        for cid, name in chats:
            print(f"{cid}\t{name}")
        if not chats:
            print("no chat yet: send the bot any message, then run this again", file=sys.stderr)
            return 1
        if args.save and len(chats) == 1:
            telegram.save_chat(root, chats[0][0])
            print("TELEGRAM_CHAT_ID saved to .env")
        elif args.save:
            print("more than one chat: put the right one in .env as TELEGRAM_CHAT_ID", file=sys.stderr)
            return 1
        return 0
    if args.plan:
        text = Path(args.plan).read_text()
    else:
        text = "" if sys.stdin.isatty() else sys.stdin.read()
        if not text.strip() and os.environ.get("ANYTIME_PLAN_PATH"):
            text = Path(os.environ["ANYTIME_PLAN_PATH"]).read_text()
    return run(json.loads(text or "{}"), preview=args.preview)


if __name__ == "__main__":
    raise SystemExit(main())
