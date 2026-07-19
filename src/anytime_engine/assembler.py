"""Context assembler — builds focused context for each concern's execution."""

from __future__ import annotations

from typing import Any, Callable

from .state import State


# Provider registry: name -> callable that returns data
_PROVIDERS: dict[str, Callable[..., Any]] = {}


def provider(name: str):
    """Decorator to register a context provider."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _PROVIDERS[name] = fn
        return fn
    return decorator


def register_provider(name: str, fn: Callable[..., Any]) -> None:
    """Register a context provider imperatively."""
    _PROVIDERS[name] = fn


def get_provider(name: str) -> Callable[..., Any] | None:
    """Get a registered provider."""
    return _PROVIDERS.get(name)


def all_providers() -> dict[str, Callable[..., Any]]:
    """Return all registered providers."""
    return dict(_PROVIDERS)


def clear_providers() -> None:
    """Clear provider registry (for testing)."""
    _PROVIDERS.clear()


def assemble(context_needs: list[str], state: State) -> dict[str, Any]:
    """Assemble context by calling each needed provider.

    Providers receive the state object so they can check/update caches.
    If a provider fails, its key maps to {"error": str}.
    """
    context: dict[str, Any] = {}

    for need in context_needs:
        p = _PROVIDERS.get(need)
        if p is None:
            context[need] = {"error": f"No provider registered for '{need}'"}
            continue

        try:
            context[need] = p(state)
        except Exception as e:
            context[need] = {"error": f"{type(e).__name__}: {e}"}

    return context


def context_errors(context: dict[str, Any]) -> list[dict[str, str]]:
    """Return the providers that failed in an assembled context.

    The "providers never raise" convention keeps ticks running, but a dead
    provider reads downstream as "0 events" / "not available" — indistinguishable
    from genuinely empty. This surfaces the difference so callers (tick log,
    the review email's degraded-run banner) can make degradation visible instead
    of silently blind. Returns [{provider, error}, ...] (empty on a clean run).
    """
    errors: list[dict[str, str]] = []
    for key, value in context.items():
        if isinstance(value, dict) and "error" in value and len(value) == 1:
            errors.append({"provider": key, "error": str(value["error"])})
    return errors
