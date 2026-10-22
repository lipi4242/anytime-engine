#!/usr/bin/env python3
"""mentat.json integration (LG1): the engine reads and writes ONLY its own keys.

  components.engine  {path, plugins, schedule_owner}   (mentat.json, committed)
  installed.engine   "<version>"                       (.mentat/local.json)

Rule 2: writes under the .mentat/lock flock, unknown fields kept.
Rule 3: `plugins` may only name the repo's own packages.
Rule 5: `schedule --install` refuses when schedule_owner is `fleet`.
Rule 6: a newer mentat.json schema -> diagnostics only: no tick, no write.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
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
from anytime_engine import config, mentat_manifest as mm, schedule, status, tick  # noqa: E402
from anytime_engine.assembler import clear_providers  # noqa: E402
from anytime_engine.registry import all_concerns, clear  # noqa: E402


def _quiet(fn, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = fn(argv)
    return rc, out.getvalue()


class _Case(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        clear()
        clear_providers()
        self.units = self.root / "units"

    def tearDown(self):
        clear()
        clear_providers()
        for m in [m for m in sys.modules if m.startswith("mjpack")]:
            del sys.modules[m]
        if str(self.root) in sys.path:
            sys.path.remove(str(self.root))
        super().tearDown()

    def manifest(self, engine=None, schema=1, **extra):
        doc = {"schema": schema, "agent": {"name": "t"},
               "components": {"brain": {"root": "agy"}, **({"engine": engine} if engine else {})},
               **extra}
        mm.manifest_path(self.root).write_text(json.dumps(doc))

    def read(self):
        return json.loads(mm.manifest_path(self.root).read_text())

    def install(self, *extra):
        return _quiet(schedule.main, ["--plugins", "a.concerns", "--name", "bot", "--install",
                                      "--no-enable", "--unit-dir", str(self.units), *extra])


class TestSchedule(_Case):
    def test_fleet_owned_schedule_is_refused(self):
        self.manifest({"schedule_owner": "fleet"})
        rc, out = self.install()
        self.assertNotEqual(rc, 0)
        self.assertIn("fleet", out)
        self.assertFalse(self.units.exists())

    def test_install_writes_only_the_engine_keys(self):
        self.manifest({"keep_me": 1}, cases={"backend": "markdown"})
        rc, out = self.install()
        self.assertEqual(rc, 0, out)
        doc = self.read()
        eng = doc["components"]["engine"]
        self.assertEqual((eng["schedule_owner"], eng["plugins"], eng["keep_me"]),
                         ("engine", ["a.concerns"], 1))
        self.assertEqual(doc["components"]["brain"], {"root": "agy"})
        self.assertEqual(doc["cases"], {"backend": "markdown"})
        local = json.loads(mm.local_path(self.root).read_text())
        self.assertEqual(local["installed"]["engine"], anytime_engine.__version__)

    def test_without_mentat_json_nothing_is_created(self):
        rc, _ = self.install()
        self.assertEqual(rc, 0)
        self.assertFalse(mm.manifest_path(self.root).exists())

    def test_newer_schema_is_not_written(self):
        self.manifest(schema=2)
        before = mm.manifest_path(self.root).read_text()
        rc, out = self.install()
        self.assertNotEqual(rc, 0)
        self.assertEqual(mm.manifest_path(self.root).read_text(), before)
        self.assertFalse(self.units.exists())


class TestTick(_Case):
    def _pack(self):
        d = self.root / "mjpack"
        d.mkdir()
        (d / "__init__.py").write_text('ANYTIME_PLUGIN = {"name": "mj", "engine": ">=0.3"}\n')
        (d / "c.py").write_text(
            "from anytime_engine.registry import Concern, register\n"
            "register(Concern(name='mj_due', description='', triggers=['hourly'],"
            " should_run=lambda s: True))\n")
        sys.path.insert(0, str(self.root))

    def test_plugins_come_from_mentat_json(self):
        self._pack()
        self.manifest({"plugins": ["mjpack"]})
        rc, out = _quiet(tick.main, ["hourly", "--dry-run"])
        self.assertEqual(rc, 0, out)
        self.assertIn("mj_due", all_concerns())

    def test_a_foreign_package_in_mentat_json_is_refused(self):
        self.manifest({"plugins": ["json"]})
        rc, out = _quiet(tick.main, ["hourly"])
        self.assertEqual(rc, 1)
        self.assertIn("outside the repo", out)
        self.assertFalse(config.heartbeat_path().exists())

    def test_newer_schema_means_no_tick(self):
        self._pack()
        self.manifest({"plugins": ["mjpack"]}, schema=2)
        rc, out = _quiet(tick.main, ["hourly", "--plugins", "mjpack"])
        self.assertEqual(rc, 1)
        self.assertIn("schema 2", out)
        self.assertFalse(config.last_tick_path().exists())


class TestManifestLib(_Case):
    def test_concurrent_writers_lose_nothing(self):
        self.manifest()
        def w(elem):
            for i in range(30):
                mm.update(elem, "components", {"n": i}, self.root)
        ts = [threading.Thread(target=w, args=(e,)) for e in ("engine", "fleet")]
        [t.start() for t in ts]
        [t.join() for t in ts]
        comps = self.read()["components"]
        self.assertEqual((comps["engine"]["n"], comps["fleet"]["n"]), (29, 29))
        self.assertEqual(comps["brain"], {"root": "agy"})

    def test_paths_must_stay_in_the_repo(self):
        for bad in ("../x", "/abs/x", "a/../../b"):
            with self.assertRaises(mm.ManifestError):
                mm.check_relative(bad)
        self.assertEqual(mm.check_relative("anytime_engine"), "anytime_engine")

    def test_sync_records_path_and_version_only(self):
        import os, shutil, subprocess
        self.manifest({"schedule_owner": "fleet", "plugins": ["x"]})
        shutil.copytree(Path(anytime_engine.__file__).parent, self.root / "anytime_engine",
                        ignore=shutil.ignore_patterns("__pycache__"))
        env = dict(os.environ, PYTHONPATH=str(self.root), ANYTIME_REPO_ROOT=str(self.root))
        r = subprocess.run([sys.executable, "-m", "anytime_engine.engine_manifest"],
                           cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        eng = self.read()["components"]["engine"]
        self.assertEqual(eng, {"schedule_owner": "fleet", "plugins": ["x"],
                               "path": "anytime_engine"})
        local = json.loads(mm.local_path(self.root).read_text())
        self.assertEqual(local["installed"]["engine"], anytime_engine.__version__)

    def test_status_says_what_it_sees(self):
        self.manifest({"schedule_owner": "fleet", "plugins": []})
        rc, out = _quiet(status.main, [])
        self.assertEqual(rc, 0)
        self.assertIn("schedule owner: fleet", out)
        self.assertIn("admin: not connected", out)


if __name__ == "__main__":
    unittest.main()
