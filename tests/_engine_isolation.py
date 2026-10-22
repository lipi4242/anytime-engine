"""Stdlib test isolation for the engine's own tests (unittest AND pytest).

Any test that can touch the state file, the heartbeat or the tick stamps MUST
subclass `IsolatedTestCase`. It points the repo root and the state path at a
fresh temp dir for the duration of each test.

Why this is not just a pytest fixture: the vendored copy of these tests runs
from the *consumer's* repo root, often with plain `python3 -m unittest` (no
pytest on a fresh box). Before 0.3.0 the isolation lived only in conftest.py,
so under unittest `State.save()` resolved to the consumer's real state file.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from anytime_engine import config  # noqa: E402
from anytime_engine import state as state_mod  # noqa: E402

_ENV_KEYS = (
    "ANYTIME_REPO_ROOT", "ANYTIME_STATE_PATH", "THUFIR_STATE_PATH",
    "ANYTIME_REVIEW_TIMES", "ANYTIME_REVIEW_WINDOWS", "ANYTIME_PLUGINS",
    "ANYTIME_TZ", "ANYTIME_CASES_MORNING",
)


class IsolatedTestCase(unittest.TestCase):
    """Fresh temp repo root per test; env, config and STATE_PATH restored after."""

    def setUp(self) -> None:
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="anytime-test-"))
        self._saved_env = {k: os.environ.get(k) for k in _ENV_KEYS}
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        os.environ["ANYTIME_REPO_ROOT"] = str(self.root)
        self._saved_root = config._repo_root
        config._repo_root = None
        self._saved_state_path = getattr(state_mod, "STATE_PATH", None)
        state_mod.STATE_PATH = None
        warned = getattr(config, "_warned", None)
        if warned is not None:
            warned.clear()

    def tearDown(self) -> None:
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config._repo_root = self._saved_root
        state_mod.STATE_PATH = self._saved_state_path
        shutil.rmtree(self.root, ignore_errors=True)
        super().tearDown()
