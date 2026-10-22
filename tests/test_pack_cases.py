#!/usr/bin/env python3
"""The cases concern pack on the markdown backend.

Fixed clock -> deterministic plans; a signal goes out once (a `delivered:`
receipt written by the executor after a confirmed send), an `unknown` result is
retried, and the delivery receipts never leak into the concern timers.

Compatible with both pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import contextlib
import io
import json
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
from anytime_engine import tick  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.registry import validate  # noqa: E402
from anytime_engine.state import State  # noqa: E402

T = datetime(2026, 10, 15, 8, 30)


def action(plan, name):
    return next((a for a in plan["actions"] if a["concern"] == name), None)


def mark(*keys, result="ok"):
    argv = [x for k in keys for x in ("--mark", k)] + ["--result", result]
    with contextlib.redirect_stdout(io.StringIO()):
        assert tick.main(argv) == 0


class TestMorning(CasesCase):
    def test_pack_validates(self):
        self.assertEqual(validate(), [])

    def test_plan_is_a_function_of_the_clock(self):
        a = json.dumps(reduce("review", State(), now=T)["actions"], sort_keys=True)
        b = json.dumps(reduce("review", State(), now=T)["actions"], sort_keys=True)
        self.assertEqual(a, b)

    def test_buckets(self):
        due = action(reduce("review", State(), now=T), "cases_morning")["context"]["cases.due"]
        pick = lambda b: [(o["case_id"], o["due_at"]) for o in due[b]]  # noqa: E731
        self.assertEqual(due["as_of"], "2026-10-15")
        self.assertEqual(pick("overdue"), [("01JAB6Z9Q3M8K7T2V5W4X1Y0RS", "2026-09-10"),
                                           ("01JAB6Z9Q3M8K7T2V5W4X1Y0RS", "2026-10-10")])
        self.assertEqual(pick("today"), [("KAR1", "2026-10-15")])
        self.assertEqual(pick("week"), [("ADO1", "2026-10-17")])
        self.assertEqual([c["case_id"] for c in due["waiting"]], ["KAR1"])
        self.assertEqual([i["file"] for i in due["invalid"]], ["agy/cases/rossz.md"])
        # The base model: a description travels with each occurrence; an older
        # file's waiting_on (dropped from the model) still says what we wait for.
        self.assertEqual(due["overdue"][0]["description"], "A havi gázszámla")
        self.assertEqual(due["waiting"][0]["next_action"], "a biztosító")
        self.assertTrue(all("waiting_on" not in o for o in due["overdue"] + due["today"] + due["waiting"]))

    def test_quarterly_case_lists_each_open_quarter(self):
        from anytime_cases.due import open_dates
        from datetime import date
        vat = {"status": "open", "recurrence": "quarterly:20", "anchor_at": "2026-01-20",
               "occurrences": [{"due_at": "2026-01-20", "status": "done"}]}
        self.assertEqual(open_dates(vat, date(2026, 10, 31)),
                         [date(2026, 4, 20), date(2026, 7, 20), date(2026, 10, 20)])

    def test_one_off_case(self):
        due = action(reduce("review", State(), now=T), "cases_morning")["context"]["cases.due"]
        ado = [o for o in due["week"] if o["case_id"] == "ADO1"]
        self.assertEqual([(o["due_at"], o["days"]) for o in ado], [("2026-10-17", 2)])

    def test_morning_goes_out_once_a_day(self):
        self.assertIsNotNone(action(reduce("review", State(), now=T), "cases_morning"))
        mark("delivered:cases_morning:2026-10-15")
        self.assertIsNone(action(reduce("review", State.load(), now=T), "cases_morning"))
        nxt = T.replace(day=16)
        self.assertIsNotNone(action(reduce("review", State.load(), now=nxt), "cases_morning"))


class TestDeadline(CasesCase):
    def signals(self, now=T):
        a = action(reduce("hourly", State.load(), now=now), "cases_deadline")
        return None if a is None else [s["mark"] for s in a["context"]["cases.signals"]]

    def test_due_and_upcoming_signals(self):
        self.assertEqual(self.signals(), [
            "delivered:cases:01JAB6Z9Q3M8K7T2V5W4X1Y0RS:2026-09-10:due",
            "delivered:cases:01JAB6Z9Q3M8K7T2V5W4X1Y0RS:2026-10-10:due",
            "delivered:cases:KAR1:2026-10-15:due",
            "delivered:cases:ADO1:2026-10-17:upcoming",
        ])

    def test_a_delivered_signal_is_not_repeated(self):
        first = self.signals()
        mark(*first[:2])
        self.assertEqual(self.signals(), first[2:])
        mark(*first[2:])
        self.assertIsNone(self.signals())   # nothing pending: not planned at all

    def test_unknown_delivery_is_retried(self):
        first = self.signals()
        mark(first[0], result="unknown")
        self.assertEqual(self.signals(), first)

    def test_upcoming_then_due_are_two_signals(self):
        mark(*self.signals())
        self.assertEqual(self.signals(T.replace(day=17)),
                         ["delivered:cases:ADO1:2026-10-17:due"])

    def test_delivery_receipts_do_not_become_concern_timers(self):
        mark(*self.signals())
        s = State.load()
        self.assertFalse([k for k in s.concern_last_run if k.startswith("delivered:")])


class TestMonthEnd(CasesCase):
    files = {"m.md": "---\ntype: case\ncase_id: M31\ntitle: Bérleti díj\nstatus: open\n"
                     "recurrence: monthly:31\nanchor_at: 2026-10-31\n"
                     "occurrences:\n  - due_at: 2026-10-31\n    status: done\n---\n"}

    def test_november_31_is_the_30th(self):
        a = action(reduce("hourly", State(), now=datetime(2026, 11, 28, 9)), "cases_deadline")
        self.assertEqual([s["mark"] for s in a["context"]["cases.signals"]],
                         ["delivered:cases:M31:2026-11-30:upcoming"])


if __name__ == "__main__":
    unittest.main()
