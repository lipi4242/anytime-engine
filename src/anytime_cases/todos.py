"""Todos with a deadline count as one-off cases (read only).

`<brain>/todos/*.md` carry `type: todo`, `status: open | in-progress` and an
optional `due: YYYY-MM-DD` (the todo template). A todo WITHOUT `due` is not a
deadline and is left alone. One with a due date is read like a one-off case:
case_id `todo:<path>`, title from `title:` or the `**Feladat:**` line, next
step = that line. The file is never written: closing the todo (status: done)
is the agent's job, and a promoted todo (now a case) should be closed so it
is not counted twice.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from . import frontmatter

OPEN = ("open", "in-progress")
_TASK = re.compile(r"^\*\*(?:Feladat|Task):\*\*\s*(.+)$", re.M)


def load(root: Path, brain: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    folder = brain / "todos"
    todos, invalid = [], []
    for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if f.name.startswith("_"):
            continue
        rel = f.relative_to(root).as_posix()
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            invalid.append({"file": rel, "error": str(e)})
            continue
        try:
            fm = frontmatter.parse(text)
        except frontmatter.FrontmatterError as e:
            if re.search(r"^due:", text, re.M):   # a deadline we cannot read
                invalid.append({"file": rel, "error": str(e)})
            continue
        if fm.get("type") != "todo" or fm.get("status") not in OPEN or not fm.get("due"):
            continue
        try:
            date.fromisoformat(str(fm["due"])[:10])
        except ValueError:
            invalid.append({"file": rel, "error": f"due: {fm['due']!r} is not YYYY-MM-DD"})
            continue
        task = _TASK.search(text)
        task = task.group(1).strip() if task else None
        todos.append({
            "case_id": f"todo:{rel}", "ref": rel, "status": "open", "kind": "todo",
            "title": str(fm.get("title") or task or f.stem), "description": None,
            "next_action": task, "due_at": str(fm["due"])[:10], "recurrence": None,
            "anchor_at": None, "occurrences": None})
    return todos, invalid
