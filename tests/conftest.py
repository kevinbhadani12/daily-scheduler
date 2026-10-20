import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler import linkcheck, render, store  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Send every file the app writes into a temp folder and fake the link checker,
    so tests never touch the real docs/ and data/ folders or the internet."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "HISTORY_DIR", tmp_path / "data" / "history")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "state.json")
    monkeypatch.setattr(store, "OUTBOX_FILE", tmp_path / ".outbox.json")
    monkeypatch.setattr(render, "DOCS_DIR", tmp_path / "docs")
    monkeypatch.setattr(linkcheck, "_is_dead", lambda url: "dead" in url)
    return tmp_path
