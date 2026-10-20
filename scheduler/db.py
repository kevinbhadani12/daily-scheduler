"""SQLite storage: settings, keys, briefings, runs and finished briefing pages."""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .news import STARTER_SOURCES, parse_sources

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "briefings"

ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
CHANNELS = ["telegram", "email"]
MODELS = [
    ("gemini-3.8-flash", "Gemini 3.8 Flash (recommended)"),
    ("gemini-4-argon", "Gemini 4 Argon (best quality, needs billing)"),
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite (cheapest)"),
]
PAID_ONLY_MODELS = {"gemini-4-argon"}   # not on Gemini's free tier
# When a model is overloaded (Gemini error 503), try this one instead
BACKUP_MODELS = {"gemini-3.8-flash": "gemini-3.5-flash-lite", "gemini-4-argon": "gemini-3.8-flash"}
RESEARCH_MODES = [
    ("free", "Free: news feeds + Gemini free tier"),
    ("search", "Google Search: deeper, needs Gemini billing"),
]
EFFORTS = [("high", "High (most careful)"), ("medium", "Medium"), ("low", "Low"), ("minimal", "Minimal (fastest)")]

DEFAULT_SETTINGS = {
    "timezone": "Asia/Kolkata",
    "country": "IN",
    "history_days": "7",
    "default_model": "gemini-3.8-flash",
    "default_effort": "high",
    "research_mode": "free",
    "public_url": "",
}
# Keys can be typed into the dashboard, or set as environment variables (which win)
SECRETS = ["gemini_api_key", "telegram_bot_token", "telegram_chat_id",
           "email_address", "email_app_password", "email_to", "smtp_host", "smtp_port"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS briefings (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL, time TEXT NOT NULL,
    days TEXT NOT NULL, deliver TEXT NOT NULL, enabled INTEGER NOT NULL,
    model TEXT NOT NULL DEFAULT '', effort TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0,
    sources TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, briefing_id TEXT NOT NULL, day TEXT NOT NULL,
    trigger TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL, finished_at TEXT, usage TEXT NOT NULL DEFAULT '{}', issue_token TEXT);
CREATE TABLE IF NOT EXISTS issues (
    token TEXT PRIMARY KEY, briefing_id TEXT NOT NULL, briefing_name TEXT NOT NULL, day TEXT NOT NULL,
    created_at TEXT NOT NULL, title TEXT NOT NULL, highlights TEXT NOT NULL, mood TEXT NOT NULL,
    headlines TEXT NOT NULL, html TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS runs_by_day ON runs (briefing_id, day);
CREATE INDEX IF NOT EXISTS issues_by_day ON issues (briefing_id, day);
"""


class ValidationError(Exception):
    pass


@dataclass
class Briefing:
    id: str
    name: str
    prompt: str
    time: str
    days: list[str]
    deliver: list[str]
    enabled: bool = True
    model: str = ""      # "" = use the default
    effort: str = ""
    sources: str = ""    # free mode: one RSS feed URL or Google News search per line

    @property
    def hour_minute(self) -> tuple[int, int]:
        hour, minute = self.time.split(":")
        return int(hour), int(minute)

    def to_dict(self) -> dict:
        return asdict(self)


def data_dir() -> Path:
    path = Path(os.environ.get("DATA_DIR", ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    conn = sqlite3.connect(data_dir() / "app.db", timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        # A run that was in progress when the app stopped will never finish
        conn.execute("UPDATE runs SET status='failed', error='The app stopped while this was running.', "
                     "finished_at=started_at WHERE status='running'")
    if get_setting("seeded") != "1":
        _seed()


def _migrate(conn) -> None:
    """Upgrade databases made by older versions of the app."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(briefings)")}
    if "sources" not in columns:
        conn.execute("ALTER TABLE briefings ADD COLUMN sources TEXT NOT NULL DEFAULT ''")
        for bid, sources in STARTER_SOURCES.items():
            conn.execute("UPDATE briefings SET sources=? WHERE id=? AND sources=''", ("\n".join(sources), bid))


