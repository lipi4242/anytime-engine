"""The delivery-state contract, on the engine's receipts (receipts.py).

A message counts as delivered only when the executor, AFTER a confirmed send,
records it:  python3 -m anytime_engine.tick --mark delivered:<key>
Any other result (`--result unknown`: sent, but not confirmed) leaves it owed,
so the next tick retries it — a rare double message over a missed one, by
design. `delivered:` receipts are never overlaid on the concern timers.
"""
from __future__ import annotations

from anytime_engine import receipts


def mark_name(key: str) -> str:
    return receipts.DELIVERY_PREFIX + key


def delivered() -> set[str]:
    return {name for name, rec in receipts.latest().items()
            if name.startswith(receipts.DELIVERY_PREFIX) and rec.get("result") == "ok"}
