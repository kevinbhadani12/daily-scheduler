"""Small JSON files that remember past briefings and what was already sent."""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
STATE_FILE = DATA_DIR / "state.json"
OUTBOX_FILE = ROOT / ".outbox.json"  # temporary, lives only during one run
KEEP_HISTORY = 60


def _read(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# History: one file per briefing, newest entry first
def load_history(briefing_id: str) -> list[dict]:
    return _read(HISTORY_DIR / f"{briefing_id}.json", [])


def add_history(briefing_id: str, entry: dict) -> None:
    history = [e for e in load_history(briefing_id) if e["date"] != entry["date"]]
    _write(HISTORY_DIR / f"{briefing_id}.json", ([entry] + history)[:KEEP_HISTORY])


def all_history() -> dict[str, list[dict]]:
    if not HISTORY_DIR.exists():
        return {}
    return {p.stem: _read(p, []) for p in sorted(HISTORY_DIR.glob("*.json"))}


# State: what happened today for each briefing
def load_state() -> dict:
    return _read(STATE_FILE, {})


def save_state(state: dict) -> None:
    _write(STATE_FILE, state)


# Outbox: notifications waiting to be sent after the page is published
def load_outbox() -> list[dict]:
    return _read(OUTBOX_FILE, [])


def add_to_outbox(item: dict) -> None:
    _write(OUTBOX_FILE, load_outbox() + [item])


def clear_outbox() -> None:
    OUTBOX_FILE.unlink(missing_ok=True)
