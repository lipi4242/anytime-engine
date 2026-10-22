"""Plain-text messages from the providers' data — no model, same input same text.

`morning(due)` renders the cases.due context (None when there is nothing to
say), `signal(sig)` one cases.signals item, `unavailable(error)` the notice
for an unreadable backend. Language: components.engine.delivery.lang (en|hu).
"""
from __future__ import annotations

from typing import Any

LABELS = {
    "en": {"title": "Cases — {d}", "overdue": "Overdue", "today": "Due today",
           "week": "This week", "waiting": "Waiting on", "invalid": "Unreadable case file",
           "ago": "{n} days overdue", "in": "in {n} days", "on": "today",
           "up": "Due in {n} days", "due": "Due today", "late": "Overdue ({n} days)",
           "down": "The cases could not be read ({e}). Nothing is listed from memory."},
    "hu": {"title": "Ügyek — {d}", "overdue": "Lejárt", "today": "Ma esedékes",
           "week": "A héten", "waiting": "Várunk rá", "invalid": "Olvashatatlan ügyfájl",
           "ago": "{n} napja lejárt", "in": "{n} nap múlva", "on": "ma",
           "up": "{n} nap múlva esedékes", "due": "Ma esedékes", "late": "Lejárt ({n} napja)",
           "down": "Az ügyeket nem sikerült beolvasni ({e}). Fejből nem sorolok fel semmit."},
}


def labels(lang: str | None) -> dict[str, str]:
    return LABELS.get(lang or "en", LABELS["en"])


def _when(o: dict[str, Any], t: dict[str, str]) -> str:
    n = o.get("days", 0)
    rel = t["ago"].format(n=-n) if n < 0 else t["on"] if n == 0 else t["in"].format(n=n)
    return f"{o['due_at']}, {rel}"


def _line(o: dict[str, Any], t: dict[str, str] | None = None) -> str:
    head = o.get("title") or o.get("case_id") or "?"
    if t is not None and o.get("due_at"):
        head += f" ({_when(o, t)})"
    nxt = o.get("next_action")
    return f"- {head}" + (f" — {nxt}" if nxt else "")


def morning(due: dict[str, Any], lang: str | None = None) -> str | None:
    t = labels(lang)
    out = []
    for key in ("overdue", "today", "week"):
        if due.get(key):
            out += ["", t[key] + ":"] + [_line(o, t) for o in due[key]]
    if due.get("waiting"):
        out += ["", t["waiting"] + ":"] + [_line(w) for w in due["waiting"]]
    for bad in due.get("invalid") or []:
        out += ["", f"{t['invalid']}: {bad.get('file')} ({bad.get('error')})"]
    if not out:
        return None
    return "\n".join([t["title"].format(d=due.get("as_of", ""))] + out) + "\n"


def signal(sig: dict[str, Any], lang: str | None = None) -> str:
    t = labels(lang)
    n = sig.get("days", 0)
    head = t["up"].format(n=n) if n > 0 else t["due"] if n == 0 else t["late"].format(n=-n)
    title = sig.get("title") or sig.get("case_id")
    nxt = sig.get("next_action")
    return f"{head}: {title} ({sig.get('due_at')})" + (f" — {nxt}" if nxt else "") + "\n"


def unavailable(error: str, lang: str | None = None) -> str:
    return labels(lang)["down"].format(e=error) + "\n"
