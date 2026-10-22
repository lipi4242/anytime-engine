#!/usr/bin/env python3
"""A vendored concern pack is wired: `engine_manifest --plugin PKG` (sync-to.sh
--pack cases) appends it to mentat.json components.engine.plugins, once, and
touches nothing else.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
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
from anytime_engine import mentat_manifest as mm  # noqa: E402


class TestPackWiring(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(Path(anytime_engine.__file__).parent, self.root / "anytime_engine",
                        ignore=shutil.ignore_patterns("__pycache__", "tests"))

    def record(self, *argv):
        env = dict(os.environ, PYTHONPATH=str(self.root), ANYTIME_REPO_ROOT=str(self.root))
        return subprocess.run([sys.executable, "-m", "anytime_engine.engine_manifest", *argv],
                              cwd=self.root, env=env, capture_output=True, text=True)

    def manifest(self, engine):
        mm.manifest_path(self.root).write_text(json.dumps(
            {"schema": 1, "components": {"brain": {"root": "agy"}, "engine": engine}}))

    def engine(self):
        return json.loads(mm.manifest_path(self.root).read_text())["components"]["engine"]

    def test_pack_is_appended_once_and_kept_in_order(self):
        self.manifest({"plugins": ["agent.concerns"], "schedule_owner": "fleet"})
        for _ in range(2):
            r = self.record("--plugin", "anytime_cases")
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.engine(), {"plugins": ["agent.concerns", "anytime_cases"],
                                         "schedule_owner": "fleet", "path": "anytime_engine"})

    def test_without_plugin_the_list_is_untouched(self):
        self.manifest({"plugins": ["x"]})
        self.assertEqual(self.record().returncode, 0)
        self.assertEqual(self.engine()["plugins"], ["x"])

    def test_without_mentat_json_nothing_is_written_and_the_env_is_named(self):
        r = self.record("--plugin", "anytime_cases")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(mm.manifest_path(self.root).exists())
        self.assertIn("ANYTIME_PLUGINS=anytime_cases", r.stderr)


if __name__ == "__main__":
    unittest.main()
