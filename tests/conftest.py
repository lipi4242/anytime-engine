"""Engine test fixtures — state isolation (never touch a live state file).

pytest-only belt; the stdlib braces are tests/_engine_isolation.py, which every
test touching state uses, so `python3 -m unittest` is just as safe."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(autouse=True)
def _isolate_state_path(monkeypatch, tmp_path: Path):
    isolated = tmp_path / "anytime-state.json"
    monkeypatch.setenv("ANYTIME_STATE_PATH", str(isolated))
    monkeypatch.delenv("THUFIR_STATE_PATH", raising=False)
    import anytime_engine.state as state_mod
    monkeypatch.setattr(state_mod, "STATE_PATH", isolated)
    yield isolated
