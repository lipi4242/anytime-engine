#!/usr/bin/env python3
"""A3 — fail-closed state, backup restore, explicit migration, operation receipts.

The hazard: a corrupt or unknown-schema state file used to be quarantined and
replaced by an EMPTY state, so every concern looked never-run and an outbound
action (an e-mail) could run again. Now:

  unknown/newer schema  -> fail closed: StateUnavailable, file untouched, no reset
  corrupt / missing     -> restore the newest intact prev.N within the age gap,
                           else fail closed
  known old schema      -> explicit migration chain, pre-migration backup first
  receipts              -> a concern marked done survives losing the state file

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
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _engine_isolation import IsolatedTestCase  # noqa: E402
from anytime_engine import config, receipts, tick  # noqa: E402
from anytime_engine.assembler import clear_providers  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.registry import Concern, clear, register  # noqa: E402
from anytime_engine.state import State, StateUnavailable  # noqa: E402

DAY = 24 * 60


def _quiet(fn, *a, **kw):
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


class _Case(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.path = config.state_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def prev(self, n: int) -> Path:
        return self.path.with_suffix(self.path.suffix + f".prev.{n}")

    def write(self, p: Path, data, *, age_min: float = 0) -> None:
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        t = time.time() - age_min * 60
        os.utime(p, (t, t))


class TestFailClosedSchema(_Case):
    def test_newer_schema_fails_closed_and_leaves_the_file_alone(self):
        self.write(self.path, {"schema_version": 99, "concern_last_run": {"x": "2026-10-14T08:00:00"}})
        before = self.path.read_bytes()
        with self.assertRaises(StateUnavailable) as cm:
            _quiet(State.load)
        self.assertIn("schema_version=99", str(cm.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])

    def test_garbage_schema_value_fails_closed(self):
        self.write(self.path, {"schema_version": "two"})
        with self.assertRaises(StateUnavailable):
            _quiet(State.load)


class TestCorruptRestore(_Case):
    def test_corrupt_current_restores_intact_recent_backup(self):
        self.write(self.prev(1), {"schema_version": 1,
                                  "concern_last_run": {"todos": "2026-10-14T08:00:00"}}, age_min=60)
        self.write(self.path, "{not json")
        s = _quiet(State.load)
        self.assertEqual(s.concern_last_run, {"todos": "2026-10-14T08:00:00"})
        quarantined = [p for p in self.path.parent.iterdir() if ".bak." in p.name]
        self.assertEqual(len(quarantined), 1, "the corrupt file is kept for the operator")

    def test_skips_a_corrupt_backup_and_takes_the_next(self):
        self.write(self.prev(1), "garbage", age_min=30)
        self.write(self.prev(2), {"schema_version": 1, "cache": {"k": 2}}, age_min=90)
        self.write(self.path, "")
        self.assertEqual(_quiet(State.load).cache, {"k": 2})

    def test_backup_older_than_the_gap_fails_closed(self):
        self.write(self.prev(1), {"schema_version": 1}, age_min=10 * 60)
        self.write(self.path, "{not json")
        with self.assertRaises(StateUnavailable) as cm:
            _quiet(State.load)
        self.assertIn("recover", str(cm.exception))

    def test_corrupt_with_no_backup_fails_closed_instead_of_resetting(self):
        self.write(self.path, "{not json")
        with self.assertRaises(StateUnavailable):
            _quiet(State.load)

    def test_missing_current_with_backup_restores(self):
        # crash between "current -> prev.1" and "tmp -> current" in save()
        self.write(self.prev(1), {"schema_version": 1, "cache": {"k": 1}}, age_min=5)
        self.assertEqual(_quiet(State.load).cache, {"k": 1})

    def test_first_run_without_any_file_is_a_fresh_state(self):
        self.assertEqual(State.load().concern_last_run, {})


class TestMigration(_Case):
    def test_v0_is_migrated_with_a_backup_first(self):
        original = {"concern_last_run": {"todos": "2026-10-14T08:00:00"}}
        self.write(self.path, original)
        s = _quiet(State.load)
        self.assertEqual(s.concern_last_run, original["concern_last_run"])
        backups = [p for p in self.path.parent.iterdir() if ".pre-migrate-v0." in p.name]
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text()), original)

    def test_dry_load_migrates_in_memory_only(self):
        self.write(self.path, {"concern_last_run": {}})
        _quiet(State.load, migrate=False)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])


def _daily(name="send_digest"):
    return Concern(name=name, description="sends an e-mail", triggers=["hourly"],
                   should_run=lambda s: s.is_stale(name, DAY), action=name,
                   staleness_minutes=DAY)


class TestReceipts(_Case):
    def setUp(self):
        super().setUp()
        clear()
        clear_providers()
        register(_daily())

    def tearDown(self):
        clear()
        super().tearDown()

    def _wipe_state(self):
        for p in list(self.path.parent.iterdir()):
            if p.name.startswith(self.path.name):
                p.unlink()

    def test_lost_state_does_not_repeat_a_marked_concern(self):
        s = State.load()
        s.last_trigger = "hourly"
        s.mark_run("send_digest")
        s.save()
        self._wipe_state()
        plan = reduce("hourly", State.load())
        self.assertEqual(plan["actions"], [], "the e-mail would be sent twice")
        rec = receipts.latest()["send_digest"]
        self.assertEqual((rec["trigger"], rec["result"]), ("hourly", "ok"))

    def test_receipt_is_written_even_if_the_state_is_never_saved(self):
        State().mark_run("send_digest")  # crash before save()
        self.assertFalse(State.load().is_stale("send_digest", DAY))

    def test_torn_last_line_is_tolerated(self):
        State().mark_run("send_digest")
        with open(config.receipts_path(), "a") as f:
            f.write('{"concern": "x", "at"')
        self.assertIn("send_digest", _quiet(receipts.latest))

    def test_serviced_review_window_survives_state_loss(self):
        os.environ["ANYTIME_REVIEW_WINDOWS"] = "morning:00:00"
        State().mark_review_serviced()
        self._wipe_state()
        self.assertFalse(State.load().review_due())


class TestTickFailsClosed(_Case):
    def setUp(self):
        super().setUp()
        clear()
        clear_providers()
        register(_daily())

    def tearDown(self):
        clear()
        super().tearDown()

    def test_unavailable_state_means_no_tick_and_no_stamp(self):
        self.write(self.path, "{not json")
        rc = _quiet(tick.main, ["hourly", "--no-discover"])
        self.assertEqual(rc, 1)
        self.assertFalse(config.last_tick_path().exists())
        self.assertFalse(config.heartbeat_path().exists())

    def test_mark_records_the_receipt_even_when_state_is_unavailable(self):
        self.write(self.path, {"schema_version": 99})
        rc = _quiet(tick.main, ["--mark", "send_digest"])
        self.assertEqual(rc, 0)
        self.assertIn("send_digest", receipts.latest())


if __name__ == "__main__":
    unittest.main()
