"""Concern packs — the minimal loading contract (docs/concern-packs.md).

A pack is a Python package inside the agent repo. Its `__init__.py` declares

    ANYTIME_PLUGIN = {"name": "cases", "engine": ">=0.3,<0.4"}

and each direct submodule self-registers concerns, providers and @actions on
import. `load()` refuses — before importing any submodule — a package outside
the repo root (mentat.json rule 3: a committed file must not load foreign
code), an engine outside the declared range, a malformed declaration; and,
while importing, any collision between packs: pack name, concern name,
provider name. An undeclared package still loads (the pre-contract layout),
with a warning.
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__, assembler, config, versions

_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")


class PluginError(Exception):
    """A pack was refused; nothing after it was loaded."""


@dataclass
class PluginInfo:
    package: str
    name: str
    engine: str | None
    declared: bool


def _declaration(pkg_name: str, module) -> PluginInfo:
    decl = getattr(module, "ANYTIME_PLUGIN", None)
    if decl is None:
        config.warn_once(f"undeclared:{pkg_name}",
                         f"concern package '{pkg_name}' has no ANYTIME_PLUGIN declaration "
                         f"(name + engine range); loading it as a legacy pack")
        return PluginInfo(pkg_name, pkg_name, None, False)
    if not isinstance(decl, dict) or not _NAME.match(str(decl.get("name", ""))):
        raise PluginError(f"{pkg_name}: ANYTIME_PLUGIN needs a lowercase 'name' "
                          f"([a-z][a-z0-9_-]*), got {decl!r}")
    spec = decl.get("engine")
    if not isinstance(spec, str):
        raise PluginError(f"{pkg_name}: ANYTIME_PLUGIN['engine'] must be a range like '>=0.3,<0.4'")
    try:
        ok = versions.satisfies(__version__, spec)
    except ValueError as e:
        raise PluginError(f"{pkg_name}: {e}") from e
    if not ok:
        raise PluginError(f"{pkg_name} ('{decl['name']}') needs engine {spec}; "
                          f"this is {__version__}")
    return PluginInfo(pkg_name, decl["name"], spec, True)


def _check_inside(pkg_name: str, root: Path) -> None:
    spec = importlib.util.find_spec(pkg_name)
    if spec is None or not spec.submodule_search_locations:
        raise PluginError(f"'{pkg_name}' is not an importable package")
    for loc in spec.submodule_search_locations:
        if not Path(loc).resolve().is_relative_to(root):
            raise PluginError(f"'{pkg_name}' lives outside the repo ({loc}); only the "
                              f"repo's own packages may be loaded as concern packs")


def _import_modules(pkg_name: str, module) -> None:
    # Reload only what an EARLIER load imported (so registration re-fires after
    # a registry clear). A sibling imported during this loop is fresh already;
    # reloading it would split its classes (`except Err` misses the other Err).
    earlier = set(sys.modules)
    for _imp, modname, _ispkg in pkgutil.iter_modules(module.__path__):
        full = f"{pkg_name}.{modname}"
        if full in earlier:
            importlib.reload(sys.modules[full])
        elif full not in sys.modules:
            importlib.import_module(full)


def load(packages: list[str], *, root: Path | None = None) -> list[PluginInfo]:
    root = (root or config.repo_root()).resolve()
    infos: list[PluginInfo] = []
    names: dict[str, str] = {}
    provider_owner: dict[str, str] = {}
    for pkg_name in packages:
        _check_inside(pkg_name, root)
        info = _declaration(pkg_name, importlib.import_module(pkg_name))
        if info.name in names:
            raise PluginError(f"pack name '{info.name}' declared by both "
                              f"{names[info.name]} and {pkg_name}")
        names[info.name] = pkg_name
        before = assembler.registered_providers()
        try:
            _import_modules(pkg_name, sys.modules[pkg_name])
        except ValueError as e:  # registry.register: duplicate concern
            raise PluginError(f"{pkg_name}: {e}") from e
        for pname, fn in assembler.registered_providers().items():
            if before.get(pname) is fn:
                continue
            if pname in provider_owner and provider_owner[pname] != pkg_name:
                raise PluginError(f"provider '{pname}' registered by both "
                                  f"{provider_owner[pname]} and {pkg_name}")
            provider_owner[pname] = pkg_name
        infos.append(info)
    return infos