def _seed() -> None:
    """First start: add the starter briefings from briefings/*.md."""
    starters = [
        Briefing("business", "Daily Business Briefing", "", "07:00", ALL_DAYS, list(CHANNELS), True),
        Briefing("stock-market", "Stock Market Update", "", "16:30", ALL_DAYS[:5], list(CHANNELS), False, effort="medium"),
    ]
    for b in starters:
        template = TEMPLATES_DIR / f"{b.id}.md"
        if template.exists():
            b.prompt = template.read_text(encoding="utf-8").strip()
        b.sources = "\n".join(STARTER_SOURCES.get(b.id, []))
    save_briefings([b for b in starters if b.prompt])
    set_setting("seeded", "1")


# ── settings ────────────────────────────────────────────────
def get_setting(key: str) -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def general_settings() -> dict:
    return {key: get_setting(key) for key in DEFAULT_SETTINGS}


def get_secret(name: str) -> str:
    return os.environ.get(name.upper(), "").strip() or get_setting(f"secret:{name}").strip()


def secret_status() -> dict:
    """What the dashboard may show about keys: never the values themselves."""
    status = {}
    for name in SECRETS:
        from_env = bool(os.environ.get(name.upper(), "").strip())
        value = get_secret(name)
        status[name] = {"set": bool(value), "from_env": from_env,
                        "hint": ("…" + value[-4:]) if value and "password" not in name and "key" not in name
                                and "token" not in name else ""}
    return status


def timezone() -> ZoneInfo:
    return ZoneInfo(get_setting("timezone"))


def public_url() -> str:
    return (os.environ.get("PUBLIC_URL") or get_setting("public_url")).rstrip("/")


def validate_settings(values: dict) -> dict:
    clean = {}
    tz = str(values.get("timezone", "")).strip()
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError(f'"{tz}" is not a valid timezone. Example: Asia/Kolkata')
    clean["timezone"] = tz
    country = str(values.get("country", "")).strip().upper()
    if country and not re.fullmatch(r"[A-Z]{2}", country):
        raise ValidationError("Country code must be 2 letters, like IN or US.")
    clean["country"] = country
    try:
        days = int(values.get("history_days", 7))
    except (TypeError, ValueError):
        days = 0
    if not 1 <= days <= 60:
        raise ValidationError("'Remember stories for' must be between 1 and 60 days.")
    clean["history_days"] = str(days)
    if values.get("default_model") not in dict(MODELS):
        raise ValidationError("Pick a default AI model from the list.")
    clean["default_model"] = values["default_model"]
    if values.get("default_effort") not in dict(EFFORTS):
        raise ValidationError("Pick a default thinking effort from the list.")
    clean["default_effort"] = values["default_effort"]
    if values.get("research_mode", "free") not in dict(RESEARCH_MODES):
        raise ValidationError("Pick a research mode from the list.")
    clean["research_mode"] = values.get("research_mode", "free")
    url = str(values.get("public_url", "")).strip().rstrip("/")
    if url and not re.fullmatch(r"https?://[^\s]+", url):
        raise ValidationError("Public address must start with http:// or https://")
    clean["public_url"] = url
    return clean


# ── briefings ───────────────────────────────────────────────
def _row_to_briefing(row) -> Briefing:
    return Briefing(id=row["id"], name=row["name"], prompt=row["prompt"], time=row["time"],
                    days=json.loads(row["days"]), deliver=json.loads(row["deliver"]),
                    enabled=bool(row["enabled"]), model=row["model"], effort=row["effort"], sources=row["sources"])


def list_briefings() -> list[Briefing]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM briefings ORDER BY position, id").fetchall()
    return [_row_to_briefing(r) for r in rows]


def get_briefing(briefing_id: str) -> Briefing | None:
    return next((b for b in list_briefings() if b.id == briefing_id), None)


