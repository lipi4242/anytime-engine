"""Create a case file in one command — no template to read, no ID to generate.

    python3 -m anytime_cases.new "Gázszámla" --due 2026-11-10 \\
        [--next "Átutalni"] [--description "..."] [--context "..."] \\
        [--recurrence monthly:10 --anchor 2026-11-10] [--status open|waiting] [--slug gazszamla]

Writes <brain>/cases/<slug>.md (case template frontmatter, a fresh ULID) and
prints the path. Refuses to overwrite; checks the dates before writing, so
what it writes is a case the pack can read.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

from anytime_engine import config

from . import due, source
from .recurrence import RecurrenceError

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(ALPHABET[(n >> 5 * i) & 31] for i in range(25, -1, -1))


def slugify(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "ugy"


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(a: argparse.Namespace, case_id: str) -> str:
    rows = [("type", "case"), ("case_id", case_id), ("title", _q(a.title)), ("status", a.status)]
    for key, val in (("description", a.description), ("next_action", a.next)):
        if val:
            rows.append((key, _q(val)))
    rows.append(("due_at", a.due))
    if a.recurrence:
        rows += [("recurrence", a.recurrence), ("anchor_at", a.anchor)]
    body = f"\n**Kontextus:** {a.context}\n" if a.context else ""
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in rows) + "---\n" + body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m anytime_cases.new", description=__doc__.split("\n")[0])
    p.add_argument("title")
    p.add_argument("--due", required=True, help="YYYY-MM-DD (first deadline)")
    p.add_argument("--next", help="the next step, one sentence")
    p.add_argument("--description")
    p.add_argument("--context")
    p.add_argument("--status", choices=("open", "waiting"), default="open")
    p.add_argument("--recurrence", help="e.g. monthly:10 (needs --anchor)")
    p.add_argument("--anchor", help="YYYY-MM-DD the series is counted from")
    p.add_argument("--slug")
    a = p.parse_args(argv)
    root = config.repo_root().resolve()
    try:
        date.fromisoformat(a.due)
        if a.recurrence and not a.anchor:
            raise ValueError("--recurrence needs --anchor")
        case_id = ulid()
        due.open_dates({"status": a.status, "due_at": a.due, "recurrence": a.recurrence,
                        "anchor_at": a.anchor, "occurrences": []}, date.fromisoformat(a.due))
        folder = source._brain_root(root) / "cases"
    except (ValueError, RecurrenceError, source.CasesUnavailable) as e:
        print(f"new: NOT written — {e}", file=sys.stderr)
        return 2
    target = folder / f"{a.slug or slugify(a.title)}.md"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as fh:
            fh.write(render(a, case_id))
    except FileExistsError:
        print(f"new: NOT written — {target.relative_to(root)} exists (pick --slug)", file=sys.stderr)
        return 2
    print(target.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
