"""Action prompt registry + shared prompt-formatting helpers.

Each concern co-locates its action prompt in the agent repo's
`concerns/<name>.py` using the @action decorator. The registry is populated
at import time when concerns are auto-discovered.
"""
from __future__ import annotations

import json
from typing import Any

ACTION_PROMPTS: dict[str, Any] = {}


def action(name: str):
    """Decorator: register an action prompt function in ACTION_PROMPTS."""
    def decorator(fn):
        ACTION_PROMPTS[name] = fn
        return fn
    return decorator


def get_prompt(action_name: str, context: dict[str, Any]) -> str:
    """Get the execution prompt for an action with its context."""
    fn = ACTION_PROMPTS.get(action_name)
    if fn is None:
        return f"Unknown action: {action_name}. No prompt available."
    return fn(context)


# ── Shared helpers used by multiple action prompts ─────────────────────


def count(data: Any) -> str:
    """Safe count for context data that might be a list, dict, or error."""
    if isinstance(data, list):
        return str(len(data))
    if isinstance(data, dict) and "error" in data:
        return "(unavailable)"
    return "?"


def format_context(data: Any) -> str:
    """Format context data for inclusion in prompts."""
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        if not data:
            return "(none)"
        return json.dumps(data[:20], indent=2, ensure_ascii=False, default=str)
    if isinstance(data, dict):
        if not data:
            return "(none)"
        if "error" in data:
            return f"(error: {data['error']})"
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)
    return str(data)
