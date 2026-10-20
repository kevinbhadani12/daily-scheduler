"""Daily Scheduler – AI briefings sent to Telegram and email on your schedule.

  python app.py                      Start the app (dashboard + scheduler) on http://localhost:8000
  python app.py list                 Show your briefings
  python app.py run business         Make one briefing now and send it (uses AI credit)
  python app.py reset-password       Set a new dashboard password
  python app.py add ID --name "…" --prompt-file FILE [--time 08:00] [--days daily] [--deliver telegram,email]

Settings via environment variables (all optional):
  PORT (8000), HOST (0.0.0.0), DATA_DIR (./data), PUBLIC_URL, ADMIN_PASSWORD, COOKIE_SECURE=1,
  GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, EMAIL_ADDRESS, EMAIL_APP_PASSWORD, EMAIL_TO
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import threading
from pathlib import Path

from scheduler import db, jobs

try:
    from dotenv import load_dotenv
    for env_file in (db.ROOT / ".env", db.ROOT / "scheduler" / ".env"):
        load_dotenv(env_file)
except ImportError:
    pass


def serve() -> int:
    from waitress import serve as waitress_serve

    from scheduler.web import create_app

    app = create_app()
    stop = threading.Event()
    jobs.start(stop)
    host, port = os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "8000"))
    logging.getLogger("app").info("Dashboard: http://localhost:%s/dashboard  (data in %s)", port, db.data_dir())
    try:
        waitress_serve(app, host=host, port=port, threads=8)
    finally:
        stop.set()
    return 0


def list_briefings() -> int:
    print(f"Timezone: {db.get_setting('timezone')}\n")
    for b in db.list_briefings():
        days = "daily" if len(b.days) == 7 else ",".join(b.days)
        print(f"[{'ON ' if b.enabled else 'OFF'}] {b.id:<16} {b.time}  {days:<20} → {', '.join(b.deliver):<16} {b.name}")
    return 0


def run(briefing_id: str) -> int:
    if db.get_briefing(briefing_id) is None:
        print(f"No briefing with id '{briefing_id}'. Run: python app.py list")
        return 1
    result = jobs.run_briefing(briefing_id, "manual")
    if result["status"] == "done":
        print(f"✅ Done: {result['url']}")
        for problem in result["send_problems"]:
            print(f"⚠️ {problem}")
        return 0
    print(f"❌ {result['error']}")
    return 1


def reset_password() -> int:
    pw = getpass.getpass("New dashboard password (at least 8 characters): ")
    if len(pw) < 8 or pw != getpass.getpass("Type it again: "):
        print("❌ Too short, or the two passwords don't match.")
        return 1
    from werkzeug.security import generate_password_hash
    db.set_setting("password_hash", generate_password_hash(pw))
    print("✅ Password changed. Log in again in the dashboard.")
    return 0


def add(args) -> int:
    briefings = db.list_briefings()
    new = db.validate_briefing({
        "id": args.id, "name": args.name, "prompt": Path(args.prompt_file).read_text(encoding="utf-8"),
        "time": args.time, "days": db.ALL_DAYS if args.days == "daily" else db.ALL_DAYS[:5]
        if args.days == "weekdays" else args.days.split(","), "deliver": args.deliver.split(","), "enabled": True,
    })
    db.save_briefings([b for b in briefings if b.id != new.id] + [new])
    print(f"✅ Added '{new.name}' at {new.time}. Change it any time in the dashboard.")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Daily Scheduler")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="start the dashboard and scheduler (default)")
    sub.add_parser("list", help="show your briefings")
    run_p = sub.add_parser("run", help="make one briefing now and send it")
    run_p.add_argument("briefing_id")
    sub.add_parser("reset-password", help="set a new dashboard password")
    add_p = sub.add_parser("add", help="add a briefing from a prompt file")
    add_p.add_argument("id")
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--prompt-file", required=True)
    add_p.add_argument("--time", default="08:00")
    add_p.add_argument("--days", default="daily", help="daily, weekdays, or mon,wed,fri")
    add_p.add_argument("--deliver", default="telegram,email")
    args = parser.parse_args()

    db.init()
    try:
        if args.command == "list":
            return list_briefings()
        if args.command == "run":
            return run(args.briefing_id)
        if args.command == "reset-password":
            return reset_password()
        if args.command == "add":
            return add(args)
        return serve()
    except db.ValidationError as exc:
        print(f"❌ {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