def validate_briefing(raw: dict) -> Briefing:
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ValidationError("Every briefing needs a name.")
    bid = str(raw.get("id", "")).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", bid):
        raise ValidationError(f"{name}: id must use only lowercase letters, numbers and dashes.")
    time = str(raw.get("time", ""))
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time):
        raise ValidationError(f"{name}: pick a send time.")
    days = [d for d in ALL_DAYS if d in (raw.get("days") or [])]
    deliver = [c for c in CHANNELS if c in (raw.get("deliver") or [])]
    enabled = bool(raw.get("enabled", True))
    if enabled and not days:
        raise ValidationError(f"{name}: pick at least one day.")
    if enabled and not deliver:
        raise ValidationError(f"{name}: choose Telegram and/or Email.")
    prompt = str(raw.get("prompt", "")).strip()
    if not prompt:
        raise ValidationError(f"{name}: write what the briefing should contain.")
    model, effort = str(raw.get("model") or ""), str(raw.get("effort") or "")
    if model and model not in dict(MODELS):
        raise ValidationError(f"{name}: unknown AI model {model!r}.")
    if effort and effort not in dict(EFFORTS):
        raise ValidationError(f"{name}: unknown thinking effort {effort!r}.")
    sources = parse_sources(str(raw.get("sources") or ""))
    if len(sources) > 30:
        raise ValidationError(f"{name}: use at most 30 news sources.")
    if any(len(line) > 300 for line in sources):
        raise ValidationError(f"{name}: a news source line is too long.")
    return Briefing(bid, name, prompt, time, days, deliver, enabled, model, effort, "\n".join(sources))


def save_briefings(briefings: list[Briefing]) -> None:
    """Replace the whole list (the dashboard always sends all of them)."""
    ids = [b.id for b in briefings]
    if len(ids) != len(set(ids)):
        raise ValidationError("Two briefings share the same id.")
    with connect() as conn:
        conn.execute("DELETE FROM briefings")
        for position, b in enumerate(briefings):
            conn.execute(
                "INSERT INTO briefings (id, name, prompt, time, days, deliver, enabled, model, effort, position, "
                "sources) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (b.id, b.name, b.prompt, b.time, json.dumps(b.days), json.dumps(b.deliver),
                 int(b.enabled), b.model, b.effort, position, b.sources))


def effective_model(b: Briefing) -> str:
    return b.model or get_setting("default_model")


def effective_effort(b: Briefing) -> str:
    return b.effort or get_setting("default_effort")


# ── runs ────────────────────────────────────────────────────
def start_run(briefing_id: str, day: str, trigger: str, now_iso: str) -> int:
    with connect() as conn:
        cur = conn.execute("INSERT INTO runs (briefing_id, day, trigger, status, started_at) "
                           "VALUES (?, ?, ?, 'running', ?)", (briefing_id, day, trigger, now_iso))
        return cur.lastrowid


def finish_run(run_id: int, status: str, now_iso: str, error: str = "", usage: dict | None = None,
               issue_token: str | None = None) -> None:
    with connect() as conn:
        conn.execute("UPDATE runs SET status=?, error=?, finished_at=?, usage=?, issue_token=? WHERE id=?",
                     (status, error[:1000], now_iso, json.dumps(usage or {}), issue_token, run_id))


def runs_on(briefing_id: str, day: str, trigger: str = "schedule") -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM runs WHERE briefing_id=? AND day=? AND trigger=? ORDER BY id",
                            (briefing_id, day, trigger)).fetchall()
    return [dict(r) for r in rows]


def is_running(briefing_id: str) -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM runs WHERE briefing_id=? AND status='running'",
                            (briefing_id,)).fetchone() is not None


def recent_runs(limit: int = 15) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── issues (finished briefings) ─────────────────────────────
def save_issue(briefing: Briefing, day: str, created_at: str, title: str, highlights: list[str], mood: str,
               headlines: list[str], html: str) -> str:
    token = secrets.token_urlsafe(16)   # unguessable link, so pages need no login
    with connect() as conn:
        conn.execute("INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (token, briefing.id, briefing.name, day, created_at, title, json.dumps(highlights),
                      mood, json.dumps(headlines), html))
    return token


def get_issue(token: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM issues WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def recent_headlines(briefing_id: str, since_day: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT day, headlines FROM issues WHERE briefing_id=? AND day>=? ORDER BY created_at",
                            (briefing_id, since_day)).fetchall()
    return [{"date": r["day"], "headlines": json.loads(r["headlines"])} for r in rows]


def recent_issues(limit: int = 30) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT token, briefing_id, briefing_name, day, created_at, title FROM issues "
                            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
