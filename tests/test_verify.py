#!/usr/bin/env python3
"""The vendored copy is pinned and checkable, and there is one.

`python3 -m anytime_engine.verify` answers three questions about a consumer
repo: which engine version is vendored (VERSION), is it byte-for-byte what the
sync stamped (no hand edits), and is it the ONLY engine copy in the repo (a
second registry silently splits concerns — see test_split_registry).

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import shutil
import sys
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _engine_isolation import IsolatedTestCase  # noqa: E402
import anytime_engine  # noqa: E402
from anytime_engine import verify, versions  # noqa: E402

SRC = Path(anytime_engine.__file__).parent


def _run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = verify.main(argv)
    return rc, out.getvalue()


class TestVerify(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.pkg = self.root / "anytime_engine"
        shutil.copytree(SRC, self.pkg, ignore=shutil.ignore_patterns("__pycache__", "VERSION"))
        verify.stamp(self.pkg)

    def test_a_fresh_stamp_verifies(self):
        rc, out = _run(["--pkg", str(self.pkg), "--root", str(self.root)])
        self.assertEqual(rc, 0, out)
        self.assertIn(anytime_engine.__version__, out)
        self.assertIn(f"version={anytime_engine.__version__}",
                      (self.pkg / "VERSION").read_text())

    def test_a_hand_edit_is_caught(self):
        with open(self.pkg / "reducer.py", "a") as f:
            f.write("\n# local fix\n")
        rc, out = _run(["--pkg", str(self.pkg), "--root", str(self.root)])
        self.assertEqual(rc, 1)
        self.assertIn("hand-edited", out)

    def test_pycache_does_not_count_as_an_edit(self):
        (self.pkg / "__pycache__").mkdir()
        (self.pkg / "__pycache__" / "reducer.cpython-314.pyc").write_bytes(b"x")
        self.assertEqual(_run(["--pkg", str(self.pkg), "--root", str(self.root)])[0], 0)

    def test_a_second_copy_is_reported(self):
        legacy = self.root / "scripts" / "anytime" / "v2"
        legacy.mkdir(parents=True)
        (legacy / "registry.py").write_text("")
        (legacy / "reducer.py").write_text("")
        other = self.root / "vendor" / "anytime_engine"
        other.mkdir(parents=True)
        (other / "registry.py").write_text("")
        (self.root / ".venv" / "anytime_engine").mkdir(parents=True)
        (self.root / ".venv" / "anytime_engine" / "registry.py").write_text("")
        rc, out = _run(["--pkg", str(self.pkg), "--root", str(self.root)])
        self.assertEqual(rc, 1)
        self.assertIn("scripts/anytime/v2", out)
        self.assertIn("vendor/anytime_engine", out)
        self.assertNotIn(".venv", out)

    def test_no_version_file_is_unverifiable(self):
        (self.pkg / "VERSION").unlink()
        rc, out = _run(["--pkg", str(self.pkg), "--root", str(self.root)])
        self.assertEqual(rc, 1)
        self.assertIn("no VERSION", out)


class TestVersions(unittest.TestCase):
    def test_order_and_ranges(self):
        self.assertLess(versions.parse("0.2.9"), versions.parse("0.3"))
        self.assertTrue(versions.satisfies("0.3.1", ">=0.3,<0.4"))
        self.assertFalse(versions.satisfies("0.4.0", ">=0.3,<0.4"))
        self.assertFalse(versions.satisfies("0.2.0", ">=0.3"))
        with self.assertRaises(ValueError):
            versions.satisfies("0.3.0", "~0.3")

    def test_compare_cli_refuses_a_downgrade(self):
        self.assertEqual(versions.main(["check-upgrade", "0.3.0", "0.2.0"]), 1)
        self.assertEqual(versions.main(["check-upgrade", "0.2.0", "0.3.0"]), 0)
        self.assertEqual(versions.main(["check-upgrade", "0.3.0", "0.3.0"]), 0)


if __name__ == "__main__":
    unittest.main()
