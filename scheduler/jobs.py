"""Decides when a briefing is due, makes it, and sends the link."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from . import db, news, render
from .generator import GenerationError, ModelBusy, generate
from .linkcheck import mark_dead_links
from .notify import SENDERS, NotifyError

log = logging.getLogger("scheduler")

TICK_SECONDS = 30                    # how often the scheduler checks for due briefings
MAX_ATTEMPTS = 2                     # tries per briefing per day
RETRY_AFTER = timedelta(minutes=10)  # wait between tries
CATCH_UP = timedelta(hours=2)        # still send if the app was off at the set time, up to this late

_active: set[str] = set()
_active_lock = threading.Lock()


class AlreadyRunning(Exception):
    pass


def is_due(b: db.Briefing, now: datetime) -> bool:
    if not b.enabled or now.strftime("%a").lower() not in b.days:
        return False
    hour, minute = b.hour_minute
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if not scheduled <= now <= scheduled + CATCH_UP:
        return False
    if b.id in _active or db.is_running(b.id):
        return False
    runs = db.runs_on(b.id, now.date().isoformat())
    if any(r["status"] == "done" for r in runs):
        return False
    failed = [r for r in runs if r["status"] == "failed"]
    if len(failed) >= MAX_ATTEMPTS:
        return False
    return not failed or now - datetime.fromisoformat(failed[-1]["finished_at"]) >= RETRY_AFTER


def _send(b: db.Briefing, item: dict) -> list[str]:
    problems = []
    for channel in b.deliver:
        try:
            SENDERS[channel](item)
            log.info("Sent '%s' to %s", b.name, channel)
        except NotifyError as exc:
            problems.append(f"{channel}: {exc}")
            log.warning("Could not send '%s' to %s: %s", b.name, channel, exc)
    return problems


def run_briefing(briefing_id: str, trigger: str = "manual") -> dict:
    """Make one briefing and send it. trigger is 'schedule' or 'manual'."""
    with _active_lock:
        if briefing_id in _active or db.is_running(briefing_id):
            raise AlreadyRunning(briefing_id)
        _active.add(briefing_id)
    try:
        return _run(briefing_id, trigger)
    finally:
        with _active_lock:
            _active.discard(briefing_id)


def _collect_news(b: db.Briefing, model: str) -> str:
    """Free mode: gather today's news from the briefing's sources for Gemini to work from."""
    if model in db.PAID_ONLY_MODELS:
        raise GenerationError(f"{model} needs Gemini billing. In free mode, pick Gemini 3.8 Flash "
                              "(General settings or this briefing's AI model).")
    sources = news.parse_sources(b.sources) or [b.name]   # no sources: search Google News for the name
    items = news.collect(sources)
    if not items:
        raise GenerationError("No recent news was found in this briefing's news sources. Check the sources "
                              "(one RSS feed link or search words per line) and the server's internet.")
    log.info("Collected %d news items for '%s'", len(items), b.name)
    return news.as_prompt(items)


def _run(briefing_id: str, trigger: str) -> dict:
    b = db.get_briefing(briefing_id)
    if b is None:
        raise KeyError(briefing_id)
    now = datetime.now(db.timezone())
    day, date_label = now.date().isoformat(), now.strftime("%A, %d %B %Y")
    run_id = db.start_run(b.id, day, trigger, now.isoformat())
    model, effort = db.effective_model(b), db.effective_effort(b)
    log.info("Writing '%s' with %s (effort: %s, %s)", b.name, model, effort, trigger)

    try:
        api_key = db.get_secret("gemini_api_key")
        if not api_key:
            raise GenerationError("The Gemini API key is missing. Add it in the dashboard under Connections.")
        news_text = _collect_news(b, model) if db.get_setting("research_mode") == "free" else None
        since = (now.date() - timedelta(days=int(db.get_setting("history_days")))).isoformat()
        args = (b, now, db.get_setting("country") or None, db.recent_headlines(b.id, since))
        try:
            result = generate(*args, model=model, effort=effort, api_key=api_key, news_text=news_text)
        except ModelBusy:
            backup = db.BACKUP_MODELS.get(model)
            if not backup or (news_text is not None and backup in db.PAID_ONLY_MODELS):
                raise
            log.info("%s is overloaded; trying %s instead", model, backup)
            model = backup
            result = generate(*args, model=model, effort=effort, api_key=api_key, news_text=news_text)
        result.usage["model"] = model
        markdown, dead = mark_dead_links(result.markdown)
        if dead:
            log.info("Marked %d source link(s) that did not open", len(dead))
        html = render.briefing_page(b.name, date_label, markdown, model)
        token = db.save_issue(b, day, now.isoformat(), result.title, result.highlights, result.mood,
                              result.headlines, html)
    except Exception as exc:
        error = str(exc) if isinstance(exc, GenerationError) else f"Unexpected problem: {exc}"
        log.warning("'%s' failed: %s", b.name, error)
        db.finish_run(run_id, "failed", datetime.now(db.timezone()).isoformat(), error=error)
        tries = len([r for r in db.runs_on(b.id, day) if r["status"] == "failed"])
        if trigger != "schedule" or tries >= MAX_ATTEMPTS:   # tell the user only after the last try
            _send(b, {"kind": "failure", "name": b.name, "error": error})
        return {"status": "failed", "error": error}

    url = f"{db.public_url()}/b/{token}"
    problems = _send(b, {"kind": "briefing", "name": b.name, "date_label": date_label, "title": result.title,
                         "highlights": result.highlights, "mood": result.mood, "url": url})
    db.finish_run(run_id, "done", datetime.now(db.timezone()).isoformat(),
                  error="; ".join(problems), usage=result.usage, issue_token=token)
    return {"status": "done", "url": url, "send_problems": problems}


def run_in_background(briefing_id: str) -> None:
    """For the dashboard's Run now button."""
    if briefing_id in _active or db.is_running(briefing_id):
        raise AlreadyRunning(briefing_id)

    def work():
        try:
            run_briefing(briefing_id, "manual")
        except AlreadyRunning:
            pass
        except Exception:
            log.exception("Run now failed for %s", briefing_id)

    threading.Thread(target=work, name=f"run-{briefing_id}", daemon=True).start()


def tick(now: datetime | None = None) -> None:
    now = now or datetime.now(db.timezone())
    for b in db.list_briefings():
        if is_due(b, now):
            try:
                run_briefing(b.id, "schedule")
            except AlreadyRunning:
                pass


def start(stop: threading.Event) -> threading.Thread:
    def loop():
        log.info("Scheduler started (checks every %ss)", TICK_SECONDS)
        while not stop.is_set():
            try:
                tick()
            except Exception:
                log.exception("Scheduler check failed")
            stop.wait(TICK_SECONDS)

    thread = threading.Thread(target=loop, name="scheduler", daemon=True)
    thread.start()
    return thread
