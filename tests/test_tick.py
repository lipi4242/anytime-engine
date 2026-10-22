#!/usr/bin/env python3
"""tick — the engine-owned tick entry point and the fleet contract it writes.

The hazard these tests pin ("the stamp before the work"): four consumers wrote
the heartbeat / last-tick.json at the START of their tick, so a tick that died
mid-work still looked landed to fleet supervision. The engine now owns the
contract and writes both stamps only AFTER the work succeeded.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
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
from anytime_engine import tick  # noqa: E402
from anytime_engine.assembler import clear_providers  # noqa: E402
from anytime_engine.registry import Concern, clear, register  # noqa: E402
from anytime_engine.state import State  # noqa: E402


def _main(argv):
    """tick.main with its stdout swallowed (the plan JSON is noise in test output)."""
    with contextlib.redirect_stdout(io.StringIO()):
        return tick.main(argv)


def _daily(name="todos"):
    """A once-per-run concern: due until it has been marked run."""
    return Concern(
        name=name, description="read todos", triggers=["hourly", "review"],
        should_run=lambda s: s.is_stale(name, 24 * 60), action=name,
        staleness_minutes=24 * 60,
    )


class _TickCase(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        clear()
        clear_providers()
        register(_daily())
        self.hb = self.root / "data" / "state" / "orchestrator-heartbeat.json"
        self.last = self.root / "data" / "state" / "last-tick.json"

    def tearDown(self):
        clear()
        clear_providers()
        super().tearDown()


class TestStampAfterWork(_TickCase):
    def test_no_stamp_exists_while_the_work_runs(self):
        seen = {}

        def executor(plan):
            seen["hb"] = self.hb.exists()
            seen["last"] = self.last.exists()
            seen["actions"] = [a["concern"] for a in plan["actions"]]
            return 0

        tick.run_tick("hourly", executor=executor)
        self.assertEqual(seen, {"hb": False, "last": False, "actions": ["todos"]})
        self.assertTrue(self.hb.exists())
        self.assertTrue(self.last.exists())
        self.assertEqual(json.loads(self.last.read_text())["trigger"], "hourly")

    def test_failed_work_writes_no_stamp(self):
        with self.assertRaises(tick.TickError):
            tick.run_tick("hourly", executor=lambda plan: 3)
        self.assertFalse(self.hb.exists())
        self.assertFalse(self.last.exists())

    def test_crashing_work_writes_no_stamp(self):
        def executor(plan):
            raise RuntimeError("agent died mid-tick")
        with self.assertRaises(RuntimeError):
            tick.run_tick("hourly", executor=executor)
        self.assertFalse(self.hb.exists())
        self.assertFalse(self.last.exists())

    def test_invalid_registry_writes_no_stamp(self):
        register(Concern(name="broken", description="", triggers=["hourly"],
                         should_run=lambda s: True, depends_on=["nope"]))
        with self.assertRaises(tick.TickError):
            tick.run_tick("hourly")
        self.assertFalse(self.hb.exists())
        self.assertFalse(self.last.exists())

    def test_manual_trigger_never_writes_last_tick(self):
        tick.run_tick("telegram")
        self.assertTrue(self.hb.exists())       # the process is alive
        self.assertFalse(self.last.exists())    # but this proves no schedule

    def test_executor_state_writes_survive_the_tick(self):
        # The executor marks its concern done in the state file; the tick must
        # not overwrite that with its own (older) in-memory State afterwards.
        def executor(plan):
            s = State.load()
            s.mark_run("todos")
            s.save()
            return 0
        tick.run_tick("hourly", executor=executor)
        self.assertIn("todos", State.load().concern_last_run)


class TestSetupDoesNotConsumeTheFirstTick(_TickCase):
    def test_dry_run_changes_nothing_and_first_real_tick_has_work(self):
        plan = tick.run_tick("hourly", dry_run=True)
        self.assertEqual([a["concern"] for a in plan["actions"]], ["todos"])
        self.assertFalse((self.root / "data").exists())   # no state, no stamps
        real = tick.run_tick("hourly")
        self.assertEqual([a["concern"] for a in real["actions"]], ["todos"])

    def test_dry_run_with_a_legacy_state_file_still_writes_nothing(self):
        legacy = self.root / "scripts" / "anytime" / "anytime-state-v2.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"schema_version": 1, "concern_last_run": {}}))
        tick.run_tick("hourly", dry_run=True)
        self.assertFalse((self.root / "data").exists())

    def test_mark_cli_records_completion(self):
        self.assertEqual(_main(["--mark", "todos"]), 0)
        self.assertEqual(tick.run_tick("hourly", dry_run=True)["actions"], [])


class TestCli(_TickCase):
    def test_exec_command_failure_exits_nonzero_without_stamp(self):
        rc = _main(["hourly", "--no-discover", "--exec", "exit 4"])
        self.assertEqual(rc, 1)
        self.assertFalse(self.last.exists())

    def test_exec_command_receives_plan_on_stdin(self):
        out = self.root / "got.json"
        rc = _main(["hourly", "--no-discover", "--exec", f"cat > '{out}'"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.read_text())["actions"][0]["concern"], "todos")
        self.assertTrue(self.last.exists())


if __name__ == "__main__":
    unittest.main()
