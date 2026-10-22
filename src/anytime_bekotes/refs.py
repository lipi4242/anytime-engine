"""The weekly full reconciliation: does every "(forrás: …)" citation in the
business map still resolve? Re-exported as `diff.unresolved_refs` (the
`frissit --advance` step reuses it).

    repo    the path exists at HEAD (`git cat-file -e HEAD:<path>`)
    memory  the file exists in the memory folder
    linear  the identifier is in the local export (only a complete one)
    a source not in bekotes.json is not ours to judge -> ignored; a blocked /
    unreachable source (or live / mail) cannot be checked -> kept; a line
    already marked " [elavult <day>]" is skipped (not re-reported weekly)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from anytime_engine import config as engine_config

from . import sources
from .config import source_path

CITATION = re.compile(r"\(forrás:\s*([^)]*)\)")
SKIP_DIRS = {"memoria"}


STALE = " [elavult "


def map_files(biz_dir: Path) -> list[Path]:
    """The business map's *.md files, the top-level memoria/ folder excluded."""
    return [p for p in sorted(Path(biz_dir).rglob("*.md"))
            if p.relative_to(biz_dir).parts[0] not in SKIP_DIRS]


def normalise(ref: str) -> str:
    """"web : ./a.md" -> "web:a.md" (the form the diff reports deletions in)."""
    name, _, target = ref.partition(":")
    target = target.strip()
    while target.startswith("./"):
        target = target[2:]
    return f"{name.strip()}:{target}"


def line_refs(line: str) -> list[str]:
    """The refs cited on one line ("," or ";" separate several in one citation)."""
    return [normalise(r) for m in CITATION.finditer(line)
            for r in (x.strip() for x in re.split(r"[;,]", m.group(1))) if ":" in r]


def read_map(p: Path) -> str | None:
    """A map file's text, or None (warned once) when it is not valid UTF-8 —
    citations and stale.mark skip the same files."""
    try:
        return p.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        engine_config.warn_once(f"bekotes-map:{p}", f"bekotes: {p} unreadable ({e}) — skipped")
        return None


def citations(biz_dir: Path) -> list[str]:
    """Every cited ref on a not-yet-stale line of the map, in order, once."""
    seen: list[str] = []
    for p in map_files(Path(biz_dir)):
        for line in (read_map(p) or "").splitlines():
            if STALE in line:
                continue
            seen += [r for r in line_refs(line) if r not in seen]
    return seen


def unresolved_refs(biz: dict[str, Any], root: Path | str) -> list[str]:
    root = Path(root)
    by_name = {s.get("name"): s for s in biz.get("sources") or []}
    checks: dict[str, Callable[[str], bool] | None] = {}
    out = []
    for ref in citations(Path(biz["dir"])):
        name, _, target = ref.partition(":")
        if name not in by_name:
            continue
        if name not in checks:
            checks[name] = _checker(by_name[name], root)
        check = checks[name]
        if check is not None and not check(target.strip()):
            out.append(ref)
    return out


def _checker(src: dict[str, Any], root: Path) -> Callable[[str], bool] | None:
    """A resolver for one source, or None when it cannot be checked now."""
    if sources.snapshot(src, root) == sources.BLOCKED:
        return None
    kind = src.get("kind")
    if kind == "repo":
        repo = source_path(src["path"], root)

        def in_head(path: str) -> bool:
            r = sources.git(repo, "cat-file", "-e", f"HEAD:{path}")
            return r is not None and r.returncode == 0
        return in_head
    if kind == "memory":
        folder = source_path(src["path"], root)
        return lambda f: (folder / f).is_file()
    if kind == "linear":
        doc = sources.linear_export(src, root)
        if not doc or doc.get("complete") is not True:
            return None     # a partial export cannot prove an issue is gone
        ids = set(sources.linear_snapshot(doc)["items"])
        return lambda ident: ident in ids
    return None
