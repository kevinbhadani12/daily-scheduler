import pytest

from scheduler import db


def test_first_start_adds_starter_briefings():
    briefings = {b.id: b for b in db.list_briefings()}
    assert briefings["business"].enabled and "business developments" in briefings["business"].prompt
    assert not briefings["stock-market"].enabled
    db.init()   # starting again must not add them twice
    assert len(db.list_briefings()) == 2


def test_save_and_load_briefings_keeps_order_and_fields():
    new = db.validate_briefing({"id": "ai-news", "name": "AI News", "prompt": "Explain AI news.", "time": "20:00",
                                "days": ["fri", "mon"], "deliver": ["email"], "enabled": True,
                                "model": "gemini-4-argon", "effort": "low"})
    db.save_briefings([new] + db.list_briefings())
    first = db.list_briefings()[0]
    assert first == new and first.days == ["mon", "fri"]   # days are put in week order
    assert db.effective_model(first) == "gemini-4-argon"
    assert db.effective_effort(db.get_briefing("business")) == "high"   # falls back to the default


GOOD = {"id": "a", "name": "A", "prompt": "p", "time": "07:00", "days": ["mon"], "deliver": ["telegram"]}


@pytest.mark.parametrize("change, message", [
    ({"name": ""}, "needs a name"),
    ({"id": "Bad Id"}, "lowercase"),
    ({"time": "7:00"}, "send time"),
    ({"days": []}, "at least one day"),
    ({"deliver": []}, "Telegram and/or Email"),
    ({"prompt": "  "}, "should contain"),
    ({"model": "gpt-9"}, "unknown AI model"),
    ({"effort": "max"}, "unknown thinking effort"),
])
def test_briefing_problems_are_explained(change, message):
    with pytest.raises(db.ValidationError, match=message):
        db.validate_briefing({**GOOD, **change})


def test_disabled_briefing_may_have_no_days():
    assert db.validate_briefing({**GOOD, "enabled": False, "days": []}).days == []


def test_duplicate_ids_rejected():
    b = db.validate_briefing(GOOD)
    with pytest.raises(db.ValidationError, match="same id"):
        db.save_briefings([b, b])


SETTINGS = {"timezone": "Asia/Kolkata", "country": "in", "history_days": "7",
            "default_model": "gemini-3.8-flash", "default_effort": "high", "public_url": "https://x.example/"}


def test_settings_are_cleaned():
    clean = db.validate_settings(SETTINGS)
    assert clean["country"] == "IN" and clean["public_url"] == "https://x.example"


@pytest.mark.parametrize("change, message", [
    ({"timezone": "Mars/Base"}, "not a valid timezone"),
    ({"country": "IND"}, "2 letters"),
    ({"history_days": "0"}, "between 1 and 60"),
    ({"default_model": "x"}, "default AI model"),
    ({"public_url": "briefings.com"}, "http"),
])
def test_bad_settings_are_explained(change, message):
    with pytest.raises(db.ValidationError, match=message):
        db.validate_settings({**SETTINGS, **change})


def test_secrets_env_wins_and_status_never_shows_values(monkeypatch):
    db.set_setting("secret:gemini_api_key", "db-key-123456")
    db.set_setting("secret:telegram_chat_id", "987654321")
    assert db.get_secret("gemini_api_key") == "db-key-123456"
    monkeypatch.setenv("GEMINI_API_KEY", "env-key-abcdef")
    assert db.get_secret("gemini_api_key") == "env-key-abcdef"

    status = db.secret_status()
    assert status["gemini_api_key"] == {"set": True, "from_env": True, "hint": ""}
    assert status["telegram_chat_id"]["hint"] == "…4321"         # harmless ids show the last 4 characters
    assert "abcdef" not in str(status) and "123456" not in str(status)
    assert status["email_app_password"]["set"] is False


def test_run_left_running_by_a_crash_is_marked_failed():
    run_id = db.start_run("business", "2026-10-20", "schedule", "2026-10-20T07:00:00+05:30")
    db.init()
    run = db.runs_on("business", "2026-10-20")[0]
    assert run["id"] == run_id and run["status"] == "failed" and "stopped" in run["error"]
