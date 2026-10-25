#!/usr/bin/env python3
"""Before a message goes out, the executor runs the brain's acceptance check for every
agreement (contract) the message's items carry. Red: nothing is sent, the user gets one short
"not sent, because …" note, and the message stays owed. No contract: sent as before, and the
executor says it was not checked. No brain checker: a contract cannot be checked, so it does
not go out.

The measured gap (holdout, 0.3.0): a scheduled morning list went out with the wrong names and
nobody looked at it before it was sent. Compatible with both pytest and direct execution.
"""
from __future__ import annotations

import contextlib
import io
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

from test_cases_csv import FEES, SOURCE, T, CsvCase  # noqa: E402
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.state import State  # noqa: E402

# A stand-in for the brain's .mentat/bin/mentat_accept.py: logs its call, answers from a file.
FAKE = r'''
import json, pathlib, sys
args = sys.argv[1:]
root = pathlib.Path(args[args.index("--repo") + 1])
out = json.loads(pathlib.Path(args[-1]).read_text())
with open(root / "accept-calls.jsonl", "a") as f:
    f.write(json.dumps({"args": args[:-1], "output": out}) + "\n")
ans = json.loads((root / "accept-answer.json").read_text())
print(ans["line"])
sys.exit(ans["exit"])
'''


class AcceptCase(CsvCase):
    sources = [dict(SOURCE, contract="tagdij")]
    checker = True

    def setUp(self):
        super().setUp()
        if self.checker:
            (self.root / ".mentat" / "bin").mkdir(parents=True)
            (self.root / ".mentat" / "bin" / "mentat_accept.py").write_text(FAKE)
        self.answer(0, "GREEN — this would go out: 2 rows (email, name, hatarido, teendo) to no one (a file).")
        from anytime_cases import deliver
        self.deliver = deliver

    def answer(self, code, line):
        (self.root / "accept-answer.json").write_text(json.dumps({"exit": code, "line": line}))

    def calls(self):
        p = self.root / "accept-calls.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def outbox(self):
        p = self.root / "data" / "outbox" / "2026-10-15.md"
        return p.read_text() if p.exists() else ""

    def run_plan(self, trigger="review", **kw):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(err):
            rc = self.deliver.run(reduce(trigger, State.load(), now=T), **kw)
        return rc, out.getvalue(), err.getvalue()

    def owed(self, concern="cases_morning"):
        return concern in [a["concern"] for a in reduce("review", State.load(), now=T)["actions"]]


class TestChecked(AcceptCase):
    def test_green_is_sent_and_the_check_saw_the_rows_that_go_out(self):
        rc, _, err = self.run_plan()
        self.assertEqual(rc, 0, err)
        self.assertIn("Anna", self.outbox())
        call = self.calls()[0]
        self.assertEqual(call["args"][-1], "tagdij")
        self.assertEqual(sorted(r["email"] for r in call["output"]["records"]), ["anna@example.com", "bob@example.com"])
        self.assertIn("Anna", call["output"]["message"])
        self.assertIn("checked against tagdij: GREEN", err)
        self.assertFalse(self.owed())

    def test_red_sends_only_a_short_note_once_and_the_message_stays_owed(self):
        self.answer(1, "RED — do not send it. Problems:\n- it has a record that is not eligible: peter@example.com")
        rc, _, err = self.run_plan()
        self.assertEqual(rc, 0, err)
        box = self.outbox()
        self.assertNotIn("Anna", box)
        self.assertIn("was not sent", box)
        self.assertIn("peter@example.com", box)
        self.assertTrue(self.owed())
        self.run_plan()
        self.assertEqual(self.outbox().count("was not sent"), 1)
        self.answer(0, "GREEN — fixed")
        self.run_plan()
        self.assertIn("Anna", self.outbox())
        self.assertFalse(self.owed())

    def test_preview_shows_the_verdict_and_sends_nothing(self):
        self.answer(1, "RED — a date is outside the agreed window: 2026-10-20")
        rc, out, _ = self.run_plan(preview=True)
        self.assertEqual(rc, 0)
        self.assertIn("would NOT be sent", out)
        self.assertIn("2026-10-20", out)
        self.assertEqual(self.outbox(), "")


