"""What the executor says for each cases action: the text, its mark, and the items it lists.

The items matter beyond the text: their agreements (contract ids) are checked before the
text is sent (acceptance.py). A morning summary is the whole agreed set; a single reminder
is one part of it.
"""
from __future__ import annotations

from typing import Any

from . import delivery, render

WHAT = {"en": ("The morning summary of {d}", "The reminder about {t}"),
        "hu": ("A {d}-i reggeli összefoglaló", "Az emlékeztető ({t})")}


def messages(action: dict[str, Any], day: str, lang: str | None, covered: set) -> list[tuple]:
    """[(mark, text, items, what, part)] — text None: nothing (new) to say, the mark alone is
    the delivery; items: what the text lists (their agreements are checked before sending)."""
    ctx, what = action.get("context") or {}, WHAT.get(lang or "en", WHAT["en"])
    if action["concern"] == "cases_morning":
        due = ctx.get("cases.due") or {}
        if "error" in due:   # notice once a day; the morning itself stays owed
            return [(delivery.mark_name(f"cases_morning_error:{day}"),
                     render.unavailable(due["error"], lang), [], "", False)]
        items = [o for k in ("overdue", "today", "week") for o in due.get(k) or []]
        return [(due["mark"], render.morning(due, lang), items, what[0].format(d=day), False)]
    return [(s["mark"], None if (s.get("case_id"), s.get("due_at")) in covered
             else render.signal(s, lang), [s], what[1].format(t=s.get("title")), True)
            for s in ctx.get("cases.signals") or []]


def listed(action: dict[str, Any]) -> set:
    """Occurrences a morning summary names: a signal for them in the same plan
    would say it twice, so it is marked without a second message."""
    due = (action.get("context") or {}).get("cases.due") or {}
    return {(o.get("case_id"), o.get("due_at"))
            for k in ("overdue", "today", "week") for o in due.get(k) or []}
