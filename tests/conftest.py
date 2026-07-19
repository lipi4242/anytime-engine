"""Engine test fixtures — state isolation (never touch a live state file)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(autouse=True)
def _isolate_state_path(monkeypatch, tmp_path: Path):
    isolated = tmp_path / "anytime-state-v2.json"
    monkeypatch.setenv("THUFIR_STATE_PATH", str(isolated))
    import anytime_engine.state as state_mod
    monkeypatch.setattr(state_mod, "STATE_PATH", isolated)
    yield isolated
