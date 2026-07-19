"""Topological sort for concern dependency resolution."""

from __future__ import annotations
from collections import defaultdict, deque


class CyclicDependencyError(Exception):
    """Raised when concerns have circular dependencies."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency: {' -> '.join(cycle)}")


def topo_sort(concerns: dict[str, list[str]]) -> list[list[str]]:
    """Sort concerns into dependency levels using Kahn's algorithm.

    Args:
        concerns: {name: [dependency_names]}

    Returns:
        List of levels, each a list of concern names that can run in parallel.
        Level 0 has no dependencies, level 1 depends only on level 0, etc.

    Raises:
        CyclicDependencyError: If circular dependencies exist.
    """
    # Build adjacency and in-degree
    in_degree: dict[str, int] = defaultdict(int)
    dependents: dict[str, list[str]] = defaultdict(list)

    for name in concerns:
        in_degree.setdefault(name, 0)

    for name, deps in concerns.items():
        for dep in deps:
            if dep not in concerns:
                raise ValueError(f"Concern '{name}' depends on unknown '{dep}'")
            dependents[dep].append(name)
            in_degree[name] += 1

    # Kahn's algorithm with level tracking
    queue: deque[str] = deque()
    for name, degree in in_degree.items():
        if degree == 0:
            queue.append(name)

    levels: list[list[str]] = []
    processed = 0

    while queue:
        # All items currently in queue form one level
        level = sorted(queue)  # sorted for determinism
        queue.clear()

        for name in level:
            processed += 1
            for dependent in dependents[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        levels.append(level)

    if processed != len(concerns):
        # Find the cycle for a useful error message
        remaining = [n for n in concerns if in_degree[n] > 0]
        raise CyclicDependencyError(remaining)

    return levels
