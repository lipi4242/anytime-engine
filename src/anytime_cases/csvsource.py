"""Rows of a CSV with a deadline count as one-off cases (read only).

mentat.json `components.engine.csv_deadlines`, one entry per table:

    {"name": "tagdij", "path": "data/tagdij.csv", "key": "email", "title": "name",
     "due": "hatarido", "next": "teendo", "where": {"fizetve": "nem"}, "contract": "tagdij"}

`key`, `title`, `due` are column names (required); `next` is optional; `where` keeps the
rows whose columns equal the value (or one of a list). Each kept row is a case with id
`csv:<name>:<key value>`, its `row` (only the mapped columns, as written) and the optional
`contract` id that the executor checks before sending (acceptance.py). Dates: YYYY-MM-DD,
also YYYY.MM.DD. and YYYY/MM/DD. A missing file, a bad mapping or an unreadable date goes
to `invalid`, the rest still count. The file is never written.
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Any

from anytime_engine import engine_manifest, mentat_manifest as mm

REQUIRED = ("name", "path", "key", "title", "due")
_DAY = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})\.?$")


def day(raw: str) -> str | None:
    m = _DAY.match((raw or "").strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return None


def _keep(row: dict[str, str], where: dict[str, Any]) -> bool:
    return all(row.get(k, "").strip() in ([str(x) for x in v] if isinstance(v, list) else [str(v)])
               for k, v in where.items())


def _table(root: Path, src: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rel = mm.check_relative(str(src["path"]))
    try:
        with (root / rel).open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        return [], [{"file": rel, "error": str(e)}]
    cols = [src[c] for c in ("key", "title", "due", "next") if src.get(c)]
    items, invalid = [], []
    for n, row in enumerate(rows, start=2):   # line 1 is the header
        row = {k: (v or "").strip() for k, v in row.items() if k is not None}
        if not _keep(row, src.get("where") or {}):
            continue
        when = day(row.get(src["due"], ""))
        if when is None:
            invalid.append({"file": f"{rel}:{n}", "error": f"{src['due']}: {row.get(src['due'], '')!r} is not a date"})
            continue
        items.append({
            "case_id": f"csv:{src['name']}:{row.get(src['key'], n)}", "ref": f"{rel}:{n}", "status": "open",
            "kind": "csv", "title": row.get(src["title"]) or f"{rel}:{n}", "description": None,
            "next_action": (row.get(src["next"]) or None) if src.get("next") else None, "due_at": when,
            "recurrence": None, "anchor_at": None, "occurrences": None,
            "row": {c: row.get(c, "") for c in cols}, "contract": src.get("contract")})
    return items, invalid


def load(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    raw = engine_manifest.section(root).get("csv_deadlines") or []
    items, invalid = [], []
    for i, src in enumerate(raw if isinstance(raw, list) else [raw]):
        where = f"components.engine.csv_deadlines[{i}]"
        if not isinstance(src, dict) or not all(src.get(k) for k in REQUIRED):
            invalid.append({"file": where, "error": "needs %s" % ", ".join(REQUIRED)})
            continue
        try:
            got, bad = _table(root, src)
        except mm.ManifestError as e:
            got, bad = [], [{"file": where, "error": str(e)}]
        items += got
        invalid += bad
    return items, invalid
