"""status — what the engine sees in mentat.json / .mentat/local.json (LG1 §3).

    python3 -m anytime_engine.status
    python3 -m anytime_engine.status --concerns     # JSON: the loaded concerns

Read-only. Prints the engine's section, versions, schedule owner, and which
synergies are live or absent ("admin: not connected").

`--concerns` loads the agent's packs and lists each concern with its triggers,
context_needs and `reads_cases`. The contract: a concern reads the agent's
cases (brain markdown or admin, per mentat.json cases.backend) exactly when it
needs a `cases.*` provider — those belong to the anytime_cases pack.
"""
from __future__ import annotations

import json
import sys

from . import __version__
from . import engine_manifest as em
from . import mentat_manifest as mm


def concerns() -> list[dict]:
    from .assembler import clear_providers
    from .registry import all_concerns, clear, discover
    clear()             # a fresh load, as the tick does it
    clear_providers()
    discover(None)
    return [{"name": c.name, "pack": getattr(c.should_run, "__module__", "?").split(".")[0],
             "triggers": list(c.triggers), "context_needs": list(c.context_needs),
             "reads_cases": any(n.startswith("cases.") for n in c.context_needs)}
            for c in sorted(all_concerns().values(), key=lambda c: c.name)]


def main(argv: list[str] | None = None) -> int:
    if "--concerns" in (sys.argv[1:] if argv is None else argv):
        try:
            print(json.dumps({"concerns": concerns()}, indent=2, ensure_ascii=False))
        except Exception as e:   # noqa: BLE001 — a diagnostic: say why, exit 1
            print(f"concerns: cannot load the packs — {e}", file=sys.stderr)
            return 1
        return 0
    r = em.root()
    try:
        doc, local = mm.load(r), mm.local(r)
    except mm.SchemaTooNew as e:
        print(f"mentat.json: {e} — the engine will not tick or write")
        return 0
    except mm.ManifestError as e:
        print(f"mentat.json: UNREADABLE — {e}")
        return 1
    print(f"engine: running {__version__}")
    if doc is None:
        print("mentat.json: absent — standalone engine (ANYTIME_PLUGINS / --plugins)")
        return 0
    comps = doc.get("components") or {}
    eng = comps.get("engine") or {}
    installed = ((local or {}).get("installed") or {}).get("engine")
    print(f"mentat.json: schema {doc.get('schema')}, components: {', '.join(sorted(comps)) or '-'}")
    print(f"installed (local): {installed or 'not recorded'}")
    print(f"plugins: {', '.join(eng.get('plugins') or []) or '-'}")
    print(f"schedule owner: {eng.get('schedule_owner') or 'unset'}")
    print("brain: " + (f"root {comps['brain'].get('root', '?')}" if "brain" in comps
                       else "not present"))
    print("fleet: " + ("present" if "fleet" in comps else "not present"))
    print("admin: " + ("present" if "admin" in comps and (local or {}).get("admin")
                       else "not connected"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
