#!/usr/bin/env python3
"""CSV deadlines in the cases pack: rows of a table count as one-off cases (read only).

The measured gap (holdout, 0.3.0): a list of payment deadlines lived in a CSV, and the agent
wrote its own executor and preview (~25 turns) because the pack only read case files. Now
`components.engine.csv_deadlines` maps the columns and a filter; the morning summary, the
deadline signals, the preview and the delivery are the pack's own. Compatible with both
pytest and direct execution.
"""
from __future__ import annotations

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
from anytime_engine.reducer import reduce  # noqa: E402
from anytime_engine.state import State  # noqa: E402

T = datetime(2026, 10, 15, 8, 30)
FEES = ("name,email,hatarido,fizetve,teendo\n"
        "Anna,anna@example.com,2026-10-14,nem,Emlékeztetni\n"
        "Bob,bob@example.com,2026.10.20.,nem,\n"
        "Péter,peter@example.com,2026-10-16,igen,\n"
        "Alice,alice@example.com,soon,nem,\n")
SOURCE = {"name": "tagdij", "path": "data/tagdij.csv", "key": "email", "title": "name",
          "due": "hatarido", "next": "teendo", "where": {"fizetve": "nem"}}


class CsvCase(CasesCase):
    files: dict = {}
    sources = [SOURCE]

    def setUp(self):
        super().setUp()
        (self.root / "data").mkdir(exist_ok=True)
        (self.root / "data" / "tagdij.csv").write_text(FEES, encoding="utf-8")
        doc = json.loads((self.root / "mentat.json").read_text())
        doc["components"]["engine"]["csv_deadlines"] = self.sources
        (self.root / "mentat.json").write_text(json.dumps(doc))

    def context(self, concern, provider, trigger="review"):
        plan = reduce(trigger, State(), now=T)
        return next(a for a in plan["actions"] if a["concern"] == concern)["context"][provider]


class TestRows(CsvCase):
    def test_filtered_rows_are_due_items_with_their_row(self):
        due = self.context("cases_morning", "cases.due")
        self.assertEqual([o["title"] for o in due["overdue"]], ["Anna"])
        self.assertEqual([(o["title"], o["due_at"]) for o in due["week"]], [("Bob", "2026-10-20")])
        anna = due["overdue"][0]
        self.assertEqual(anna["case_id"], "csv:tagdij:anna@example.com")
        self.assertEqual(anna["next_action"], "Emlékeztetni")
        self.assertEqual(anna["row"], {"email": "anna@example.com", "name": "Anna",
                                       "hatarido": "2026-10-14", "teendo": "Emlékeztetni"})
        self.assertEqual(due["scanned"]["csv_rows"], 2)
        self.assertNotIn("Péter", json.dumps(due, ensure_ascii=False))

    def test_an_unreadable_date_is_named_with_its_line(self):
        due = self.context("cases_morning", "cases.due")
        self.assertIn({"file": "data/tagdij.csv:5", "error": "hatarido: 'soon' is not a date"}, due["invalid"])

    def test_signals_come_from_the_rows_too(self):
        sig = self.context("cases_deadline", "cases.signals", trigger="hourly")
        self.assertEqual([(s["title"], s["kind"]) for s in sig], [("Anna", "due")])


class TestMissingFile(CsvCase):
    sources = [dict(SOURCE, path="data/nincs.csv"), dict(SOURCE, name="rossz", title=None)]

    def test_a_missing_file_or_a_bad_mapping_is_invalid_not_silent(self):
        due = self.context("cases_morning", "cases.due")
        files = [i["file"] for i in due["invalid"]]
        self.assertIn("data/nincs.csv", files)
        self.assertIn("components.engine.csv_deadlines[1]", files)


if __name__ == "__main__":
    unittest.main()
