"""Where the cases come from: `mentat.json` `cases.backend`.

    markdown (default)  <brain root>/cases/*.md frontmatter (the case template)
    admin               the admin API (admin.py: the due window, computed by the admin)

A chosen admin that is not connected or not reachable raises CasesUnavailable;
there is no fall-back to the markdown files (mentat.json rule 4: two writers
must not exist, and a stale copy must not pass for the truth).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from anytime_engine import mentat_manifest as mm

from . import frontmatter, todos

FIELDS = ("title", "description", "status", "next_action", "due_at",
          "recurrence", "anchor_at", "occurrences")


class CasesUnavailable(Exception):
    """The chosen backend cannot be read: the answer is unknown, not empty."""


def backend(root: Path) -> str:
    doc = mm.load(root) or {}
    return str((doc.get("cases") or {}).get("backend") or "markdown")


def load(root: Path) -> tuple[str, list[dict[str, Any]], list[dict[str, str]]]:
    """(backend, cases, invalid). Each case: case_id, ref and FIELDS."""
    name = backend(root)
    if name == "markdown":
        cases, invalid = _markdown(root)
        return name, cases, invalid
    if name == "admin":   # read occurrence by occurrence: due.py -> admin.fetch
        raise CasesUnavailable("the admin backend is read through admin.fetch, not as case files")
    raise CasesUnavailable(f"unknown cases.backend {name!r} (markdown | admin)")


def _normal(raw: dict[str, Any], case_id: Any, ref: Any) -> dict[str, Any]:
    out = {k: raw.get(k) for k in FIELDS}
    # waiting_on left the case model (status waiting + next_action says it);
    # an older file's value still names what we wait for.
    if not out["next_action"] and raw.get("waiting_on"):
        out["next_action"] = str(raw["waiting_on"])
    out.update(case_id=str(case_id) if case_id else None, ref=ref)
    return out


def _brain_root(root: Path) -> Path:
    doc = mm.load(root)
    brain = (((doc or {}).get("components") or {}).get("brain") or {}).get("root")
    if not brain:
        raise CasesUnavailable("markdown cases need components.brain.root in mentat.json")
    return root / mm.check_relative(str(brain))


def _markdown(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    brain = _brain_root(root)
    folder = brain / "cases"
    cases, invalid = [], []
    for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if f.name.startswith("_"):
            continue
        rel = f.relative_to(root).as_posix()
        try:
            fm = frontmatter.parse(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, frontmatter.FrontmatterError) as e:
            invalid.append({"file": rel, "error": str(e)})
            continue
        if fm.get("type") == "case":
            cases.append(_normal(fm, fm.get("case_id") or rel, rel))
    deadline_todos, bad = todos.load(root, brain)   # todos with a due date, read only
    return cases + deadline_todos, invalid + bad
