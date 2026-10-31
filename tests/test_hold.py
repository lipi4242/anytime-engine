#!/usr/bin/env python3
"""The outward hold (kifelé-tartás): while data/state/kifele-tartas.json is in
force, nothing leaves the agent.

The incident (H5, 2026-10): a developer building into a live agent ran its tick
without --dry-run and the agent sent a real reminder to the team group. The
procedure text said "only --dry-run during build"; the guard is now the state.
Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
import unittest
from datetime import timedelta
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _engine_isolation import IsolatedTestCase  # noqa: E402
from anytime_engine import clock, hold, tick  # noqa: E402
from anytime_engine.assembler import clear_providers  # noqa: E402
from anytime_engine.registry import Concern, clear, register  # noqa: E402


def put(root: Path, *, hours: float = 2, raw: str | None = None, age_h: float = 0) -> Path:
    p = hold.path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    until = clock.stamp(clock.now() + timedelta(hours=hours))
    set_at = clock.stamp(clock.now() - timedelta(hours=age_h))
    p.write_text(raw if raw is not None else json.dumps(
        {"until": until, "reason": "Vilma építése", "set_by": "fleet hold-outward", "set_at": set_at}))
    # mtime a motor órájához igazítva: a hamis órás dobozban (libfaketime) a kernel-mtime és a
    # clock.now() eltér; a tesztek a set_at nélküli tartalék-utat is az ő órájukon mérik
    t = (clock.now() - timedelta(hours=age_h)).timestamp()
    os.utime(p, (t, t))
    return p


class TestMarker(IsolatedTestCase):
    def test_no_marker_no_hold(self):
        self.assertIsNone(hold.active())

    def test_marker_in_force(self):
        put(self.root)
        h = hold.active()
        self.assertEqual(h["reason"], "Vilma építése")
        self.assertIn("kifelé-tartás aktív — dry-run, eddig: ", hold.banner(h))

    def test_expired_is_ignored_and_said(self):
        put(self.root, hours=-1)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(hold.active())
        self.assertIn("lejárt", err.getvalue())

    def test_never_longer_than_24h_from_writing(self):
        put(self.root, hours=24 * 30, age_h=25)   # "until next month", written 25h ago
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(hold.active())

    def test_unreadable_marker_holds(self):
        put(self.root, raw="{nem json")
        h = hold.active()
        self.assertTrue(h["broken"])

    def test_missing_until_holds(self):
        put(self.root, raw=json.dumps({"reason": "x"}))
        self.assertTrue(hold.active()["broken"])


class TestTickIsDryWhileHeld(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        clear()
        clear_providers()
        register(Concern(name="remind", description="team reminder", triggers=["hourly"],
                         should_run=lambda s: True, action="remind"))
        self.calls = []
        self.hb = self.root / "data" / "state" / "orchestrator-heartbeat.json"

    def tearDown(self):
        clear()
        clear_providers()
        super().tearDown()

    def executor(self, plan):
        self.calls.append(plan)
        return 0

    def test_held_tick_never_runs_the_executor_nor_stamps(self):
        put(self.root)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            plan = tick.run_tick("hourly", executor=self.executor)
        self.assertEqual(self.calls, [])                       # nothing went out
        self.assertFalse(self.hb.exists())                     # and nothing claims it did
        self.assertFalse(tick.config.plan_path().exists())
        self.assertEqual([a["concern"] for a in plan["actions"]], ["remind"])
        self.assertIn("kifelé-tartás aktív — dry-run, eddig:", err.getvalue())

    def test_without_marker_the_executor_runs(self):
        tick.run_tick("hourly", executor=self.executor)
        self.assertEqual(len(self.calls), 1)

    def test_expired_marker_does_not_hold(self):
        put(self.root, hours=-1)
        with contextlib.redirect_stderr(io.StringIO()):
            tick.run_tick("hourly", executor=self.executor)
        self.assertEqual(len(self.calls), 1)

    def test_cli_with_exec_prints_the_hold_and_exits_clean(self):
        put(self.root)
        marker = self.root / "sent"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = tick.main(["hourly", "--no-discover", "--exec", f"touch {marker}"])
        self.assertEqual(rc, 0)
        self.assertFalse(marker.exists())
        self.assertIn("kifelé-tartás aktív", err.getvalue())
        self.assertIn("NOT landed (kifelé-tartás)", err.getvalue())
        self.assertIn("kifele_tartas", json.loads(out.getvalue()))



class TestSkewedClock(IsolatedTestCase):
    """A faked/skewed box clock (libfaketime, H2 harness): mtime is kernel time, now() is not."""

    def test_set_at_wins_over_mtime(self):
        p = put(self.root)
        t = clock.now().timestamp() - 30 * 24 * 3600   # the file looks a month old to the kernel
        os.utime(p, (t, t))
        self.assertIsNotNone(hold.active())

    def test_old_set_at_still_capped(self):
        put(self.root, hours=48, age_h=25)
        self.assertIsNone(hold.active())

    def test_no_set_at_falls_back_to_mtime(self):
        p = hold.path(self.root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"until": clock.stamp(clock.now() + timedelta(hours=2))}))
        t = clock.now().timestamp() - 25 * 3600
        os.utime(p, (t, t))
        self.assertIsNone(hold.active())


class TestFakeClockBox(IsolatedTestCase):
    """A teljes hold-viselkedés egy 4 nappal előre járó motor-órán (a harness libfaketime-ja;
    2026-10-30: a telepítéskori selftest ezen bukott, és az ágens nem telepítette a motort)."""

    def setUp(self):
        super().setUp()
        real = clock._utcnow
        self.addCleanup(setattr, clock, "_utcnow", real)
        clock._utcnow = lambda: real() + timedelta(days=4)

    def test_in_force(self):
        put(self.root)
        self.assertIsNotNone(hold.active())

    def test_missing_until_holds(self):
        put(self.root, raw="{}")
        self.assertTrue(hold.active()["broken"])


if __name__ == "__main__":
    unittest.main()
