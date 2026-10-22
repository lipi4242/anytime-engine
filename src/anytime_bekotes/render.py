"""Plain-text output of `frissit`: the compact diff of `--begin` and the
per-source cursor lines of `--status`."""
from __future__ import annotations

from typing import Any

LIMIT = 30   # items per source in the compact diff; the rest as a number


def item(c: dict[str, Any]) -> str:
    kind = c["kind"]
    if kind == "commit":
        return f"commit {c['sha']} {c['subject']}"
    if kind in ("file", "memory"):
        return f"{c['status']} {c['path']}"
    if kind == "issue":
        return f"{c['identifier']} [{c.get('state')}] {c.get('title')} ({c.get('updatedAt')})"
    if kind == "live":
        return "az élő forrás tartalma változott"
    if kind == "resync":
        return "teljes újraolvasás kell (új vagy visszatért forrás, ismeretlen előző állapot)"
    return "HIBA: a forrás most nem olvasható (a kurzora marad)"


def diff_lines(biz: dict[str, Any], d: dict[str, Any], marked: int) -> list[str]:
    out = [f"## {biz.get('business')}"]
    by_src: dict[str, list[dict]] = {}
    paths = {s.get("name"): s.get("path") for s in biz.get("sources") or []}
    for c in d["changes"]:
        by_src.setdefault(c["source"], []).append(c)
    for name, items in by_src.items():
        head = d["next"]["sources"].get(name, {}).get("head")
        path = paths.get(name)
        out.append(f"### {name}" + (f" (repo {path}, HEAD {head})" if head else "")
                   + f" — {len(items)} változás")
        out += [f"- {item(c)}" for c in items[:LIMIT]]
        if len(items) > LIMIT:
            out.append(f"- … és még {len(items) - LIMIT}")
    if d["deleted"]:
        out.append(f"### törölt hivatkozások — {len(d['deleted'])} "
                   f"(elavultnak jelölt sor: {marked})")
        out += [f"- {r}" for r in d["deleted"][:LIMIT]]
        if len(d["deleted"]) > LIMIT:
            out.append(f"- … és még {len(d['deleted']) - LIMIT}")
    return out


def snapshot(snap: dict[str, Any]) -> str:
    if snap.get("state"):
        return snap["state"]
    if "head" in snap:
        return f"HEAD {snap['head']}"
    if "hashes" in snap:
        return f"{len(snap['hashes'])} fájl"
    if "items" in snap:
        return f"{len(snap['items'])} jegy, utolsó módosítás {snap.get('max')}"
    if "sha256" in snap:
        return f"sha256 {snap['sha256'][:12]}"
    return str(snap)
