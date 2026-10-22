#!/usr/bin/env python3
"""The minimal contract of an external concern pack.

A concern pack is a Python package INSIDE the agent repo. Its __init__.py
declares itself:

    ANYTIME_PLUGIN = {"name": "example", "engine": ">=0.3,<0.4"}

and its direct submodules self-register concerns / providers / @actions on
import. Loading (ANYTIME_PLUGINS, --plugins) refuses: a package outside the
repo, an engine version outside the declared range, a malformed declaration,
and any collision (pack name, concern name, provider name) between packs.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _engine_isolation import IsolatedTestCase  # noqa: E402
from anytime_engine import plugins  # noqa: E402
from anytime_engine.assembler import all_providers, clear_providers  # noqa: E402
from anytime_engine.registry import all_concerns, clear, validate  # noqa: E402

# The minimal example pack (also the template in docs/concern-packs.md).
EXAMPLE_CONCERNS = '''
from anytime_engine.assembler import register_provider
from anytime_engine.registry import Concern, register

register_provider("{prov}", lambda state: {{"open": 0}})
register(Concern(name="{concern}", description="example", triggers=["hourly"],
                 should_run=lambda s: s.is_stale("{concern}", 60),
                 action="{concern}", context_needs=["{prov}"]))
'''


class _PackCase(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        clear()
        clear_providers()
        sys.path.insert(0, str(self.root))
        self._pkgs: list[str] = []
        self._dirs: list[Path] = []

    def tearDown(self):
        sys.path.remove(str(self.root))
        for d in self._dirs:
            sys.path.remove(str(d))
            shutil.rmtree(d, ignore_errors=True)
        for name in list(sys.modules):
            if name.split(".")[0] in self._pkgs:
                del sys.modules[name]
        clear()
        clear_providers()
        super().tearDown()

    def pack(self, *, decl: str | None = 'name="{name}", engine=">=0.3,<1.0"',
             name: str = "example", concern: str = "example_due",
             prov: str = "example_data", where: Path | None = None) -> str:
        pkg = f"pack_{uuid.uuid4().hex[:8]}"
        self._pkgs.append(pkg)
        d = (where or self.root) / pkg
        d.mkdir(parents=True)
        init = "" if decl is None else "ANYTIME_PLUGIN = dict(" + decl.format(name=name) + ")\n"
        (d / "__init__.py").write_text(init)
        (d / "concerns.py").write_text(EXAMPLE_CONCERNS.format(concern=concern, prov=prov))
        return pkg

    def load(self, *pkgs):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            infos = plugins.load(list(pkgs))
        return infos, err.getvalue()


class TestContract(_PackCase):
    def test_the_example_pack_loads_and_validates(self):
        infos, _ = self.load(self.pack())
        self.assertEqual([i.name for i in infos], ["example"])
        self.assertIn("example_due", all_concerns())
        self.assertIn("example_data", all_providers())
        self.assertEqual(validate(), [])

    def test_engine_outside_the_declared_range_is_refused(self):
        pkg = self.pack(decl='name="example", engine=">=9.0"')
        with self.assertRaisesRegex(plugins.PluginError, ">=9.0"):
            self.load(pkg)
        self.assertNotIn("example_due", all_concerns())

    def test_malformed_declaration_is_refused(self):
        for decl in ('engine=">=0.3"', 'name="x", engine="~0.3"', 'name="", engine=">=0.3"'):
            with self.subTest(decl=decl), self.assertRaises(plugins.PluginError):
                self.load(self.pack(decl=decl))

    def test_undeclared_pack_loads_as_legacy_with_a_warning(self):
        infos, err = self.load(self.pack(decl=None))
        self.assertFalse(infos[0].declared)
        self.assertIn("ANYTIME_PLUGIN", err)

    def test_package_outside_the_repo_is_refused(self):
        outside = Path(tempfile.mkdtemp(prefix="anytime-outside-"))
        sys.path.insert(0, str(outside))
        self._dirs.append(outside)
        with self.assertRaisesRegex(plugins.PluginError, "outside the repo"):
            self.load(self.pack(where=outside))


class TestSiblingImports(_PackCase):
    def test_a_sibling_imported_during_the_load_is_not_reloaded(self):
        # concerns.py imports errors.py before the loader reaches it; reloading
        # it then would make a second Err class: `except Err` in one module no
        # longer catches the Err raised by another (found while building the cases pack).
        pkg = self.pack()
        d = self.root / pkg
        (d / "errors.py").write_text("class Err(Exception):\n    pass\n")
        (d / "concerns.py").write_text((d / "concerns.py").read_text()
                                       + "from .errors import Err\n")
        self.load(pkg)
        self.assertIs(sys.modules[f"{pkg}.concerns"].Err, sys.modules[f"{pkg}.errors"].Err)


class TestCollisions(_PackCase):
    def test_same_pack_name(self):
        with self.assertRaisesRegex(plugins.PluginError, "pack name 'example'"):
            self.load(self.pack(), self.pack(concern="b", prov="pb"))

    def test_same_concern_name(self):
        b = self.pack(name="other", prov="pb")
        with self.assertRaisesRegex(plugins.PluginError, b):
            self.load(self.pack(), b)

    def test_same_provider_name(self):
        a, b = self.pack(), self.pack(name="other", concern="b")
        with self.assertRaisesRegex(plugins.PluginError, "provider 'example_data'"):
            self.load(a, b)


if __name__ == "__main__":
    unittest.main()
