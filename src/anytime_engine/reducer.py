"""Reducer v2 — event-driven concern dispatcher.

Pure Python. No LLM. Evaluates concerns, sorts by dependencies,
assembles context, and returns an ordered action plan.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .state import State
from .registry import resolve, all_concerns
from .assembler import assemble, context_errors


def reduce(trigger: str, state: State) -> dict[str, Any]:
    """Evaluate all concerns for a trigger and return an action plan.

    This is the core decision engine. It:
    1. Filters concerns by trigger type
    2. Evaluates should_run() for each (pure Python)
    3. Topologically sorts by dependencies
    4. Assembles context for each action
    5. Returns the plan as JSON-serializable dict

    No LLM calls happen here. The agent executor handles that.
    """
    now = datetime.now()
    state.last_trigger = trigger
    state.last_trigger_at = now.isoformat()

    all_registered = all_concerns()

    # Find which concerns are relevant but won't run
    skipped: dict[str, str] = {}
    for name, concern in all_registered.items():
        if trigger in concern.triggers and not concern.should_run(state):
            skipped[name] = _skip_reason(name, state)

    # Resolve to ordered levels
    levels = resolve(trigger, state)

    # Build action list with context
    actions: list[dict[str, Any]] = []
    action_names: set[str] = set()
    degraded: list[dict[str, str]] = []  # providers that failed this reduce
    for level_idx, level in enumerate(levels):
        for concern in level:
            ctx = assemble(concern.context_needs, state)
            for err in context_errors(ctx):
                degraded.append({"concern": concern.name, **err})
            if concern.name == "review_email":
                ctx["review_type"] = state.review_type()
            actions.append({
                "concern": concern.name,
                "description": concern.description,
                "action": concern.action,
                "context": ctx,
                "context_needs": concern.context_needs,
                "level": level_idx,
                "state_keys": concern.state_keys,
            })
            action_names.add(concern.name)

    # Remove from skipped if pulled in by dependency resolution
    for name in action_names:
        skipped.pop(name, None)

    return {
        "trigger": trigger,
        "timestamp": now.isoformat(),
        "actions": actions,
        "skipped": list(skipped.keys()),
        "skip_reasons": skipped,
        "context_errors": degraded,  # degraded providers this reduce (empty = clean)
        "state_summary": state.summary(),
    }


def _skip_reason(concern_name: str, state: State) -> str:
    """Human-readable reason why a concern was skipped."""
    last = state.concern_last_run.get(concern_name)
    if last:
        age = datetime.now() - datetime.fromisoformat(last)
        minutes = int(age.total_seconds() / 60)
        return f"ran {minutes} min ago"
    return "should_run returned False"
