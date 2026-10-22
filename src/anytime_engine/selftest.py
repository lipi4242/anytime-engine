"""selftest — the engine's own tests, one command, one exit code.

    python3 -m anytime_engine.selftest        # 0 = green · 1 = red · 2 = no tests found
    python3 -m anytime_engine.selftest -k ID  # rerun one test (a red run prints this line)

A red run prints, per failed test: its id, the reason in one line and the rerun command.

Stdlib only (no pytest, no venv), from any working directory: it finds the
tests next to this package (a vendored `anytime_engine/tests/`, or the source
repo's `tests/`) and makes this copy of the engine the one they import.
The concern packs vendored beside it (anytime_cases, anytime_calendar) are
tested too; where a pack is absent its tests skip.
"""
from __future__ import annotations

import argparse
import io
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_LISTED = 8


def tests_dir() -> Path | None:
    for d in (HERE / "tests", HERE.parent.parent / "tests"):
        if d.is_dir() and any(d.glob("test_*.py")):
            return d
    return None


def _flat(suite):
    for t in suite:
        yield from _flat(t) if isinstance(t, unittest.TestSuite) else [t]


def _reason(tb: str) -> str:
    lines = [l.strip() for l in tb.strip().splitlines() if l.strip()]
    return (lines[-1] if lines else "?")[:200]


def run(tests: Path, verbosity: int = 1, pattern: str | None = None) -> int:
    sys.path.insert(0, str(HERE.parent))   # this engine copy, whatever the cwd
    suite = unittest.TestLoader().discover(str(tests), top_level_dir=str(tests))
    if pattern:
        suite = unittest.TestSuite(t for t in _flat(suite) if pattern in t.id())
        if not suite.countTestCases():
            print(f"selftest: no test matches -k {pattern!r}")
            return 2
    stream = sys.stderr if verbosity == 2 else io.StringIO()   # -v: everything, live
    # buffer: what a passing test prints (on purpose: refusals it provokes) stays quiet
    result = unittest.TextTestRunner(stream=stream, verbosity=verbosity, buffer=True).run(suite)
    if result.testsRun == 0:
        print(f"selftest: NO TESTS in {tests}")
        return 2
    broken = result.failures + result.errors
    bad = len(broken) + len(result.unexpectedSuccesses)
    for test, tb in broken[:MAX_LISTED]:   # which test, why (one line), how to rerun it alone
        print(f"FAIL {test.id()} — {_reason(tb)}\n  repro: python3 -m anytime_engine.selftest "
              f"-k {test.id()}   # add -v for the full trace")
    if len(broken) > MAX_LISTED:
        print(f"... and {len(broken) - MAX_LISTED} more (selftest -v lists all)")
    print(f"selftest: {'OK' if not bad else 'FAILED'} — {result.testsRun} run, "
          f"{bad} failed, {len(result.skipped)} skipped ({tests})")
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m anytime_engine.selftest",
                                description="Run the engine's own tests (stdlib).")
    p.add_argument("-q", "--quiet", action="store_true", help="(kept: the default is as short)")
    p.add_argument("-v", "--verbose", action="store_true", help="one line per test, full traces")
    p.add_argument("-k", dest="pattern", metavar="ID", help="only tests whose id contains ID")
    args = p.parse_args(argv)
    tests = tests_dir()
    if tests is None:
        print(f"selftest: NO TESTS next to {HERE} (re-run sync-to.sh)")
        return 2
    return run(tests, verbosity=2 if args.verbose else 0, pattern=args.pattern)


if __name__ == "__main__":
    raise SystemExit(main())
