"""`python3 -m anytime_bekotes.frissit` — the deterministic half of the daily refresh.

    --baseline        save the current snapshot as the cursor (end of the wiring)
    --begin           diff since the cursor -> <biz>/.pending-kurzor.json, mark the
                      deleted refs [elavult <day>], print run_id + compact diff;
                      a run under way (pending < 2 h) -> exit 1
    --advance RUN_ID  the matching pending becomes the cursor (atomically), if every
                      citation of the map still resolves; else exit 1, cursor kept
    --status          per business and source: the cursor, the pending run, errors

Time is the engine clock (agent-local). Writes only inside the business folders.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from typing import Any

from anytime_engine import clock
from anytime_engine import config as engine_config

from . import cursor, diff, pending, render, sources, stale
from .config import businesses


def baseline(bizs: list[dict[str, Any]], root, now) -> int:
    for biz in bizs:
        snaps = {s["name"]: sources.snapshot(s, root) for s in biz.get("sources") or []}
        cursor.save(biz["dir"], {"schema": 1, "sources": snaps, "advanced_at": now.isoformat()})
        pending.clear(biz["dir"])
        print(f"{biz.get('business')}: kurzor mentve ({len(snaps)} forrás)")
    return 0


def begin(bizs: list[dict[str, Any]], root, now) -> int:
    work = []
    for biz in bizs:
        try:
            if cursor.load(biz["dir"]) is None:
                print(f"{biz.get('business')}: nincs kurzor — futtasd: frissit --baseline")
                continue
            p = pending.load(biz["dir"])
            if pending.fresh(p, now):
                print(f"{biz.get('business')}: már fut egy frissítés (run_id {p['run_id']}, "
                      f"{p['started_at']}) — várd meg, vagy 2 óra múlva újra")
                return 1
            work.append((biz, diff.compute(biz, root, now)))
        except Exception as e:     # one broken business never blocks the others
            print(f"{biz.get('business')}: HIBA: {e}")
    run_id, started = f"{now:%Y%m%dT%H%M%S}-{secrets.token_hex(3)}", 0
    for biz, d in work:
        pending.clear(biz["dir"])
        if not diff.actionable(d):
            errs = [c["source"] for c in d["changes"]]
            print(f"## {biz.get('business')}: nincs változás"
                  + (f" (nem olvasható: {', '.join(errs)})" if errs else ""))
            continue
        if not started:
            print(f"run_id: {run_id}")
        pending.save(biz["dir"], {"run_id": run_id, "started_at": now.isoformat(),
                                  "next": d["next"], "changes": d["changes"],
                                  "deleted": d["deleted"]})
        marked = stale.mark(biz["dir"], d["deleted"], now.date().isoformat())
        print("\n".join(render.diff_lines(biz, d, marked)))
        started += 1
    if not started:
        print("nincs teendő — ne léptess")
        return 1
    return 0


def advance(bizs: list[dict[str, Any]], root, now, run_id: str) -> int:
    runs = [(b, p) for b in bizs if (p := pending.load(b["dir"])) and p["run_id"] == run_id]
    if not runs:
        print(f"nincs {run_id} azonosítójú függő futás — a kurzor marad")
        return 1
    for biz, _ in runs:
        bad = diff.unresolved_refs(biz, root)
        if bad:
            print(f"{biz.get('business')}: fel nem oldható hivatkozás(ok), a kurzor marad: "
                  + ", ".join(bad))
            return 1
    for biz, p in runs:
        cursor.save(biz["dir"], {**p["next"], "advanced_at": now.isoformat()})
        pending.clear(biz["dir"])
        print(f"{biz.get('business')}: kurzor léptetve ({run_id})")
    return 0


def status(bizs: list[dict[str, Any]], root, now) -> int:
    for biz in bizs:
        print(f"## {biz.get('business')}")
        try:
            _status(biz, root, now)
        except Exception as e:     # a corrupt cursor, an odd source: shown, not a crash
            print(f"  HIBA: {e}")
    return 0


def _status(biz: dict[str, Any], root, now) -> None:
    cur = cursor.load(biz["dir"])
    if cur is None:
        print("  futtasd: frissit --baseline")
        return
    print(f"  léptetve: {cur.get('advanced_at')}")
    for name, snap in (cur.get("sources") or {}).items():
        print(f"  {name}: {render.snapshot(snap)}")
    p = pending.load(biz["dir"])
    if p:
        print(f"  függő futás: {p['run_id']} ({p.get('started_at')}, "
              + ("fut" if pending.fresh(p, now) else "megszakadt") + ")")
    d = diff.compute(biz, root, now)
    for c in d["changes"]:
        if c["kind"] == "error":
            print(f"  HIBA: {c['source']} — a forrás most nem olvasható")
    print(f"  most: {len(d['changes'])} változás, {len(d['deleted'])} törölt hivatkozás")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m anytime_bekotes.frissit")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--baseline", action="store_true")
    g.add_argument("--begin", action="store_true")
    g.add_argument("--advance", metavar="RUN_ID")
    g.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)
    root, now = engine_config.repo_root(), clock.now()
    try:
        bizs = businesses(root)
    except Exception as e:
        print(f"HIBA: a business-ek nem olvashatók ({e})")
        return 1
    if not bizs:
        print("nincs bekötött business (<agy>/business/*/bekotes.json)")
        return 1
    if args.baseline:
        return baseline(bizs, root, now)
    if args.begin:
        return begin(bizs, root, now)
    if args.advance:
        return advance(bizs, root, now, args.advance)
    return status(bizs, root, now)


if __name__ == "__main__":
    sys.exit(main())
