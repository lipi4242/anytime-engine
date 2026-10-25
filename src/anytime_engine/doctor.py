"""setup --doctor — the installed timer units against what `setup --install` would write now.

    python3 -m anytime_engine.setup --doctor [--unit-dir DIR]

Read only. For each unit setup manages (anytime-<agent>-hourly.service / .timer):
    OK            identical to the generated unit
    MISSING       not there: `setup --install` writes it
    HAND-EDITED   differs: the lines are shown; the next `setup --install` overwrites them,
                  so a wanted change belongs in the setup flags or mentat.json first
    NOTE          only Environment lines setup carries from the shell (ANYTIME_TZ, …) differ
and any other anytime-<agent>-* unit in the folder is NOT MANAGED (setup never writes it).
Exit 0 when nothing is missing, hand-edited or unmanaged, else 1; 2 when it cannot compare.
Systemd units only: a cron line (`setup --cron`) is not compared.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from . import config, engine_manifest as em, schedule

FIX = ("fix: put the change into the setup flags (or mentat.json components.engine), then "
       "`python3 -m anytime_engine.setup --install --tz <tz>` rewrites the units")


def _carried(line: str) -> bool:
    return line.startswith("Environment=") and any(
        f'"{k}=' in line for k in schedule._CARRIED_ENV)


def compare(name: str, want: str, have: str) -> tuple[str, list[str]]:
    diff = [d for d in difflib.unified_diff(want.splitlines(), have.splitlines(), lineterm="", n=0)
            if d[:1] in "+-" and not d.startswith(("+++", "---"))]
    if not diff:
        return "OK", []
    if all(_carried(d[1:]) for d in diff):
        return "NOTE", [f"{name}: only the environment setup carries from the shell differs: " +
                        ", ".join(d[1:].strip() for d in diff)]
    return "HAND-EDITED", [f"  {d[0]} {d[1:]}" for d in diff[:8]] + (
        [f"  … {len(diff) - 8} more lines"] if len(diff) > 8 else [])


def run(unit_dir: str | None) -> int:
    if em.schedule_owner() == "fleet":
        print("doctor: the fleet owns this agent's schedule; there are no engine units to compare")
        return 0
    plugins = ",".join(em.plugins())
    if not plugins:
        print("doctor: cannot compare — components.engine.plugins is empty")
        return 2
    folder = Path(unit_dir) if unit_dir else Path.home() / ".config/systemd/user"
    agent = config.repo_root().resolve().name
    units = schedule.render_systemd(agent, "hourly", "hourly", plugins)
    bad, lines = False, []
    for fname, want in units.items():
        path = folder / fname
        if not path.is_file():
            bad = True
            lines.append(f"MISSING {fname} ({path}): `setup --install` writes it")
            continue
        verdict, detail = compare(fname, want, path.read_text(encoding="utf-8"))
        bad |= verdict == "HAND-EDITED"
        lines.append(f"{verdict} {fname}" if verdict != "NOTE" else f"NOTE {detail.pop(0)}")
        lines += detail
    for other in sorted(folder.glob(f"{schedule.unit_name(agent, '')}*")) if folder.is_dir() else []:
        if other.name not in units:
            bad = True
            lines.append(f"NOT MANAGED {other.name}: setup did not write it and will not update it; "
                         "recurring work belongs to the engine's tick (remove it, or ask)")
    if bad:
        lines.append(FIX)
    print("\n".join(lines))
    return 1 if bad else 0
