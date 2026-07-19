"""Concern registry — auto-discovers and validates concern plugins."""

from __future__ import annotations

import importlib
import pkgutil
import sys
from dataclasses import dataclass, field
from typing import Callable, Any

from .state import State
from .topo_sort import topo_sort, CyclicDependencyError
from .assembler import all_providers


@dataclass
class Concern:
    """A self-contained unit of work in the reducer."""

    # Identity
    name: str
    description: str

    # When to run
    triggers: list[str]
    should_run: Callable[[State], bool]

    # Dependencies (other concern names)
    depends_on: list[str] = field(default_factory=list)

    # Context assembly
    context_needs: list[str] = field(default_factory=list)

    # Execution
    action: str = ""  # prompt key or skill name

    # State keys this concern reads/writes
    state_keys: list[str] = field(default_factory=list)

    # Staleness threshold in minutes (how long before re-running)
    staleness_minutes: int = 60


# Global registry
_CONCERNS: dict[str, Concern] = {}


def register(concern: Concern) -> Concern:
    """Register a concern. Returns the concern for decorator use."""
    if concern.name in _CONCERNS:
        raise ValueError(f"Duplicate concern name: {concern.name}")
    _CONCERNS[concern.name] = concern
    return concern


def get(name: str) -> Concern:
    """Get a registered concern by name."""
    return _CONCERNS[name]


def all_concerns() -> dict[str, Concern]:
    """Return all registered concerns."""
    return dict(_CONCERNS)


def clear() -> None:
    """Clear registry (for testing)."""
    _CONCERNS.clear()


def discover(plugin_packages: list[str] | None = None) -> None:
    """Auto-discover and import all concern and provider modules.

    `plugin_packages` is the list of package dotted-paths holding the agent's
    concern/provider modules (e.g. ["scripts.anytime.v2.concerns",
    "scripts.anytime.v2.providers"]). Falls back to the ANYTIME_PLUGINS env
    var (comma-separated). The engine has no default — the agent repo must
    say where its plugins live.

    Reloads already-imported modules so that self-registration
    decorators re-fire after a registry clear (important for testing).
    """
    import os
    if plugin_packages is None:
        raw = os.environ.get("ANYTIME_PLUGINS", "")
        plugin_packages = [p.strip() for p in raw.split(",") if p.strip()]
    if not plugin_packages:
        raise ValueError(
            "discover(): no plugin packages — pass plugin_packages or set ANYTIME_PLUGINS"
        )

    for pkg_name in plugin_packages:
        pkg = importlib.import_module(pkg_name)
        for _importer, modname, _ispkg in pkgutil.iter_modules(pkg.__path__):
            full_name = f"{pkg_name}.{modname}"
            if full_name in sys.modules:
                importlib.reload(sys.modules[full_name])
            else:
                importlib.import_module(full_name)


def find_foreign_registries() -> list[tuple[str, list[str]]]:
    """Detect a second, populated concern registry living in another module.

    Vendoring copies files with generic basenames (`registry.py`, `state.py`)
    into the consumer's repo. If that repo already has a hand-rolled reducer of
    the same shape, a concern importing `register` from the *other* copy calls a
    different `register()` backed by a different `_CONCERNS` dict. It registers
    without error into a dict nothing downstream reads — silently inert, and
    invisible to validate(), which only inspects its own `_CONCERNS`.

    We can't prevent a second copy, but we can see it: scan sys.modules for any
    module exposing a `_CONCERNS` dict that is a *different, non-empty* object
    from ours. Returns (module_name, [concern_names]) per foreign registry.
    A clean single-copy install returns []; an empty second copy (e.g. a
    re-export shim keeping its own empty dict) is harmless and not reported.
    """
    foreign: list[tuple[str, list[str]]] = []
    for mod_name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        other = getattr(mod, "_CONCERNS", None)
        if isinstance(other, dict) and other is not _CONCERNS and other:
            foreign.append((mod_name, sorted(other.keys())))
    return foreign


def validate() -> list[str]:
    """Validate the registry. Returns list of errors (empty = valid)."""
    errors = []

    # Split-registry guard: a second populated registry in memory means concerns
    # registered into a copy nothing downstream reads (see find_foreign_registries).
    # Surface it loudly instead of returning a false green.
    for mod_name, names in find_foreign_registries():
        errors.append(
            f"split registry: '{mod_name}' holds {len(names)} concern(s) "
            f"({', '.join(names)}) in a separate _CONCERNS dict this engine will "
            f"never read. A concern is importing `register` from a different copy "
            f"of the registry. Import from a single registry module, or make the "
            f"local copy a re-export shim of anytime_engine.registry."
        )

    # Check all dependencies exist
    for name, concern in _CONCERNS.items():
        for dep in concern.depends_on:
            if dep not in _CONCERNS:
                errors.append(f"'{name}' depends on unknown concern '{dep}'")

    # Check for cycles
    dep_graph = {name: c.depends_on for name, c in _CONCERNS.items()}
    try:
        topo_sort(dep_graph)
    except CyclicDependencyError as e:
        errors.append(str(e))

    # Check valid trigger types
    valid_triggers = {"hourly", "review", "telegram", "startup", "webhook"}
    for name, concern in _CONCERNS.items():
        for trigger in concern.triggers:
            if trigger not in valid_triggers:
                errors.append(f"'{name}' has unknown trigger '{trigger}'")

    # Check that all context_needs have registered providers
    providers = all_providers()
    for name, concern in _CONCERNS.items():
        for need in concern.context_needs:
            if need not in providers:
                errors.append(f"'{name}' needs provider '{need}' but none is registered")

    return errors


def resolve(trigger: str, state: State) -> list[list[Concern]]:
    """Resolve which concerns to run for a trigger, sorted by dependency level.

    Returns list of levels, each containing concerns that can run in parallel.
    Only includes concerns whose should_run() returns True.
    """
    # Filter to relevant concerns
    candidates = {
        name: concern
        for name, concern in _CONCERNS.items()
        if trigger in concern.triggers and concern.should_run(state)
    }

    if not candidates:
        return []

    # Include transitive dependencies only if they haven't run recently.
    # If a dependency ran recently (not stale), the dependent can use cached data.
    to_include = set(candidates.keys())
    changed = True
    while changed:
        changed = False
        for name in list(to_include):
            for dep in _CONCERNS[name].depends_on:
                if dep not in to_include and dep in _CONCERNS:
                    # Force a dependency in only if it BOTH is stale (its own
                    # threshold) AND would itself run under this trigger/state.
                    # Without the should_run guard, a stale time-of-day-specific
                    # concern (e.g. one whose should_run requires the morning
                    # review) gets pulled into an evening review and executes at
                    # the wrong time — silently, since it looks like a normal
                    # planned action. A dep that declined via should_run has no
                    # fresh data to offer anyway; the dependent uses cached data.
                    dep_concern = _CONCERNS[dep]
                    if (
                        state.is_stale(dep, dep_concern.staleness_minutes)
                        and dep_concern.should_run(state)
                    ):
                        to_include.add(dep)
                        candidates[dep] = _CONCERNS[dep]
                        changed = True

    # Topological sort — only include deps that are in the candidate set.
    # Fresh (non-stale) dependencies are intentionally excluded; their
    # cached data is still valid and available to the dependent concern.
    dep_graph = {
        name: [d for d in c.depends_on if d in candidates]
        for name, c in candidates.items()
    }
    levels = topo_sort(dep_graph)

    # Convert back to Concern objects
    return [
        [candidates[name] for name in level]
        for level in levels
    ]
