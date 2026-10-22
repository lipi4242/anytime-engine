"""lasttick — a short, readable record of what the last tick looked at.

    python3 -m anytime_engine last          # what did the last tick find?
    python3 -m anytime_engine last --json

Every real (non-dry) tick writes data/state/last-summary.json from the plan it
decided: per planned concern what its context held (counts, the first titles,
errors), and per skipped concern why. It is a record, not state: the engine
never reads it back, and a failure to write it never fails the tick.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import config

TITLES = 5


def path() -> Path:
    return config.last_tick_path().with_name("last-summary.json")


def _titles(items: list[Any]) -> list[str]:
    out = []
    for i in items:
        name = isinstance(i, dict) and (i.get("title") or i.get("file"))
        if name:
            out.append(f"{name} ({i['due_at']})" if i.get("due_at") else str(name))
    return out[:TITLES]


def _read(value: Any) -> dict[str, Any]:
    """What one provider handed the concern: counts + a few titles; never the bodies."""
    if isinstance(value, dict) and "error" in value:
        return {"error": str(value["error"])}
    if isinstance(value, list):
        return {"items": len(value), "titles": _titles(value)}
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {k: value[k] for k in ("backend", "as_of", "scanned") if value.get(k)}
    for k, v in value.items():
        if isinstance(v, list):
            out[k] = {"count": len(v), "titles": _titles(v)}
    return out


def build(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "at": plan.get("timestamp"), "trigger": plan.get("trigger"),
        "planned": [{"concern": a["concern"], "read": {k: _read(v) for k, v in
                                                       (a.get("context") or {}).items()}}
                    for a in plan.get("actions", [])],
        "skipped": plan.get("skip_reasons") or {},
        "errors": plan.get("context_errors") or [],
    }


def write(plan: dict[str, Any]) -> None:
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(build(plan), indent=2, ensure_ascii=False, default=str))
        os.replace(tmp, p)
    except OSError as e:   # a record only: never fails the tick
        print(f"[tick] summary not written: {e}", file=sys.stderr)


def _line(name: str, r: dict[str, Any]) -> str:
    if "error" in r:
        return f"  {name}: ERROR {r['error']}"
    if "items" in r:
        return f"  {name}: {r['items']} item(s)" + (" — " + "; ".join(r["titles"]) if r["titles"] else "")
    parts = []
    for k, v in r.items():
        if isinstance(v, dict) and "count" in v:
            parts.append(f"{k} {v['count']}" + (" [" + "; ".join(v["titles"]) + "]" if v["titles"] else ""))
        elif k == "scanned":
            parts.append("read " + ", ".join(f"{n} {w}" for w, n in v.items()))
        elif k == "backend":
            parts.append(f"backend {v}")
    return f"  {name}: " + (", ".join(parts) or "-")


def render(s: dict[str, Any]) -> str:
    lines = [f"Last tick: {s.get('trigger')} at {s.get('at')}"]
    if not s["planned"]:
        lines.append("Planned: nothing")
    for a in s["planned"]:
        lines.append(f"Planned: {a['concern']}")
        lines += [_line(k, v) for k, v in a["read"].items()]
    for name, why in s["skipped"].items():
        lines.append(f"Skipped: {name} — {why}")
    for e in s["errors"]:
        lines.append(f"Degraded: {e}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m anytime_engine last",
                                description="What did the last tick find?")
    p.add_argument("--json", action="store_true", help="the raw record")
    args = p.parse_args(argv)
    try:
        s = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("No tick has run here yet (a dry run writes nothing).", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"last: the record is unreadable — {e}", file=sys.stderr)
        return 1
    print(json.dumps(s, indent=2, ensure_ascii=False) if args.json else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
