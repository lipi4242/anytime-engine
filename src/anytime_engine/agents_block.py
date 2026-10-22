"""The engine's block at the end of the agent's AGENTS.md (written by `setup --install`).

Always in the agent's context, so it does not rediscover the engine every session:
how to get a given day's morning summary, where the summary really goes, which
timezone to speak in. Idempotent: replaces its own block, keeps everything else.
"""
from __future__ import annotations

from pathlib import Path

START, END = "<!-- anytime-engine:begin -->", "<!-- anytime-engine:end -->"


def text(data: dict) -> str:
    channel = (data.get("delivery") or {}).get("channel", "file")
    where = ("a file: data/outbox/<date>.md, not on Telegram (the user gets nothing on the phone)"
             if channel == "file" else "Telegram (TELEGRAM_CHAT_ID in .env)")
    return "\n".join([
        START,
        "## Engine: the morning summary",
        f"- It goes to {where}; say exactly that when asked.",
        "- A given day's summary: `python3 -m anytime_engine preview --at <YYYY-MM-DD>` "
        "(never assemble it by hand from cases or todos).",
        "- What the last tick saw and sent: `python3 -m anytime_engine last`; health: `... status`.",
        f"- Speak in the user's local time ({data.get('timezone')}); engine stamps carry an offset.",
        END,
    ])


def upsert(path: Path, block: str) -> str:
    """'written' | 'updated' | 'current'."""
    old = path.read_text() if path.exists() else ""
    if START in old and END in old:
        head, rest = old.split(START, 1)
        new = head + block + rest.split(END, 1)[1]
        state = "updated"
    else:
        new = old + ("" if not old or old.endswith("\n\n") else "\n" if old.endswith("\n") else "\n\n") + block + "\n"
        state = "written"
    if new == old:
        return "current"
    path.write_text(new)
    return state
