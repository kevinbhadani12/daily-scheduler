import html

import pytest
import requests

from scheduler import db, jobs, notify, web


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(web.time, "sleep", lambda s: None)   # skip the anti-guessing delay in tests
    flask_app = web.create_app()
    flask_app.testing = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def do_setup(app, client, password="correct horse"):
    return client.post("/setup", data={"code": app.config["SETUP_CODE"], "password": password, "password2": password})


@pytest.fixture
def admin(app, client):
    do_setup(app, client)
    page = client.get("/dashboard").get_data(as_text=True)
    csrf = page.split('name="csrf" content="')[1].split('"')[0]
    return client, {"X-CSRF-Token": csrf}


# ── first-time setup & login ────────────────────────────────
def test_everything_goes_to_setup_until_password_exists(client):
    assert client.get("/dashboard").headers["Location"].endswith("/setup")
    assert client.get("/api/state").status_code == 302
    assert client.get("/healthz").json == {"ok": True}


@pytest.mark.parametrize("form, message", [
    ({"code": "WRONG", "password": "longenough", "password2": "longenough"}, "setup code is wrong"),
    ({"password": "short", "password2": "short"}, "at least 8"),
    ({"password": "longenough", "password2": "different1"}, "don't match"),
])
def test_setup_problems(app, client, form, message):
    form = {"code": app.config["SETUP_CODE"], **form}
    resp = client.post("/setup", data=form)
    assert resp.status_code == 400 and message in html.unescape(resp.get_data(as_text=True))
    assert not db.get_setting("password_hash")


def test_setup_then_login_logout(app, client):
    assert do_setup(app, client).headers["Location"].endswith("/dashboard")
    assert client.get("/setup").headers["Location"].endswith("/login")          # setup only works once
    client.post("/logout", data={"csrf": "wrong"})                               # logout needs the csrf value
    assert client.get("/dashboard").status_code == 200

    fresh = app.test_client()
    assert fresh.get("/dashboard").headers["Location"].endswith("/login")
    assert fresh.post("/login", data={"password": "nope"}).status_code == 401
    assert fresh.post("/login", data={"password": "correct horse"}).headers["Location"].endswith("/dashboard")


def test_admin_password_env_skips_setup(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "from-the-env")
    client = web.create_app().test_client()
    assert client.get("/dashboard").headers["Location"].endswith("/login")
    assert client.post("/login", data={"password": "from-the-env"}).status_code == 302


def test_dashboard_remembers_its_own_address(admin):
    assert db.public_url() == "http://localhost"


# ── API ─────────────────────────────────────────────────────
def test_api_needs_login_and_csrf(app, admin):
    assert app.test_client().get("/api/state").status_code == 401
    client, headers = admin
    assert client.put("/api/briefings", json={"briefings": []}).status_code == 403        # no csrf header
    assert client.put("/api/briefings", json={"briefings": []}, headers=headers).status_code == 200


def test_state_never_contains_secret_values(admin):
    client, headers = admin
    db.set_setting("secret:gemini_api_key", "AIzaSECRETVALUE")
    state = client.get("/api/state").get_json()
    assert state["secrets"]["gemini_api_key"]["set"] is True
    assert "SECRETVALUE" not in client.get("/api/state").get_data(as_text=True)
    assert [b["id"] for b in state["briefings"]] == ["business", "stock-market"]


def test_save_settings_and_secrets(admin):
    client, headers = admin
    settings = {**db.general_settings(), "country": "us", "public_url": "https://me.example"}
    body = {"settings": settings, "secrets": {"telegram_chat_id": " 42 ", "email_address": "", "bogus": "x"}}
    assert client.put("/api/settings", json=body, headers=headers).status_code == 200
    assert db.get_setting("country") == "US" and db.public_url() == "https://me.example"
    assert db.get_secret("telegram_chat_id") == "42"
    assert db.get_secret("email_address") == ""                     # empty box = keep (nothing) saved
    client.put("/api/settings", json={"settings": settings, "clear_secrets": ["telegram_chat_id"]}, headers=headers)
    assert db.get_secret("telegram_chat_id") == ""

    bad = client.put("/api/settings", json={"settings": {**settings, "timezone": "Nowhere"}}, headers=headers)
    assert bad.status_code == 400 and "timezone" in bad.get_json()["error"]


def test_save_briefings_roundtrip_and_validation(admin):
    client, headers = admin
    items = client.get("/api/state").get_json()["briefings"]
    items[0]["time"] = "06:15"
    items.append({"id": "ai-news", "name": "AI News", "prompt": "Explain AI news simply.", "time": "20:00",
                  "days": ["mon"], "deliver": ["email"], "enabled": True, "model": "", "effort": ""})
    assert client.put("/api/briefings", json={"briefings": items}, headers=headers).status_code == 200
    assert db.get_briefing("business").time == "06:15" and db.get_briefing("ai-news").deliver == ["email"]

    items[-1]["prompt"] = ""
    bad = client.put("/api/briefings", json={"briefings": items}, headers=headers)
    assert bad.status_code == 400 and "AI News" in bad.get_json()["error"]
    assert db.get_briefing("ai-news").prompt                         # nothing changed on error


def test_run_now(admin, monkeypatch):
    client, headers = admin
    started = []
    monkeypatch.setattr(jobs, "run_in_background", started.append)
    assert client.post("/api/briefings/business/run", headers=headers).status_code == 200
    assert started == ["business"]
    assert client.post("/api/briefings/nope/run", headers=headers).status_code == 404

    def busy(bid):
        raise jobs.AlreadyRunning(bid)
    monkeypatch.setattr(jobs, "run_in_background", busy)
    resp = client.post("/api/briefings/business/run", headers=headers)
    assert resp.status_code == 409 and "already" in resp.get_json()["error"]


def test_test_notify_reports_each_channel(admin, monkeypatch):
    client, headers = admin
    monkeypatch.setitem(notify.SENDERS, "telegram", lambda item: None)
    monkeypatch.setitem(web.SENDERS, "telegram", lambda item: None)
    results = client.post("/api/test-notify", headers=headers).get_json()["results"]
    assert results["telegram"] == "ok"
    assert "Gmail address is missing" in results["email"]


# ── briefing pages ──────────────────────────────────────────
def test_briefing_page_is_public_by_secret_link(client):
    b = db.get_briefing("business")
    token = db.save_issue(b, "2026-10-20", "2026-10-20T07:05:00+05:30", "T", [], "", [], "<h1>Hello</h1>")
    resp = client.get(f"/b/{token}")   # no setup or login needed
    assert resp.status_code == 200 and "Hello" in resp.get_data(as_text=True)
    assert "default-src 'none'" in resp.headers["Content-Security-Policy"]
    assert client.get("/b/not-a-real-token").status_code == 404
    assert len(token) >= 20


def test_telegram_network_error_does_not_leak_token(monkeypatch):
    db.set_setting("secret:telegram_bot_token", "123:SECRET-TOKEN")
    db.set_setting("secret:telegram_chat_id", "1")

    def down(url, **kwargs):
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
    monkeypatch.setattr(notify.requests, "post", down)
    with pytest.raises(notify.NotifyError) as exc:
        notify.send_telegram({"kind": "failure", "name": "X", "error": "e"})
    assert "SECRET-TOKEN" not in str(exc.value) and "SECRET-TOKEN" not in repr(exc.value.__cause__)
