"""versions — the one version grammar of the Mentat components.

`MAJOR.MINOR[.PATCH]`; a range is comma-separated `>=X` / `<X` conditions (the
release.json `requires_if_present` format, LG1 §4, and a concern pack's
`ANYTIME_PLUGIN["engine"]`). No resolver: a mismatch stops and says so.

    python3 -m anytime_engine.versions check-upgrade OLD NEW   # exit 1 if NEW < OLD
"""
from __future__ import annotations

import re
import sys

_V = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")


def parse(v: str) -> tuple[int, int, int]:
    m = _V.match(v.strip())
    if not m:
        raise ValueError(f"not a MAJOR.MINOR[.PATCH] version: {v!r}")
    return int(m[1]), int(m[2]), int(m[3] or 0)


def satisfies(version: str, spec: str) -> bool:
    v = parse(version)
    for cond in (c.strip() for c in spec.split(",")):
        if cond.startswith(">="):
            ok = v >= parse(cond[2:])
        elif cond.startswith("<"):
            ok = v < parse(cond[1:])
        else:
            raise ValueError(f"unsupported condition {cond!r} in {spec!r} (only >= and <)")
        if not ok:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3 or args[0] != "check-upgrade":
        print("usage: python3 -m anytime_engine.versions check-upgrade OLD NEW", file=sys.stderr)
        return 2
    old, new = args[1], args[2]
    if parse(new) < parse(old):
        print(f"refusing downgrade {old} -> {new} (pass --allow-downgrade to sync-to.sh "
              f"if you mean it; see the state rollback policy first)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
