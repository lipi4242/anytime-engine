"""Concerns `cases_morning` and `cases_deadline` with their @action prompts.

cases_morning   once a day: overdue / due today / this week / waiting. Planned
                by a review tick at any time, and by an hourly tick from the
                `morning` time on (mentat.json components.engine.morning or
                ANYTIME_CASES_MORNING, default 07:00, agent-local time) — so an
                hourly-only schedule (the fleet's) brings it too. Owed until
                delivered:cases_morning:<date> is marked — so a morning whose
                provider failed is not counted as done, and the next tick
                makes it up.
cases_deadline  hourly, only while a signal is owed (due.signals): one message
                per occurrence N days before (`upcoming`) and from its day on
                (`due`). An unreadable backend plans nothing here; the error
                shows in the morning summary and in the plan's context_errors.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from anytime_engine import engine_manifest
from anytime_engine.prompts import action, format_context
from anytime_engine.registry import Concern, register

from . import delivery
from .due import signals
from .source import CasesUnavailable


def morning_at() -> str:
    raw = (os.environ.get("ANYTIME_CASES_MORNING")
           or engine_manifest.section().get("morning") or "07:00")
    return datetime.strptime(str(raw), "%H:%M").strftime("%H:%M")   # 7:00 -> 07:00


def _morning_owed(state) -> bool:
    if state.last_trigger != "review" and state.now().strftime("%H:%M") < morning_at():
        return False
    return delivery.mark_name(f"cases_morning:{state.now().date().isoformat()}") \
        not in delivery.delivered()


def _signals_owed(state) -> bool:
    try:
        return bool(signals(state))
    except CasesUnavailable:
        return False


register(Concern(
    name="cases_morning", description="Morning overview of the cases: overdue, today, this week, waiting.",
    triggers=["review", "hourly"], should_run=_morning_owed, context_needs=["cases.due"],
    action="cases_morning", staleness_minutes=24 * 60))

register(Concern(
    name="cases_deadline", description="One message per case occurrence before and at its due date.",
    triggers=["hourly"], should_run=_signals_owed, context_needs=["cases.signals"],
    action="cases_deadline", staleness_minutes=60))

_DELIVERY = ("Delivery contract: after the message is CONFIRMED sent, run "
             "`python3 -m anytime_engine.tick --mark {mark}`. Not confirmed → "
             "`--result unknown` (it will be retried). Never mark what was not sent.")


@action("cases_morning")
def cases_morning_prompt(ctx: dict[str, Any]) -> str:
    data = ctx.get("cases.due") or ctx
    if isinstance(data, dict) and "error" in data:
        return ("# Cases — morning overview\n\nThe cases backend is UNAVAILABLE: "
                f"{data['error']}\nTell the user the cases could not be read (do not "
                "list cases from memory or from other files). Do NOT mark this delivered.")
    return ("# Cases — morning overview\n\nSend the user a short overview: overdue first "
            "(each overdue occurrence separately), then due today, then this week, then "
            "what we are waiting on, each with its next step. Mention invalid case files.\n\n"
            + _DELIVERY.format(mark=data.get("mark")) + "\n\n" + format_context(data))


@action("cases_deadline")
def cases_deadline_prompt(ctx: dict[str, Any]) -> str:
    data = ctx.get("cases.signals") or ctx
    return ("# Cases — deadline signals\n\nSend one short message per signal: `upcoming` "
            "= due in `days` days, `due` = due today or overdue. Mark each signal by its "
            "own `mark` value, one by one, only after its send is confirmed.\n\n"
            + _DELIVERY.format(mark="<signal.mark>") + "\n\n" + format_context(data))
