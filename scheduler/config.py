"""Loads config.yaml into simple objects."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS = ALL_DAYS[:5]
CHANNELS = {"telegram", "email"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}


class ConfigError(Exception):
    pass


@dataclass
class Briefing:
    id: str
    name: str
    prompt_file: Path
    time: str
    days: list[str]
    deliver: list[str]
    enabled: bool
    model: str
    effort: str
    max_searches: int
    max_fetches: int

    @property
    def hour_minute(self) -> tuple[int, int]:
        hour, minute = self.time.split(":")
        return int(hour), int(minute)

    def prompt(self) -> str:
        return self.prompt_file.read_text(encoding="utf-8").strip()


@dataclass
class Settings:
    timezone: ZoneInfo
    site_url: str
    country: str | None
    history_days: int
    briefings: list[Briefing]

    def get(self, briefing_id: str) -> Briefing:
        for b in self.briefings:
            if b.id == briefing_id:
                return b
        known = ", ".join(b.id for b in self.briefings)
        raise ConfigError(f"No briefing with id '{briefing_id}'. Known ids: {known}")


def _parse_days(value) -> list[str]:
    if value in (None, "daily"):
        return ALL_DAYS
    if value == "weekdays":
        return WEEKDAYS
    if isinstance(value, list):
        days = [str(d).lower()[:3] for d in value]
        bad = [d for d in days if d not in ALL_DAYS]
        if bad:
            raise ConfigError(f"Unknown day(s) {bad}. Use mon, tue, wed, thu, fri, sat, sun.")
        return days
    raise ConfigError(f"'days' must be daily, weekdays, or a list like [mon, fri], not {value!r}")


def load_config(path: Path = ROOT / "config.yaml") -> Settings:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults", {})
    briefings = []

    for item in raw.get("briefings", []):
        merged = {**defaults, **item}
        bid = str(merged.get("id", ""))
        if not re.fullmatch(r"[a-z0-9-]+", bid):
            raise ConfigError(f"Briefing id {bid!r} must use only lowercase letters, numbers and dashes.")

        time = str(merged.get("time", ""))
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time):
            raise ConfigError(f"[{bid}] time {time!r} must look like \"07:00\" (24-hour, in quotes).")

        prompt_file = ROOT / merged.get("prompt_file", f"briefings/{bid}.md")
        if not prompt_file.exists():
            raise ConfigError(f"[{bid}] prompt file not found: {prompt_file}")

        deliver = list(merged.get("deliver", ["telegram", "email"]))
        if set(deliver) - CHANNELS:
            raise ConfigError(f"[{bid}] deliver can only contain {sorted(CHANNELS)}")

        effort = merged.get("effort", "high")
        if effort not in EFFORTS:
            raise ConfigError(f"[{bid}] effort must be one of {sorted(EFFORTS)}")

        briefings.append(Briefing(
            id=bid,
            name=merged.get("name", bid),
            prompt_file=prompt_file,
            time=time,
            days=_parse_days(merged.get("days")),
            deliver=deliver,
            enabled=bool(merged.get("enabled", True)),
            model=merged.get("model", "claude-opus-5-5"),
            effort=effort,
            max_searches=int(merged.get("max_searches", 25)),
            max_fetches=int(merged.get("max_fetches", 15)),
        ))

    ids = [b.id for b in briefings]
    if len(ids) != len(set(ids)):
        raise ConfigError("Two briefings share the same id.")

    return Settings(
        timezone=ZoneInfo(raw.get("timezone", "Asia/Kolkata")),
        site_url=str(raw.get("site_url", "")).rstrip("/"),
        country=raw.get("country"),
        history_days=int(raw.get("history_days", 7)),
        briefings=briefings,
    )
