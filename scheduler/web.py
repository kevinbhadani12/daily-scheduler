"""The web app: setup, login, dashboard, JSON API for the dashboard, and briefing pages."""
from __future__ import annotations

import html
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, jobs, render
from .notify import SENDERS, NotifyError

log = logging.getLogger("web")
DASHBOARD = Path(__file__).parent / "static" / "dashboard.html"
PUBLIC_PATHS = ("/healthz", "/b/", "/setup")

FORM_STYLE = """<style>
form { max-width:420px; } label { display:block; font-size:14px; font-weight:600; color:var(--muted); margin:14px 0 4px; }
input { width:100%; font:inherit; padding:10px 12px; border-radius:8px; border:1px solid var(--line);
        background:var(--card); color:var(--text); }
button { margin-top:18px; font:inherit; font-weight:600; padding:10px 18px; border-radius:8px; border:0;
         background:var(--accent); color:var(--card); cursor:pointer; }
.error { background:#fdecea; color:#b42318; padding:10px 14px; border-radius:8px; }
</style>"""


def _form_page(title: str, intro: str, fields: str, button: str, error: str = "") -> str:
    err = f'<p class="error">{html.escape(error)}</p>' if error else ""
    body = (f"{FORM_STYLE}<h1>{html.escape(title)}</h1><p>{intro}</p>{err}"
            f'<form method="post">{fields}<button type="submit">{html.escape(button)}</button></form>')
    return render.page(title, body, home="/dashboard", home_label="Daily Scheduler")


