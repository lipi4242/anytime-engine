"""The engine's own keys in mentat.json / .mentat/local.json (LG1 contract).

    components.engine = {"path": "anytime_engine", "plugins": [...],
                         "schedule_owner": "engine" | "fleet",
                         # recorded by `anytime_engine.setup`:
                         "timezone": "Europe/Budapest", "morning": "07:00",
                         "delivery": {"channel": "file" | "telegram", "lang": "en" | "hu"},
                         "exec": "python3 -m anytime_cases.deliver"}
    installed.engine  = "<engine version>"

Everything else in those files belongs to another element and is never
touched. No mentat.json = a standalone engine: nothing is read or created.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import __version__, config
from . import mentat_manifest as mm


def root() -> Path:
    return config.repo_root().resolve()


def section(r: Path | None = None) -> dict[str, Any]:
    """components.engine ({} if absent). Raises mm.SchemaTooNew / ManifestError
    — a manifest that cannot be read must stop the engine, not be guessed."""
    doc = mm.load(r or root())
    return dict(((doc or {}).get("components") or {}).get("engine") or {})


def plugins(r: Path | None = None) -> list[str]:
    raw = section(r).get("plugins") or []
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise mm.ManifestError("components.engine.plugins must be a list of package names")
    return raw


def schedule_owner(r: Path | None = None) -> str | None:
    return section(r).get("schedule_owner")


def record_settings(data: dict[str, Any], r: Path | None = None) -> None:
    """setup: merge the install choices into components.engine (mentat.json must exist)."""
    mm.update("engine", "components", data, r or root())


def _package_path(r: Path) -> str | None:
    here = Path(__file__).resolve().parent
    return mm.check_relative(here.relative_to(r).as_posix()) if here.is_relative_to(r) else None


def record_vendored(r: Path | None = None, packs: list[str] = ()) -> bool:
    """After a sync (sync-to.sh): components.engine.path + installed.engine,
    and each vendored concern pack appended to components.engine.plugins
    (kept once, in order). No-op (False) without a mentat.json."""
    r = r or root()
    if mm.load(r) is None:
        return False
    data: dict[str, Any] = {}
    path = _package_path(r)
    if path:
        data["path"] = path
    if packs:
        have = plugins(r)
        data["plugins"] = have + [p for p in dict.fromkeys(packs) if p not in have]
    if data:
        mm.update("engine", "components", data, r)
    mm.update("engine", "installed", __version__, r)
    return True


def record_install(plugin_list: list[str], r: Path | None = None) -> bool:
    """After the engine's own install (schedule --install): write our section.
    The owner is set to `engine` only when unset — never taken from the fleet.
    Returns False (and writes nothing) without a mentat.json."""
    r = r or root()
    if mm.load(r) is None:
        return False
    data: dict[str, Any] = {"plugins": plugin_list}
    if not schedule_owner(r):
        data["schedule_owner"] = "engine"
    path = _package_path(r)
    if path:
        data["path"] = path
    mm.update("engine", "components", data, r)
    mm.update("engine", "installed", __version__, r)
    print(f"mentat.json: components.engine + installed.engine={__version__} recorded",
          file=sys.stderr)
    return True


if __name__ == "__main__":   # sync-to.sh: python3 -m anytime_engine.engine_manifest [--plugin PKG]...
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m anytime_engine.engine_manifest")
    ap.add_argument("--plugin", action="append", default=[], metavar="PKG",
                    help="a concern pack vendored next to the engine: add it to engine.plugins")
    args = ap.parse_args()
    try:
        done = record_vendored(packs=args.plugin)
    except mm.ManifestError as e:
        print(f"mentat.json not updated: {e}", file=sys.stderr)
        raise SystemExit(1)
    print("mentat.json: engine recorded" if done else "no mentat.json: standalone, nothing written")
    if args.plugin and not done:
        print(f"to load the pack(s): ANYTIME_PLUGINS={','.join(args.plugin)}", file=sys.stderr)