class TestUnchecked(AcceptCase):
    sources = [SOURCE]

    def test_without_a_contract_it_goes_as_before_and_says_unchecked(self):
        rc, _, err = self.run_plan()
        self.assertEqual(rc, 0)
        self.assertIn("Anna", self.outbox())
        self.assertIn("not checked: no agreement", err)
        self.assertEqual(self.calls(), [])


class TestNoChecker(AcceptCase):
    checker = False

    def test_a_contract_without_the_brain_checker_does_not_go_out(self):
        rc, _, err = self.run_plan()
        self.assertEqual(rc, 0, err)
        self.assertNotIn("Anna", self.outbox())
        self.assertIn("mentat_accept.py", self.outbox())
        self.assertTrue(self.owed())


class TestCaseFileContract(AcceptCase):
    sources = []
    files = {"ado.md": ("---\ntype: case\ncase_id: ADO1\ntitle: Adóbevallás\nstatus: open\n"
                        "due_at: 2026-10-17\ncontract: ado\n---\n")}

    def test_a_single_reminder_is_checked_as_a_part_of_the_agreed_set(self):
        self.run_plan()                   # the morning: the whole set
        self.run_plan(trigger="hourly")   # later: the reminder alone
        self.assertEqual(["--part" in c["args"] for c in self.calls()], [False, True])

    def test_a_case_file_can_carry_the_contract(self):
        self.run_plan()
        self.assertEqual(self.calls()[0]["args"][-1], "ado")
        self.assertEqual(self.calls()[0]["output"]["records"][0]["title"], "Adóbevallás")


MENTAT_SRC = os.environ.get("MENTAT_SRC")   # .../mentat-ai-bootstrap-dev/release/reference/manifest


@unittest.skipUnless(MENTAT_SRC, "MENTAT_SRC not set: the real brain checker is not tried")
class TestRealChecker(AcceptCase):
    checker = False

    def setUp(self):
        super().setUp()
        shutil.copytree(MENTAT_SRC, self.root / ".mentat" / "bin", ignore=shutil.ignore_patterns("test_*", "_*"))
        (self.root / "agy").mkdir(exist_ok=True)
        terms = {"goal": "Who has not paid the fee, every morning.", "fields": ["email", "name", "hatarido", "teendo"],
                 "records": {"source": "data/tagdij.csv", "key": "email", "where": {"fizetve": "nem"}}}
        (self.root / "p.json").write_text(json.dumps(terms))
        tool = [sys.executable, str(self.root / ".mentat/bin/mentat_contract.py"), "--repo", str(self.root)]
        env = dict(os.environ, HOME=str(self.root / "home"))
        subprocess.run(tool + ["draft", "tagdij", "--file", str(self.root / "p.json")], check=True, capture_output=True, env=env)
        subprocess.run(tool + ["approve", "tagdij", "--quote", "igen"], check=True, capture_output=True, env=env)

    def test_the_real_checker_lets_the_right_rows_through_and_stops_a_wrong_filter(self):
        _, out, err = self.run_plan(preview=True)   # Alice's date is unreadable: the list lacks her
        self.assertIn("would NOT be sent", out, err)
        self.assertIn("alice@example.com", out)
        (self.root / "data" / "tagdij.csv").write_text(FEES.replace(",soon,", ",2026-10-21,"), encoding="utf-8")
        _, out, err = self.run_plan(preview=True)
        self.assertIn("[check] would be sent", out, err)
        doc = json.loads((self.root / "mentat.json").read_text())
        doc["components"]["engine"]["csv_deadlines"] = [dict(SOURCE, contract="tagdij", where={})]
        (self.root / "mentat.json").write_text(json.dumps(doc))
        _, out, err = self.run_plan(preview=True)   # the filter dropped: Péter would be listed
        self.assertIn("would NOT be sent", out, err)
        self.assertIn("peter@example.com", out)

if __name__ == "__main__":
    unittest.main()
