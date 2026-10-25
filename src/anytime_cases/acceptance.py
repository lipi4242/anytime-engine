"""Before a message goes out: the brain's acceptance check for each agreement its items carry.

An item (a case, a todo, a CSV row) may carry `contract: <id>`, an agreement the USER approved
in the brain (mentat_contract.py). For every such id in a message, the executor writes what
would go out — the records of that contract's items and the whole message text — and runs

    python3 <repo>/.mentat/bin/mentat_accept.py --repo <repo> [--lang hu|en] [--part] <id> <file>

(`--part`: a single reminder is one part of the agreed set, so a missing record is not an
error; the morning summary is the whole set). Exit 0 = green; anything else, a missing
checker or a crash = red: the message is not sent, the USER gets one short note
(`delivered:accept_blocked:<key>`) and the message stays owed until it passes.
A message with no contract goes out as before; stderr says it was not checked.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import delivery

CHECKER = Path(".mentat") / "bin" / "mentat_accept.py"
NOTE = {"en": "{what} was not sent: the agreement check ({cid}) says\n{why}\n"
              "It goes out by itself once the data or the agreement is fixed.",
        "hu": "{what} nem ment ki, mert a megállapodás-ellenőrzés ({cid}) ezt mondja:\n{why}\n"
              "Magától kimegy, amint az adat vagy a megállapodás rendben van."}
MISSING = {"en": "the agreement checker {p} is not installed, so it cannot be checked",
           "hu": "a megállapodás-ellenőrző ({p}) nincs telepítve, így nem ellenőrizhető"}


def _record(o: dict[str, Any]) -> dict[str, Any]:
    return o.get("row") or {k: o.get(k) for k in ("title", "due_at", "next_action") if o.get(k) is not None}


def check(root: Path, cid: str, occs: list[dict[str, Any]], text: str, lang: str | None,
          part: bool) -> tuple[bool, str]:
    """(green, the checker's words)."""
    tool = root / CHECKER
    if not tool.is_file():
        return False, MISSING.get(lang or "en", MISSING["en"]).format(p=CHECKER.as_posix())
    doc = {"records": [_record(o) for o in occs if o.get("contract") == cid], "message": text}
    fd, path = tempfile.mkstemp(prefix="accept-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        argv = [sys.executable, str(tool), "--repo", str(root)] + (["--lang", lang] if lang in ("hu", "en") else [])
        r = subprocess.run(argv + (["--part"] if part else []) + [cid, path],
                           capture_output=True, text=True, timeout=60)
        words = (r.stdout.strip() or r.stderr.strip() or "exit %d" % r.returncode)
        return r.returncode == 0, words
    except (OSError, subprocess.SubprocessError) as e:
        return False, "the checker could not run: %s" % e
    finally:
        os.unlink(path)


def verdict(root: Path, occs: list[dict[str, Any]], text: str, lang: str | None,
            part: bool) -> tuple[str, list[tuple[str, bool, str]]]:
    """("unchecked" | "green" | "red", [(contract id, green, words)])."""
    cids = sorted({o["contract"] for o in occs if o.get("contract")})
    results = [(cid, *check(root, cid, occs, text, lang, part)) for cid in cids]
    if not results:
        return "unchecked", []
    return ("green" if all(ok for _, ok, _ in results) else "red"), results


def note(what: str, results, lang: str | None) -> str:
    cid, _, why = next(r for r in results if not r[1])
    return NOTE.get(lang or "en", NOTE["en"]).format(what=what, cid=cid, why=why) + "\n"


def allowed(root, lang, mark, text, occs, what, part, done, send, record) -> bool:
    """True: send it. False: blocked (the note is sent once, the message stays owed)."""
    status, results = verdict(root, occs, text, lang, part)
    if status == "unchecked":
        print(f"[deliver] {mark}: not checked: no agreement (contract) on its items", file=sys.stderr)
        return True
    for cid, ok, words in results:
        print(f"[deliver] {mark}: checked against {cid}: {words.splitlines()[0]}", file=sys.stderr)
    if status == "green":
        return True
    blocked = delivery.mark_name("accept_blocked:" + mark.removeprefix(delivery.mark_name("")))
    if blocked not in done:
        send(note(what, results, lang))
        record(blocked)
    return False


def preview_lines(root, lang, text, occs, part) -> list[str]:
    status, results = verdict(root, occs, text, lang, part)
    if status == "unchecked":
        return ["[check] not checked: no agreement on these items"]
    head = "[check] would be sent" if status == "green" else "[check] would NOT be sent"
    return [head] + [f"[check] checked against {cid}: {words}" for cid, _, words in results]
