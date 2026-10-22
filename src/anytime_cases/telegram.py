"""Telegram channel — hands the text to the sub-etha bridge's send.mjs.

No Bot API call of our own: `node send.mjs --chat <id> --text-stdin` sends it
(and splits a long text). Keys (names fixed, values never printed):
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, from the environment or the agent
repo's `.env` (0600, gitignored). Where send.mjs lives: SUBETHA_SEND_MJS, else
~/.config/<SUBETHA_AGENT>/sub-etha/send.mjs; neither set -> SendError.

    python3 -m anytime_cases.deliver --find-chat [--save]
lists the chats in the bridge's events log (BRIDGE_STATE_DIR/telegram-inbox,
last 7 days; message the bot first) and, with --save, writes TELEGRAM_CHAT_ID
into .env.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .admin import _dotenv

TIMEOUT_S = 60
AGENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
UNSURE = "lehet, hogy kiment"
WHY = "anytime-engine gepi osszefoglalo (napi uzenet)"   # send.mjs length gate


class SendError(Exception):
    """Not confirmed: the message stays owed and the next tick retries it."""


def secret(root: Path, key: str) -> str | None:
    return os.environ.get(key) or _dotenv(root / ".env", key)


def _send_mjs(root: Path) -> str:
    explicit = secret(root, "SUBETHA_SEND_MJS")
    if explicit:
        return _checked(explicit)
    agent = secret(root, "SUBETHA_AGENT")
    if not agent:
        raise SendError("send.mjs location unknown: set SUBETHA_SEND_MJS "
                        "(or SUBETHA_AGENT) in the env or the repo .env")
    if not AGENT_RE.match(agent):
        raise SendError("SUBETHA_AGENT must match ^[a-z0-9][a-z0-9-]{0,63}$")
    return _checked(str(Path.home() / ".config" / agent / "sub-etha" / "send.mjs"))


def _checked(path: str) -> str:
    if not Path(path).is_file():
        raise SendError(f"send.mjs not found: {path}")
    return path


def send(root: Path, text: str) -> None:
    chat = secret(root, "TELEGRAM_CHAT_ID")
    if not chat:
        raise SendError("TELEGRAM_CHAT_ID is not set: message the bot, then run "
                        "`python3 -m anytime_cases.deliver --find-chat --save`")
    token = secret(root, "TELEGRAM_BOT_TOKEN")
    if not token:
        raise SendError("TELEGRAM_BOT_TOKEN is not set (env or the repo .env)")
    script = _send_mjs(root)
    node = shutil.which("node")
    if not node:
        raise SendError("node not found on PATH (send.mjs needs it)")
    cmd = [node, script, "--chat", chat, "--text-stdin", "--why", WHY]
    try:
        r = subprocess.run(cmd, input=text, text=True, encoding="utf-8",
                           capture_output=True, timeout=TIMEOUT_S,
                           env={**os.environ, "TELEGRAM_BOT_TOKEN": token})
    except subprocess.TimeoutExpired:
        raise SendError(f"send.mjs timeout after {TIMEOUT_S}s: bizonytalan, {UNSURE}") from None
    except OSError as e:
        raise SendError(f"send.mjs could not run: {str(e).replace(token, '***')}") from None
    if r.returncode in (0, 3):   # 3: sent, only the bridge's own log was not written
        return
    err = (r.stderr or "").replace(token, "***")[:300]
    note = f" (bizonytalan, {UNSURE})" if r.returncode == 5 else ""
    raise SendError(f"send.mjs exit {r.returncode}{note}: {err}")


def find_chats(root: Path, days: int = 7) -> list[tuple[str, str]]:
    base = secret(root, "BRIDGE_STATE_DIR")
    if not base:
        raise SendError("BRIDGE_STATE_DIR is not set: it points at the bridge's "
                        "state dir (telegram-inbox/events-*.jsonl)")
    inbox = Path(base) / "telegram-inbox"
    wanted = {f"events-{datetime.now(timezone.utc).date() - timedelta(days=i)}.jsonl" for i in range(days)}
    files = sorted(f for f in inbox.glob("events-*.jsonl") if f.name in wanted) \
        if inbox.is_dir() else []
    if not files:
        raise SendError(f"no bridge events log in {inbox} (BRIDGE_STATE_DIR) for the last {days} days")
    seen: dict[str, str] = {}
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                upd = json.loads(line)
            except ValueError:
                continue
            msg = (upd.get("message") or upd.get("channel_post") or {}) if isinstance(upd, dict) else {}
            chat = msg.get("chat") if isinstance(msg, dict) else None
            if isinstance(chat, dict) and "id" in chat:
                seen[str(chat["id"])] = chat.get("title") or chat.get("first_name") or "?"
    return list(seen.items())


def save_chat(root: Path, chat_id: str) -> None:
    env = root / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith("TELEGRAM_CHAT_ID=")]
    env.write_text("\n".join(lines + [f"TELEGRAM_CHAT_ID={chat_id}"]) + "\n")
    env.chmod(0o600)
