"""Daily Scheduler – creates AI briefings and sends you the link.

Commands:
  python main.py list                     Show briefings and their next times
  python main.py preview business         Make one briefing locally (nothing is sent)
  python main.py test-notify              Send a test message to Telegram and email
  python main.py generate                 Make every briefing that is due now (used by GitHub Actions)
  python main.py generate --only business --force    Make one briefing now, even if not due
  python main.py notify                   Send links for briefings made by 'generate'
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta

import requests

from scheduler import render, store
from scheduler.config import ConfigError, Settings, load_config
from scheduler.generator import generate
from scheduler.linkcheck import mark_dead_links
from scheduler.notify import SENDERS, NotifyError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MAX_ATTEMPTS = 2          # tries per briefing per day before giving up
PAGE_WAIT_SECONDS = 300   # how long to wait for GitHub Pages to publish a new page


def log(msg: str) -> None:
    print(msg, flush=True)


def is_due(briefing, now: datetime, state: dict) -> bool:
    if not briefing.enabled:
        return False
    if now.strftime("%a").lower() not in briefing.days:
        return False
    if (now.hour, now.minute) < briefing.hour_minute:
        return False
    record = state.get(briefing.id, {})
    if record.get("date") != now.date().isoformat():
        return True
    return record.get("status") != "done" and record.get("attempts", 0) < MAX_ATTEMPTS


def recent_history(briefing_id: str, settings: Settings, today: str) -> list[dict]:
    cutoff = (datetime.fromisoformat(today) - timedelta(days=settings.history_days)).date().isoformat()
    return [e for e in store.load_history(briefing_id) if cutoff <= e["date"] < today]


def make_briefing(briefing, settings: Settings, now: datetime):
    today = now.date().isoformat()
    log(f"▶ Writing '{briefing.name}' with {briefing.model} (effort: {briefing.effort}) …")
    started = time.time()
    result = generate(briefing, now, settings.country, recent_history(briefing.id, settings, today))
    log(f"  Done in {time.time() - started:.0f}s. Usage: {result.usage}")

    markdown, dead = mark_dead_links(result.markdown)
    if dead:
        log(f"  ⚠️ {len(dead)} source link(s) could not be opened and were marked: {dead}")
    return result, markdown


def cmd_generate(settings: Settings, only: str | None, force: bool) -> int:
    now = datetime.now(settings.timezone)
    today = now.date().isoformat()
    state = store.load_state()

    if only:
        targets = [settings.get(only)]
        if not force:
            targets = [b for b in targets if is_due(b, now, state)]
    else:
        targets = [b for b in settings.briefings if is_due(b, now, state)]

    if not targets:
        log(f"Nothing due at {now:%H:%M} ({settings.timezone}).")
        return 0

    failures = 0
    for briefing in targets:
        record = state.get(briefing.id, {})
        attempts = record.get("attempts", 0) + 1 if record.get("date") == today else 1
        state[briefing.id] = {"date": today, "status": "running", "attempts": attempts}
        store.save_state(state)
        date_label = now.strftime("%A, %d %B %Y")

        try:
            result, markdown = make_briefing(briefing, settings, now)
            render.write_briefing_page(render.page_path(briefing.id, today), briefing.name, date_label,
                                       markdown, briefing.model)
            store.add_history(briefing.id, {
                "date": today, "title": result.title, "highlights": result.highlights,
                "mood": result.mood, "headlines": result.headlines,
            })
            store.add_to_outbox({
                "kind": "briefing", "id": briefing.id, "name": briefing.name, "deliver": briefing.deliver,
                "date_label": date_label, "title": result.title, "highlights": result.highlights,
                "mood": result.mood, "url": render.page_url(settings.site_url, briefing.id, today),
            })
            state[briefing.id]["status"] = "done"
            log(f"  ✅ Saved {render.page_path(briefing.id, today).relative_to(render.ROOT)}")
        except Exception as exc:  # keep going with other briefings
            failures += 1
            state[briefing.id].update(status="failed", error=str(exc)[:500])
            log(f"  ❌ {briefing.name} failed (attempt {attempts}/{MAX_ATTEMPTS}): {exc}")
            if attempts >= MAX_ATTEMPTS or force:
                store.add_to_outbox({"kind": "failure", "id": briefing.id, "name": briefing.name,
                                     "deliver": briefing.deliver, "error": str(exc)[:500]})
        store.save_state(state)

    names = {b.id: b.name for b in settings.briefings}
    render.write_index(store.all_history(), names)
    return 1 if failures else 0


def wait_for_page(url: str) -> bool:
    deadline = time.time() + PAGE_WAIT_SECONDS
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=15).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(15)
    return False


def cmd_notify() -> int:
    outbox = store.load_outbox()
    if not outbox:
        log("No messages to send.")
        return 0

    errors = 0
    for item in outbox:
        if item["kind"] == "briefing" and "YOUR-GITHUB-USERNAME" not in item["url"]:
            log(f"Waiting for page to go live: {item['url']}")
            if not wait_for_page(item["url"]):
                log("  Page is not live yet; sending the link anyway (it should work in a few minutes).")
        for channel in item["deliver"]:
            try:
                SENDERS[channel](item)
                log(f"  📨 Sent '{item['name']}' to {channel}")
            except NotifyError as exc:
                errors += 1
                log(f"  ❌ {channel}: {exc}")
    store.clear_outbox()
    return 1 if errors else 0


def cmd_preview(settings: Settings, briefing_id: str) -> int:
    briefing = settings.get(briefing_id)
    now = datetime.now(settings.timezone)
    result, markdown = make_briefing(briefing, settings, now)
    out = render.ROOT / "preview" / f"{briefing.id}-{now.date().isoformat()}.html"
    render.write_briefing_page(out, briefing.name, now.strftime("%A, %d %B %Y"), markdown, briefing.model)
    (out.with_suffix(".md")).write_text(markdown, encoding="utf-8")
    log(f"\nTitle: {result.title}")
    for h in result.highlights:
        log(f"  • {h}")
    log(f"Mood: {result.mood}\n\nOpen this file in your browser:\n  {out}")
    return 0


def cmd_test_notify(settings: Settings) -> int:
    item = {
        "kind": "briefing", "name": "Test message", "date_label": datetime.now(settings.timezone).strftime("%A, %d %B %Y"),
        "title": "Your Daily Scheduler is connected 🎉",
        "highlights": ["Telegram works.", "Email works.", "Your first briefing arrives at the time set in config.yaml."],
        "mood": "Everything is set up correctly.", "url": settings.site_url or "https://github.com",
    }
    errors = 0
    for channel, send in SENDERS.items():
        try:
            send(item)
            log(f"✅ {channel}: sent")
        except NotifyError as exc:
            errors += 1
            log(f"❌ {channel}: {exc}")
    return 1 if errors else 0


def cmd_list(settings: Settings) -> int:
    now = datetime.now(settings.timezone)
    log(f"Timezone: {settings.timezone}   Now: {now:%a %H:%M}\n")
    for b in settings.briefings:
        status = "ON " if b.enabled else "OFF"
        days = "daily" if len(b.days) == 7 else ",".join(b.days)
        log(f"[{status}] {b.id:<16} {b.time}  {days:<20} → {', '.join(b.deliver):<16} {b.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily Scheduler")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="make briefings that are due now")
    gen.add_argument("--only", help="briefing id to make")
    gen.add_argument("--force", action="store_true", help="make it even if it's not due")
    sub.add_parser("notify", help="send links for briefings just made")
    prev = sub.add_parser("preview", help="make one briefing locally without sending")
    prev.add_argument("briefing_id")
    sub.add_parser("test-notify", help="send a test message")
    sub.add_parser("list", help="show your briefings")
    args = parser.parse_args()

    try:
        settings = load_config()
    except ConfigError as exc:
        log(f"❌ Problem in config.yaml: {exc}")
        return 2

    if args.command == "generate":
        return cmd_generate(settings, args.only, args.force)
    if args.command == "notify":
        return cmd_notify()
    if args.command == "preview":
        return cmd_preview(settings, args.briefing_id)
    if args.command == "test-notify":
        return cmd_test_notify(settings)
    return cmd_list(settings)


if __name__ == "__main__":
    sys.exit(main())
