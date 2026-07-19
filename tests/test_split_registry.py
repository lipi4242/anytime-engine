#!/usr/bin/env python3
"""Split-registry detection — the vendoring-next-to-a-local-copy failure mode.

Regression, reported 2026-07-19 (issue #1): a consumer vendored the engine into
a repo that already had a hand-rolled reducer of the same shape. Some concern
files imported `register` from the vendored `anytime_engine.registry`, the rest
from the pre-existing local `...registry` — two *different module objects*, each
with its own `_CONCERNS` dict. Concerns registered into the copy that nothing
downstream reads were silently inert, and `validate()` reported `valid: true`
the whole time, because by construction it only inspects its own `_CONCERNS`.

The engine can't stop a consumer having a second copy, but it must not stay
silent about it. `validate()` now scans for a second, populated registry in
memory and reports it as an error instead of a false green.

Compatible with both pytest and direct execution.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from anytime_engine.registry import (  # noqa: E402
    Concern,
    clear,
    find_foreign_registries,
    register,
    validate,
)


def _make_foreign_registry(module_name: str, concern_names: list[str]) -> str:
    """Inject a fake second registry into sys.modules holding its own concerns.

    Mimics a consumer's pre-existing local `...registry` module: same shape,
    separate `_CONCERNS` dict, populated with concerns the engine can't see.
    """
    mod = types.ModuleType(module_name)
    mod._CONCERNS = {
        n: Concern(name=n, description="", triggers=["hourly"], should_run=lambda s: True)
        for n in concern_names
    }
    sys.modules[module_name] = mod
    return module_name


class TestSplitRegistryDetection(unittest.TestCase):
    def setUp(self):
        clear()
        self._foreign = []

    def tearDown(self):
        clear()
        for name in self._foreign:
            sys.modules.pop(name, None)

    def _register_foreign(self, module_name, concern_names):
        self._foreign.append(module_name)
        return _make_foreign_registry(module_name, concern_names)

    def test_clean_install_has_no_foreign_registries(self):
        """A single-copy install: only our own registry exists."""
        register(Concern(name="alpha", description="", triggers=["hourly"],
                         should_run=lambda s: True))
        self.assertEqual(find_foreign_registries(), [])
        self.assertEqual(validate(), [])

    def test_split_registry_is_detected(self):
        register(Concern(name="alpha", description="", triggers=["hourly"],
                         should_run=lambda s: True))
        self._register_foreign("myagent.anytime.v2.registry",
                               ["media_catalog", "qbt_cleanup"])

        foreign = find_foreign_registries()
        self.assertEqual(len(foreign), 1)
        mod_name, names = foreign[0]
        self.assertEqual(mod_name, "myagent.anytime.v2.registry")
        self.assertEqual(sorted(names), ["media_catalog", "qbt_cleanup"])

    def test_validate_reports_split_instead_of_false_green(self):
        """The core regression: validate() must NOT return clean when a second
        populated registry holds concerns nothing downstream can see."""
        register(Concern(name="alpha", description="", triggers=["hourly"],
                         should_run=lambda s: True))
        self._register_foreign("myagent.anytime.v2.registry",
                               ["media_catalog", "qbt_cleanup"])

        errors = validate()
        self.assertTrue(errors, "validate() gave a false green on a split registry")
        joined = "\n".join(errors)
        self.assertIn("media_catalog", joined)
        self.assertIn("myagent.anytime.v2.registry", joined)

    def test_empty_foreign_registry_is_not_flagged(self):
        """A second copy that registered nothing (e.g. a re-export shim keeping
        an empty _CONCERNS) is harmless and must not trip a false positive."""
        register(Concern(name="alpha", description="", triggers=["hourly"],
                         should_run=lambda s: True))
        self._register_foreign("myagent.anytime.v2.registry", [])
        self.assertEqual(find_foreign_registries(), [])
        self.assertEqual(validate(), [])


if __name__ == "__main__":
    unittest.main()
