import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler import db, linkcheck  # noqa: E402

ENV_VARS = ["PUBLIC_URL", "ADMIN_PASSWORD", "COOKIE_SECURE"] + [name.upper() for name in db.SECRETS]


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Every test gets its own empty database, no real keys, and a fake link checker,
    so tests never touch real data, the network or paid APIs."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(linkcheck, "_is_dead", lambda url: "dead" in url)
    db.init()
    return tmp_path
