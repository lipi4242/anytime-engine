#!/usr/bin/env python3
"""Engine smoke tests — registry/reducer/state/prompts/config wiring.

Compatible with both pytest and direct execution.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from anytime_engine import config  # noqa: E402
from anytime_engine.assembler import clear_providers, register_provider  # noqa: E402
from anytime_engine.prompts import ACTION_PROMPTS, action, get_prompt  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.registry import Concern, clear, register  # noqa: E402
from anytime_engine.state import State  # noqa: E402


def _fresh_registry():
    clear()
    clear_providers()
    register_provider("dummy_data", lambda state: {"k": "v"})
    register(Concern(
        name="alpha",
        description="base concern",
        triggers=["hourly"],
        should_run=lambda s: True,
        context_needs=["dummy_data"],
        action="alpha_action",
        staleness_minutes=60,
    ))
    register(Concern(
        name="beta",
        description="depends on alpha",
        triggers=["hourly"],
        should_run=lambda s: True,
        depends_on=["alpha"],
        action="beta_action",
        staleness_minutes=60,
    ))


class TestReducerPlan(unittest.TestCase):
    def setUp(self):
        _fresh_registry()

    def tearDown(self):
        clear()
        clear_providers()

    def test_dependency_ordering_and_context(self):
        plan = reduce("hourly", State())
        names = [a["concern"] for a in plan["actions"]]
        self.assertEqual(names, ["alpha", "beta"])
        self.assertEqual(plan["actions"][0]["context"]["dummy_data"], {"k": "v"})
        self.assertLess(plan["actions"][0]["level"], plan["actions"][1]["level"])

    def test_provider_error_is_captured_not_raised(self):
        def boom(state):
            raise RuntimeError("nope")
        register_provider("dummy_data", boom)
        plan = reduce("hourly", State())
        self.assertIn("error", plan["actions"][0]["context"]["dummy_data"])

    def test_trigger_filtering(self):
        plan = reduce("review", State())
        self.assertEqual(plan["actions"], [])


class TestStateRoundtrip(unittest.TestCase):
    def test_unknown_keys_preserved(self):
        s = State({"cache": {"a": 1}, "agent_custom_field": {"x": 2}})
        out = s.to_dict()
        self.assertEqual(out["agent_custom_field"], {"x": 2})
        self.assertEqual(out["schema_version"], 1)

    def test_save_load_roundtrip(self):
        s = State()
        s.mark_run("alpha")
        s.save()
        loaded = State.load()
        self.assertIn("alpha", loaded.concern_last_run)


class TestConfig(unittest.TestCase):
    def test_review_times_env_override(self):
        import os
        old = os.environ.get("ANYTIME_REVIEW_TIMES")
        os.environ["ANYTIME_REVIEW_TIMES"] = "06:00,12:00,18:00"
        try:
            self.assertEqual(config.review_times(), ["06:00", "12:00", "18:00"])
        finally:
            if old is None:
                del os.environ["ANYTIME_REVIEW_TIMES"]
            else:
                os.environ["ANYTIME_REVIEW_TIMES"] = old


class TestPrompts(unittest.TestCase):
    def test_action_registry(self):
        @action("smoke_action")
        def smoke_action(ctx):
            return f"ok:{ctx.get('x')}"
        try:
            self.assertEqual(get_prompt("smoke_action", {"x": 1}), "ok:1")
            self.assertIn("Unknown action", get_prompt("missing", {}))
        finally:
            ACTION_PROMPTS.pop("smoke_action", None)


if __name__ == "__main__":
    unittest.main()


class TestStaleDependencyGuard(unittest.TestCase):
    """resolve() must not force-include a stale dep whose should_run() declines.

    Regression, found 2026-07-14 while migrating Thufir onto the engine: the
    engine's resolve() force-included any *stale* dependency, ignoring its own
    should_run(). A concern that only runs on the morning review would therefore
    get pulled into an evening review by a dependent — and execute at the wrong
    time, silently, because it looks like a normal planned action.

    A dep that declined via should_run has no fresh data to offer anyway; the
    dependent falls back to cached data, which is the whole point of the
    staleness model.
    """

    def setUp(self):
        clear()
        clear_providers()

    def tearDown(self):
        clear()
        clear_providers()

    def test_stale_dep_that_declines_is_excluded(self):
        from anytime_engine.registry import resolve

        register(Concern(name="dependent", description="", triggers=["review"],
                         should_run=lambda s: True, depends_on=["morning_only"]))
        register(Concern(name="morning_only", description="", triggers=["review"],
                         should_run=lambda s: False,   # declines under this state
                         staleness_minutes=60))

        state = State()  # morning_only never ran → stale
        names = [c.name for level in resolve("review", state) for c in level]

        self.assertIn("dependent", names)
        self.assertNotIn("morning_only", names)

    def test_stale_dep_that_wants_to_run_is_included(self):
        """The other half: a stale dep that DOES want to run is still pulled in."""
        from anytime_engine.registry import resolve

        register(Concern(name="dependent", description="", triggers=["review"],
                         should_run=lambda s: True, depends_on=["always"]))
        register(Concern(name="always", description="", triggers=["review"],
                         should_run=lambda s: True, staleness_minutes=60))

        state = State()
        names = [c.name for level in resolve("review", state) for c in level]

        self.assertIn("dependent", names)
        self.assertIn("always", names)
