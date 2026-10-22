#!/usr/bin/env python3
"""selftest — "the tests are green" as ONE command with one exit code.

The measured bug (acceptance run 2026-10-15, section 04): the agent ran
`python3 -m unittest discover -s anytime_engine/tests` (116 OK), the check ran
`... discover -s <abs>/anytime_engine/tests -t .` on a box without pytest — and
unittest refuses a top-level dir above a tests dir that is not a package
("Start directory is not importable"). Two invocations, two answers.
`python3 -m anytime_engine.selftest` is the one both sides call: any cwd, no
pytest, exit 0 only when tests ran and none failed.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

_UP = Path(__file__).resolve().parent.parent   # release/ or a vendored anytime_engine/
PKG = next(p for p in (_UP / "src" / "anytime_engine", _UP) if (p / "selftest.py").is_file())
sys.path.insert(0, str(PKG.parent))

from anytime_engine import selftest  # noqa: E402

GREEN = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n"
RED = "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self): self.fail('x')\n"


def _vendored(tests: dict[str, str]) -> Path:
    """A consumer repo with a vendored engine (no pytest, tests/ not a package)."""
    repo = Path(tempfile.mkdtemp(prefix="selftest-"))
    atexit.register(shutil.rmtree, repo, True)
    pkg = repo / "anytime_engine"
    pkg.mkdir()
    for f in PKG.glob("*.py"):
        (pkg / f.name).write_text(f.read_text())
    (pkg / "tests").mkdir()
    for name, body in tests.items():
        (pkg / "tests" / name).write_text(body)
    return repo


def _run(repo: Path, cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run([sys.executable, "-m", "anytime_engine.selftest"],
                          cwd=cwd, env=dict(env, PYTHONPATH=str(repo)),
                          capture_output=True, text=True, timeout=120)


class TestSelftest(unittest.TestCase):
    def test_green_from_another_cwd(self):
        repo = _vendored({"test_a.py": GREEN})
        r = _run(repo, cwd=Path(tempfile.gettempdir()))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("selftest: OK", r.stdout)

    def test_a_failing_test_is_exit_1(self):
        repo = _vendored({"test_a.py": GREEN, "test_b.py": RED})
        r = _run(repo, cwd=repo)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED", r.stdout)

    def test_a_red_run_names_the_test_the_reason_and_the_repro(self):
        """mérés 04: 4-5 rounds (selftest, grep, unittest, class search) to find what broke."""
        repo = _vendored({"test_a.py": GREEN, "test_b.py": RED})
        r = _run(repo, cwd=repo)
        lines = r.stdout.strip().splitlines()
        self.assertLess(len(lines), 6, r.stdout)
        self.assertIn("test_b.T.test_bad", r.stdout)
        self.assertIn("AssertionError: x", r.stdout)
        repro = next(l.split("repro:", 1)[1].strip() for l in lines if "repro:" in l)
        again = subprocess.run(repro, shell=True, cwd=repo, capture_output=True, text=True,
                               env=dict(os.environ, PYTHONPATH=str(repo)), timeout=120)
        self.assertEqual(again.returncode, 1)
        self.assertIn("1 run", again.stdout)   # only the red test ran

    def test_no_match_for_k_is_not_green(self):
        repo = _vendored({"test_a.py": GREEN})
        r = subprocess.run([sys.executable, "-m", "anytime_engine.selftest", "-k", "nope"],
                           cwd=repo, capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=str(repo)), timeout=120)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no test matches", r.stdout)

    def test_no_tests_is_not_green(self):
        repo = _vendored({})
        r = _run(repo, cwd=repo)
        self.assertEqual(r.returncode, 2)

    def test_finds_the_source_layout(self):
        self.assertEqual(selftest.tests_dir(), Path(__file__).resolve().parent)


if __name__ == "__main__":
    unittest.main()
