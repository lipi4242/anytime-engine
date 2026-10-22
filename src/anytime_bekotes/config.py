"""Where the businesses are: `components.brain.root` in mentat.json, then every
`<brain root>/business/*/bekotes.json` (written and committed by the brain).

    {"schema": 1, "business": "zoldag",
     "sources": [{"name", "kind": "repo|memory|linear|live|mail",
                  "path" | "export", "team"?, "state"?, "reason"?}]}

Source paths are repo-relative or start with "~/".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anytime_engine import config as engine_config
from anytime_engine import mentat_manifest as mm


def brain_root(root: Path) -> Path | None:
    """The brain folder, or None (no mentat.json / no brain component)."""
    doc = mm.load(root)
    brain = (((doc or {}).get("components") or {}).get("brain") or {}).get("root")
    return Path(root) / mm.check_relative(str(brain)) if brain else None


def businesses(root: Path) -> list[dict[str, Any]]:
    """Every readable bekotes.json, sorted by folder, each with its `dir`."""
    brain = brain_root(Path(root))
    if brain is None:
        return []
    out = []
    for p in sorted((brain / "business").glob("*/bekotes.json")):
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            engine_config.warn_once(f"bekotes:{p}", f"bekotes: {p} unreadable ({e}) — skipped")
            continue
        if not isinstance(data, dict) or data.get("schema") != 1:
            engine_config.warn_once(f"bekotes:{p}", f"bekotes: {p} has no schema 1 — skipped")
            continue
        out.append({**data, "sources": _valid_sources(p, data.get("sources")),
                    "dir": str(p.parent)})
    return out


def _valid_sources(p: Path, raw: Any) -> list[dict[str, Any]]:
    """Only dicts with a str name and kind; anything else is skipped, warned once."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        engine_config.warn_once(f"bekotes-src:{p}", f"bekotes: {p} sources is not a list — ignored")
        return []
    ok = [s for s in raw if isinstance(s, dict) and isinstance(s.get("name"), str)
          and isinstance(s.get("kind"), str)]
    if len(ok) != len(raw):
        engine_config.warn_once(f"bekotes-src:{p}",
                                f"bekotes: {p} has {len(raw) - len(ok)} invalid source(s) "
                                "(need a str name and kind) — skipped")
    return ok


def source_path(value: str, root: Path) -> Path:
    """A source path from bekotes.json: "~/..." -> home, else repo-relative."""
    return Path(value).expanduser() if value.startswith("~/") else Path(root) / value
