#!/usr/bin/env python3
"""The cases pack's ready executor: `python3 -m anytime_cases.deliver`.

The measured gap (acceptance run 2026-10-15, sections 04/10/09): "tell me when
it is due" only ever reached a file the user had to open, and every agent had
to write its own morning concern and executor. The pack now renders its own
messages (no model), sends them on the channel chosen at install (file by
default, Telegram only when chosen), and marks `delivered:` only after a
confirmed send. Compatible with both pytest and direct execution.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

try:
    import pytest  # noqa: F401
except Exception:  # pragma: no cover
    pytest = None

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _cases_fixture import CasesCase  # noqa: E402
from _fake_sendmjs import FakeSend, needs_node  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.state import State  # noqa: E402

T = datetime(2026, 10, 15, 8, 30)
TOKEN = "123456:SECRET-test-token"


def names(plan):
    return [a["concern"] for a in plan["actions"]]


class DeliverCase(CasesCase):
    delivery: dict = {}

    def setUp(self):
        super().setUp()
        doc = json.loads((self.root / "mentat.json").read_text())
        doc["components"]["engine"].update(delivery=self.delivery, morning="07:00")
        (self.root / "mentat.json").write_text(json.dumps(doc))
        from anytime_cases import deliver, telegram
        self.deliver, self.telegram = deliver, telegram

    def run_plan(self, plan, **kw):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = self.deliver.run(plan, **kw)
        return rc, out.getvalue(), err.getvalue()


class TestMorningTime(DeliverCase):
    def test_hourly_tick_brings_the_morning_at_its_local_time(self):
        self.assertNotIn("cases_morning", names(reduce("hourly", State(), now=T.replace(hour=6))))
        self.assertIn("cases_morning", names(reduce("hourly", State(), now=T.replace(hour=7, minute=0))))

    def test_review_tick_still_brings_it_any_time(self):
        self.assertIn("cases_morning", names(reduce("review", State(), now=T.replace(hour=5))))


class TestFileChannel(DeliverCase):
    def test_default_channel_is_a_file_and_marks_after_writing(self):
        rc, _, _ = self.run_plan(reduce("review", State(), now=T))
        self.assertEqual(rc, 0)
        text = (self.root / "data" / "outbox" / "2026-10-15.md").read_text()
        self.assertLess(text.index("Gázszámla"), text.index("Adóbevallás"))  # overdue first
        self.assertNotIn("cases_morning", names(reduce("review", State.load(), now=T)))

    def test_preview_prints_and_neither_sends_nor_marks(self):
        rc, out, _ = self.run_plan(reduce("review", State(), now=T), preview=True)
        self.assertEqual(rc, 0)
        self.assertIn("Gázszámla", out)
        self.assertFalse((self.root / "data" / "outbox").exists())
        self.assertIn("cases_morning", names(reduce("review", State.load(), now=T)))

    def test_other_concerns_are_left_alone(self):
        plan = {"timestamp": T.isoformat(), "actions": [{"concern": "mine", "context": {}}]}
        rc, _, err = self.run_plan(plan)
        self.assertEqual(rc, 0)
        self.assertIn("mine", err)


class TestTickRunsTheRecordedExecutor(DeliverCase):
    def test_a_plain_tick_delivers_through_mentat_json_exec(self):
        import os
        from anytime_engine import tick
        doc = json.loads((self.root / "mentat.json").read_text())
        doc["components"]["engine"]["exec"] = f"{sys.executable} -m anytime_cases.deliver 2>/dev/null"
        (self.root / "mentat.json").write_text(json.dumps(doc))
        engine_src = Path(tick.__file__).resolve().parent.parent
        old = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = os.pathsep.join([str(self.root), str(engine_src)])
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = tick.main(["review", "--no-discover"])
        finally:
            os.environ.pop("PYTHONPATH") if old is None else os.environ.update(PYTHONPATH=old)
        self.assertEqual(rc, 0)
        self.assertTrue(list((self.root / "data" / "outbox").glob("*.md")))


class TestHungarian(DeliverCase):
    delivery = {"lang": "hu"}

    def test_labels(self):
        _, out, _ = self.run_plan(reduce("review", State(), now=T), preview=True)
        self.assertIn("Lejárt", out)
        self.assertIn("Várunk rá", out)


class TestTelegram(DeliverCase):
    delivery = {"channel": "telegram"}

    def setUp(self):
        super().setUp()
        (self.root / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=42\n")
        self.fake = FakeSend()

    def tearDown(self):
        self.fake.stop()
        super().tearDown()

    @needs_node
    def test_confirmed_send_is_marked(self):
        fake = self.fake
        rc, out, err = self.run_plan(reduce("review", State(), now=T))
        self.assertEqual(rc, 0)
        self.assertEqual(fake.sent[0]["chat_id"], "42")
        self.assertIn("Gázszámla", fake.sent[0]["text"])
        self.assertNotIn(TOKEN, out + err)
        self.assertNotIn("cases_morning", names(reduce("review", State.load(), now=T)))

    @needs_node
    def test_refused_send_stays_owed_and_fails_the_executor(self):
        os.environ["FAKE_EXIT"], os.environ["FAKE_STDERR"] = "1", "chat not found"
        rc, out, err = self.run_plan(reduce("review", State(), now=T))
        self.assertEqual(rc, 1)
        self.assertIn("chat not found", err)
        self.assertNotIn(TOKEN, out + err)
        self.assertIn("cases_morning", names(reduce("review", State.load(), now=T)))

    @needs_node
    def test_signals_are_one_message_each(self):
        doc = json.loads((self.root / "mentat.json").read_text())   # 06:00: past the
        doc["components"]["engine"]["quiet_hours"] = "22:00-06:00"  # quiet window
        (self.root / "mentat.json").write_text(json.dumps(doc))
        fake = self.fake
        rc, _, _ = self.run_plan(reduce("hourly", State(), now=T.replace(hour=6)))
        self.assertEqual(rc, 0)
        self.assertEqual(len(fake.sent), 4)
        self.assertNotIn("cases_deadline", names(reduce("hourly", State.load(), now=T.replace(hour=6))))

    @needs_node
    def test_at_morning_time_the_summary_covers_the_signals(self):
        fake = self.fake
        at7 = T.replace(hour=7, minute=0)
        plan = reduce("hourly", State(), now=at7)
        self.assertEqual(sorted(names(plan)), ["cases_deadline", "cases_morning"])
        self.assertEqual(self.run_plan(plan)[0], 0)
        self.assertEqual(len(fake.sent), 1)      # one summary, not summary + 4 signals
        self.assertEqual(names(reduce("hourly", State.load(), now=at7)), [])

    def test_missing_token_sends_nothing(self):
        (self.root / ".env").write_text("TELEGRAM_CHAT_ID=42\n")
        fake = self.fake
        rc, _, err = self.run_plan(reduce("review", State(), now=T))
        self.assertEqual((rc, fake.sent), (1, []))
        self.assertIn("TELEGRAM_BOT_TOKEN", err)


class TestQuietHours(DeliverCase):
    delivery = {"channel": "telegram"}
    quiet = None   # None: the key is absent -> the default 22:00-07:00

    def setUp(self):
        super().setUp()
        if self.quiet is not None:
            doc = json.loads((self.root / "mentat.json").read_text())
            doc["components"]["engine"]["quiet_hours"] = self.quiet
            (self.root / "mentat.json").write_text(json.dumps(doc))
        (self.root / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=42\n")
        self.fake = FakeSend()

    def tearDown(self):
        self.fake.stop()
        super().tearDown()

    def owed(self, when):
        return names(reduce("hourly", State.load(), now=when))

    @needs_node
    def test_night_signals_wait_unsent_and_unmarked(self):
        night = T.replace(hour=23)
        rc, _, err = self.run_plan(reduce("hourly", State(), now=night))
        self.assertEqual((rc, self.fake.sent), (0, []))   # not a failure: just not now
        self.assertIn("quiet", err)
        self.assertIn("cases_deadline", self.owed(night))

    @needs_node
    def test_they_go_out_when_the_window_ends(self):
        self.run_plan(reduce("hourly", State(), now=T.replace(hour=6)))
        self.assertEqual(self.fake.sent, [])
        self.run_plan(reduce("hourly", State.load(), now=T.replace(hour=7, minute=0)))
        self.assertEqual(len(self.fake.sent), 1)          # the morning, covering them
        self.assertEqual(self.owed(T.replace(hour=7, minute=0)), [])

    def test_a_file_is_written_at_night_anyway(self):
        doc = json.loads((self.root / "mentat.json").read_text())
        doc["components"]["engine"]["delivery"] = {"channel": "file"}
        (self.root / "mentat.json").write_text(json.dumps(doc))
        self.run_plan(reduce("hourly", State(), now=T.replace(hour=23)))
        self.assertTrue(list((self.root / "data" / "outbox").glob("*.md")))


class TestQuietHoursOff(TestQuietHours):
    quiet = "off"

    @needs_node
    def test_night_signals_wait_unsent_and_unmarked(self):
        rc, _, _ = self.run_plan(reduce("hourly", State(), now=T.replace(hour=23)))
        # 23:00, no quiet hours: the day's (late) morning goes out, covering the signals
        self.assertEqual((rc, len(self.fake.sent)), (0, 1))

    @needs_node
    def test_they_go_out_when_the_window_ends(self):
        pass


class TestQuietHoursCustom(TestQuietHours):
    quiet = "21:00-06:00"

    @needs_node
    def test_they_go_out_when_the_window_ends(self):
        self.run_plan(reduce("hourly", State(), now=T.replace(hour=6, minute=0)))
        self.assertEqual(len(self.fake.sent), 4)            # 06:00: window over, signals out


class TestUnavailable(DeliverCase):
    backend = "admin"   # admin chosen but not connected: the backend is unreadable

    def test_error_notice_goes_out_once_and_the_morning_stays_owed(self):
        rc, _, _ = self.run_plan(reduce("review", State(), now=T))
        self.assertEqual(rc, 0)
        text = (self.root / "data" / "outbox" / "2026-10-15.md").read_text()
        self.assertIn("could not be read", text)
        self.assertIn("cases_morning", names(reduce("review", State.load(), now=T)))
        self.run_plan(reduce("review", State.load(), now=T))
        again = (self.root / "data" / "outbox" / "2026-10-15.md").read_text()
        self.assertEqual(again.count("could not be read"), 1)


if __name__ == "__main__":
    unittest.main()
