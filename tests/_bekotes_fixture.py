"""Shared fixture for the bekotes pack tests: a temp agent repo with a brain
(`agy/`), one business (`zoldag`) and its three sources — a git repo
(`munka/web`), a memory folder and a local Linear export.

The pack is optional: in the source tree it is `src/anytime_bekotes`, in an
agent repo it is vendored next to the engine. Neither present -> skip."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from _engine_isolation import IsolatedTestCase

_HOME = Path(__file__).resolve().parent.parent   # release/ or the vendored anytime_engine/
PACK_SRC = next((p for p in (_HOME / "src" / "anytime_bekotes", _HOME.parent / "anytime_bekotes")
                 if (p / "__init__.py").is_file()), None)
if PACK_SRC is None:   # pack not vendored into this repo
    raise unittest.SkipTest("anytime_bekotes pack not present")
if str(PACK_SRC.parent) not in sys.path:
    sys.path.insert(0, str(PACK_SRC.parent))

from anytime_bekotes import config  # noqa: E402

_GIT = ["git", "-c", "user.name=Teszt Elek", "-c", "user.email=teszt@example.com",
        "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
        "-c", "init.defaultBranch=main"]
SOURCES = [
    {"name": "web", "kind": "repo", "path": "munka/web"},
    {"name": "memoria", "kind": "memory", "path": "agy/business/zoldag/memoria"},
    {"name": "linear", "kind": "linear", "export": "munka/linear.json", "team": "ZOL"},
    {"name": "posta", "kind": "mail", "state": "blokkolt", "reason": "nincs hozzáférés"},
]


class BekotesCase(IsolatedTestCase):

    def setUp(self):
        super().setUp()
        (self.root / "mentat.json").write_text(json.dumps({
            "schema": 1, "components": {"brain": {"root": "agy"},
                                        "engine": {"plugins": ["anytime_bekotes"]}}}))
        biz = self.root / "agy" / "business" / "zoldag"
        (biz / "memoria").mkdir(parents=True)
        (biz / "bekotes.json").write_text(json.dumps(
            {"schema": 1, "business": "zoldag", "sources": SOURCES}))
        self.mem("a.md", "régi tény")
        web = self.root / "munka" / "web"
        web.mkdir(parents=True)
        self.git("munka/web", "init", "-q")
        (web / "regi.txt").write_text("régi\n")
        self.commit("munka/web", "kezdet")
        self.linear([("ZOL-1", "2026-10-10T10:00:00Z")])
        self.biz = config.businesses(self.root)[0]

    def git(self, path: str, *args: str) -> str:
        r = subprocess.run([*_GIT, "-C", str(self.root / path), *args],
                           capture_output=True, text=True, timeout=30,
                           env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"})
        if r.returncode:
            raise AssertionError(f"git {args}: {r.stderr}")
        return r.stdout

    def commit(self, path: str, msg: str, rm: str | None = None,
               files: dict[str, str] | None = None, mv: tuple[str, str] | None = None):
        repo = self.root / path
        for name, text in (files if files is not None else {"README.md": msg + "\n"}).items():
            (repo / name).write_text(text)
        if rm:
            self.git(path, "rm", "-q", rm)
        if mv:
            self.git(path, "mv", *mv)
        self.git(path, "add", "-A")
        self.git(path, "commit", "-q", "-m", msg)

    def linear(self, items, complete: bool = True):
        issues = [{"id": f"id-{i}", "identifier": i, "title": f"Feladat {i}",
                   "state": "Todo", "updatedAt": u} for i, u in items]
        (self.root / "munka" / "linear.json").write_text(json.dumps(
            {"exported_at": "2026-10-18T07:00:00Z", "complete": complete, "issues": issues}))

    def mem(self, name: str, text: str | None):
        p = self.root / "agy" / "business" / "zoldag" / "memoria" / name
        if text is None:
            p.unlink()
        else:
            p.write_text(text)

    def map_file(self, name: str, text: str):
        (self.root / "agy" / "business" / "zoldag" / name).write_text(text)