def _app_secret_key() -> str:
    key = db.get_setting("flask_secret")
    if not key:
        key = secrets.token_hex(32)
        db.set_setting("flask_secret", key)
    return key


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.secret_key = _app_secret_key()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
                      PERMANENT_SESSION_LIFETIME=timedelta(days=30))

    if os.environ.get("ADMIN_PASSWORD"):
        db.set_setting("password_hash", generate_password_hash(os.environ["ADMIN_PASSWORD"]))
    setup_code = secrets.token_hex(3).upper()
    app.config["SETUP_CODE"] = setup_code
    if not db.get_setting("password_hash"):
        log.warning("FIRST-TIME SETUP: open /setup in your browser and enter this code: %s", setup_code)

    def logged_in() -> bool:
        return session.get("admin") is True

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not logged_in():
                if request.path.startswith("/api/"):
                    return jsonify(error="Please log in again."), 401
                return redirect("/login")
            if request.method != "GET" and request.headers.get("X-CSRF-Token") != session.get("csrf"):
                return jsonify(error="Your session expired. Reload the page."), 403
            return view(*args, **kwargs)
        return wrapper

    def start_session() -> None:
        session.clear()
        session.permanent = True
        session["admin"] = True
        session["csrf"] = secrets.token_urlsafe(24)

    @app.before_request
    def need_setup():
        if not db.get_setting("password_hash") and not request.path.startswith(PUBLIC_PATHS):
            return redirect("/setup")

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    # ── setup & login ───────────────────────────────────────
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if db.get_setting("password_hash"):
            return redirect("/login")
        fields = ('<label for="code">Setup code (shown in the app\'s log / terminal)</label>'
                  '<input id="code" name="code" autocomplete="off" required>'
                  '<label for="pw">Choose a password (at least 8 characters)</label>'
                  '<input id="pw" type="password" name="password" autocomplete="new-password" required>'
                  '<label for="pw2">Type the password again</label>'
                  '<input id="pw2" type="password" name="password2" autocomplete="new-password" required>')
        intro = "Welcome! Create the password that protects your dashboard."
        if request.method == "GET":
            return _form_page("Set up Daily Scheduler", intro, fields, "Create password")
        code, pw, pw2 = (request.form.get(k, "") for k in ("code", "password", "password2"))
        error = ("That setup code is wrong. Look in the app's log or terminal for the current code."
                 if not secrets.compare_digest(code.strip().upper(), setup_code)
                 else "The password must be at least 8 characters." if len(pw) < 8
                 else "The two passwords don't match." if pw != pw2 else "")
        if error:
            time.sleep(1)
            return _form_page("Set up Daily Scheduler", intro, fields, "Create password", error), 400
        db.set_setting("password_hash", generate_password_hash(pw))
        start_session()
        return redirect("/dashboard")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        fields = ('<label for="pw">Password</label>'
                  '<input id="pw" type="password" name="password" autocomplete="current-password" autofocus required>')
        if request.method == "GET":
            return _form_page("Log in", "Enter your dashboard password.", fields, "Log in")
        if check_password_hash(db.get_setting("password_hash"), request.form.get("password", "")):
            start_session()
            return redirect("/dashboard")
        time.sleep(1)
        return _form_page("Log in", "Enter your dashboard password.", fields, "Log in",
                          "Wrong password. Forgot it? Run: python app.py reset-password"), 401

    @app.post("/logout")
    def logout():
        if request.form.get("csrf") == session.get("csrf"):
            session.clear()
        return redirect("/login")

    # ── pages ───────────────────────────────────────────────
    @app.get("/")
    def home():
        return redirect("/dashboard")

    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True)

    @app.get("/dashboard")
    @login_required
    def dashboard():
        if not db.public_url():
            db.set_setting("public_url", request.host_url.rstrip("/"))
        page = DASHBOARD.read_text(encoding="utf-8").replace("__CSRF__", session["csrf"])
        return page, 200, {"Cache-Control": "no-store"}

    @app.get("/b/<token>")
    def briefing(token: str):
        issue = db.get_issue(token)
        if issue is None:
            body = "<h1>Briefing not found</h1><p>This link is wrong or the briefing was deleted.</p>"
            return render.page("Not found", body), 404
        return issue["html"], 200, {
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:",
            "X-Robots-Tag": "noindex",
        }

    # ── API for the dashboard ───────────────────────────────
    @app.errorhandler(db.ValidationError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    @app.get("/api/state")
    @login_required
    def state():
        names = {b.id: b.name for b in db.list_briefings()}
        runs = [{**r, "briefing_name": names.get(r["briefing_id"], r["briefing_id"])} for r in db.recent_runs()]
        return jsonify(
            settings=db.general_settings(), public_url=db.public_url(), secrets=db.secret_status(),
            briefings=[b.to_dict() for b in db.list_briefings()], runs=runs, issues=db.recent_issues(),
            models=db.MODELS, efforts=db.EFFORTS, days=db.ALL_DAYS, channels=db.CHANNELS,
            now=datetime.now(db.timezone()).strftime("%a %H:%M"),
        )

    @app.put("/api/settings")
    @login_required
    def save_settings():
        data = request.get_json(force=True) or {}
        for key, value in db.validate_settings(data.get("settings", {})).items():
            db.set_setting(key, value)
        for name, value in (data.get("secrets") or {}).items():
            if name in db.SECRETS and isinstance(value, str) and value.strip():
                db.set_setting(f"secret:{name}", value.strip())
        for name in data.get("clear_secrets") or []:
            if name in db.SECRETS:
                db.set_setting(f"secret:{name}", "")
        return jsonify(ok=True)

    @app.put("/api/briefings")
    @login_required
    def save_briefings():
        items = (request.get_json(force=True) or {}).get("briefings", [])
        db.save_briefings([db.validate_briefing(item) for item in items])
        return jsonify(ok=True)

    @app.post("/api/briefings/<briefing_id>/run")
    @login_required
    def run_now(briefing_id: str):
        if db.get_briefing(briefing_id) is None:
            abort(404)
        try:
            jobs.run_in_background(briefing_id)
        except jobs.AlreadyRunning:
            return jsonify(error="This briefing is already being made. Wait a few minutes."), 409
        return jsonify(ok=True)

    @app.post("/api/test-notify")
    @login_required
    def test_notify():
        item = {"kind": "briefing", "name": "Test message",
                "date_label": datetime.now(db.timezone()).strftime("%A, %d %B %Y"),
                "title": "Your Daily Scheduler is connected 🎉",
                "highlights": ["This is a test.", "Your briefings will look like this.",
                               "The button below opens your dashboard."],
                "mood": "Everything is set up correctly.", "url": f"{db.public_url()}/dashboard"}
        results = {}
        for channel, send in SENDERS.items():
            try:
                send(item)
                results[channel] = "ok"
            except NotifyError as exc:
                results[channel] = str(exc)
        return jsonify(results=results)

    return app
