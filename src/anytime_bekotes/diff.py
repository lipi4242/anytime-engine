"""What changed in a business's sources since its cursor — pure, writes nothing.

compute(biz, root, now, weekly=None) -> {"baseline", "empty", "changes",
                                          "deleted", "next", "weekly"}

    repo    one {"kind": "commit", "sha", "subject"} per commit <head>..HEAD
            + end-state {"kind": "file", "status", "path"} (git diff -M; a
            rename = old D + new A); a deleted file -> "<source>:<path>";
            an unknown old head (force-push) -> one {"kind": "resync"}
    memory  {"kind": "memory", "path", "status"}; a vanished file -> deleted
    linear  every issue whose identifier is new or whose updatedAt differs;
            a vanished identifier -> deleted only when the export is complete
    live    {"kind": "live"} when the hash differs
    error   an unreachable source: {"kind": "error"}, its cursor entry kept

No cursor -> baseline (no changes; `next` is the snapshot to save). The full
reconciliation (every "(forrás: …)" citation must still resolve; the rest goes
to `deleted`) runs when the `weekly` stamp {"at", "ok", "unresolved"} says it
is due: none yet, 7 days after a clean one, the next day after a failed one.
A stamp taken at this very instant is reused (should_run is evaluated more
than once per reduction). A new stamp is returned as "weekly" (else None).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from . import cursor, sources
from .config import source_path
from .refs import unresolved_refs
from .weekly import weekly_due

__all__ = ["compute", "actionable", "unresolved_refs"]


def compute(biz: dict[str, Any], root: Path | str, now: datetime,
            weekly: dict[str, Any] | None = None) -> dict[str, Any]:
    root, cur, stamp = Path(root), cursor.load(biz["dir"]), None
    nxt = {"schema": 1, "sources": {}, "advanced_at": now.isoformat()}
    changes: list[dict] = []
    deleted: list[str] = []
    for src in biz.get("sources") or []:
        name, snap = src["name"], sources.snapshot(src, root)
        old = (cur or {}).get("sources", {}).get(name)
        nxt["sources"][name] = snap
        if cur is None:
            continue
        if snap == sources.BLOCKED:
            if not sources.blocked(src):
                changes.append({"source": name, "kind": "error"})
            nxt["sources"][name] = old if old is not None else snap
            continue
        if not old or old == sources.BLOCKED:
            changes.append({"source": name, "kind": "resync"})
            continue
        ch, de, nxt["sources"][name] = _DIFFS[src["kind"]](name, src, old, snap, root)
        changes += ch
        deleted += de
    if cur is not None:
        if isinstance(weekly, dict) and weekly.get("at") == now.isoformat():
            refs = list(weekly.get("unresolved") or [])
        elif weekly_due(weekly, now):
            refs = unresolved_refs(biz, root)
            stamp = {"at": now.isoformat(), "ok": not refs, "unresolved": refs}
        else:
            refs = []
        deleted += [r for r in refs if r not in deleted]
    return {"baseline": cur is None, "empty": not changes and not deleted,
            "changes": changes, "deleted": deleted, "next": nxt, "weekly": stamp}


def actionable(d: dict[str, Any]) -> bool:
    """Worth an LLM run: a deletion, or a change other than an unreachable source."""
    return bool(d["deleted"]) or any(c["kind"] != "error" for c in d["changes"])


def _repo(name, src, old, snap, root):
    repo, a, b = source_path(src["path"], root), old.get("head"), snap["head"]
    if a == b:
        return [], [], snap
    known = sources.git(repo, "cat-file", "-e", f"{a}^{{commit}}") if a else None
    if known is None or known.returncode:
        return [{"source": name, "kind": "resync"}], [], snap
    log = sources.git(repo, "log", "--reverse", "--format=%H%x00%s", f"{a}..{b}")
    ns = sources.git(repo, "diff", "--name-status", "-z", "-M", a, b)
    if log is None or ns is None or log.returncode or ns.returncode:
        return [{"source": name, "kind": "error"}], [], old
    changes = [{"source": name, "kind": "commit", "sha": sha, "subject": subject}
               for sha, _, subject in (ln.partition("\0") for ln in log.stdout.splitlines())]
    deleted = []
    for status, path in _name_status(ns.stdout):
        changes.append({"source": name, "kind": "file", "status": status, "path": path})
        if status == "D":
            deleted.append(f"{name}:{path}")
    return changes, deleted, snap


def _name_status(out: str) -> list[tuple[str, str]]:
    """`git diff --name-status -z -M` -> [(status, path)]; a rename = D old + A new."""
    toks, out_l, i = out.split("\0"), [], 0
    while i < len(toks) and toks[i]:
        st = toks[i]
        if st[0] in "RC":
            if st[0] == "R":
                out_l.append(("D", toks[i + 1]))
            out_l.append(("A", toks[i + 2]))
            i += 3
        else:
            out_l.append((st[0], toks[i + 1]))
            i += 2
    return out_l


def _memory(name, src, old, snap, root):
    was, now_h = old.get("hashes") or {}, snap["hashes"]
    changes = [{"source": name, "kind": "memory", "path": f,
                "status": "M" if f in was else "A"}
               for f, h in now_h.items() if was.get(f) != h]
    return changes, [f"{name}:{f}" for f in was if f not in now_h], snap


def _linear(name, src, old, snap, root):
    doc = sources.linear_export(src, root)
    if doc is None:
        return [{"source": name, "kind": "error"}], [], old
    snap, was = sources.linear_snapshot(doc), old.get("items") or {}
    changes = [{"source": name, "kind": "issue", "identifier": i["identifier"],
                "title": i.get("title"), "state": i.get("state"),
                "updatedAt": i.get("updatedAt")}
               for i in sources.issues(doc)
               if was.get(i["identifier"]) != str(i.get("updatedAt") or "")]
    if doc.get("complete") is True:
        return changes, [f"{name}:{i}" for i in was if i not in snap["items"]], snap
    items = {**was, **snap["items"]}   # a partial export never forgets a seen issue
    return changes, [], {"items": items, "max": max(items.values(), default=None)}


def _live(name, src, old, snap, root):
    same = old.get("sha256") == snap["sha256"]
    return ([] if same else [{"source": name, "kind": "live"}]), [], snap


_DIFFS = {"repo": _repo, "memory": _memory, "linear": _linear, "live": _live}
