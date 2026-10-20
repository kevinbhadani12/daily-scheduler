from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from scheduler import db, generator, jobs, notify

from . import fakes

TZ = ZoneInfo("Asia/Kolkata")


def at(hour, minute=0, day=20):   # 20 Oct 2026 is a Tuesday
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setitem(notify.SENDERS, "telegram", lambda item: messages.append(("telegram", item)))
    monkeypatch.setitem(notify.SENDERS, "email", lambda item: messages.append(("email", item)))
    monkeypatch.setattr(jobs, "SENDERS", notify.SENDERS)
    return messages


@pytest.fixture
def gemini():
    db.set_setting("secret:gemini_api_key", "test-key")
    db.set_setting("public_url", "https://brief.example")
    client = fakes.client()
    with mock.patch.object(generator.genai, "Client", return_value=client) as constructor:
        yield client, constructor


def business():
    return db.get_briefing("business")   # 07:00 every day


def fail(day="2026-10-20", finished=at(7, 1)):
    run_id = db.start_run("business", day, "schedule", finished.isoformat())
    db.finish_run(run_id, "failed", finished.isoformat(), error="boom")


# ── when is a briefing due? ─────────────────────────────────
@pytest.mark.parametrize("now, due", [
    (at(6, 59), False),                 # too early
    (at(7, 0), True),
    (at(8, 30), True),                  # app was off at 07:00: still sends (catch-up)
    (at(9, 1), False),                  # more than 2 hours late: skip, don't surprise the user
])
def test_due_window(now, due):
    assert jobs.is_due(business(), now) is due


def test_not_due_on_unselected_day_or_when_off():
    b = business()
    b.days = ["mon"]
    assert jobs.is_due(b, at(7, 5)) is False
    b.days, b.enabled = list(db.ALL_DAYS), False
    assert jobs.is_due(b, at(7, 5)) is False


def test_not_due_after_success_today():
    run_id = db.start_run("business", "2026-10-20", "schedule", at(7).isoformat())
    db.finish_run(run_id, "done", at(7, 5).isoformat())
    assert jobs.is_due(business(), at(7, 30)) is False
    assert jobs.is_due(business(), at(7, 30, day=21)) is True    # but due again tomorrow


def test_retry_waits_then_stops_after_max_attempts():
    fail()
    assert jobs.is_due(business(), at(7, 5)) is False            # wait 10 minutes before retrying
    assert jobs.is_due(business(), at(7, 12)) is True
    fail(finished=at(7, 13))
    assert jobs.is_due(business(), at(8, 0)) is False            # 2 tries used up


def test_manual_runs_dont_count_for_the_schedule():
    run_id = db.start_run("business", "2026-10-20", "manual", at(6).isoformat())
    db.finish_run(run_id, "done", at(6, 5).isoformat())
    assert jobs.is_due(business(), at(7, 1)) is True


# ── making a briefing ───────────────────────────────────────
def test_successful_run_saves_page_and_sends_link(gemini, sent):
    client, constructor = gemini
    result = jobs.run_briefing("business", "manual")

    assert result["status"] == "done" and result["send_problems"] == []
    assert constructor.call_args.kwargs["api_key"] == "test-key"
    token = result["url"].rsplit("/", 1)[1]
    assert result["url"] == f"https://brief.example/b/{token}"
    issue = db.get_issue(token)
    assert issue["title"] == "RBI holds rates"
    assert "<script>" not in issue["html"]                                   # AI output is sanitized
    assert "Broken <em>(⚠️ link could not be opened" in issue["html"]          # dead links are marked

    assert [channel for channel, _ in sent] == ["telegram", "email"]
    item = sent[0][1]
    assert item["kind"] == "briefing" and item["url"] == result["url"] and item["highlights"] == ["One.", "Two.", "Three."]
    run = db.recent_runs()[0]
    assert run["status"] == "done" and run["issue_token"] == token


def test_next_run_gets_previous_headlines(gemini, sent):
    client, _ = gemini
    jobs.run_briefing("business", "manual")
    jobs.run_briefing("business", "manual")
    contents = client.models.generate_content.call_args.kwargs["contents"]
    assert ": RBI holds repo rate" in contents


def test_missing_gemini_key_fails_with_clear_message(sent):
    result = jobs.run_briefing("business", "manual")
    assert result["status"] == "failed" and "Gemini API key is missing" in result["error"]
    assert sent[0][1]["kind"] == "failure"                                  # Run now failures are reported at once


def test_scheduled_failure_reports_only_after_last_try(sent, monkeypatch):
    monkeypatch.setattr(jobs, "datetime", mock.Mock(wraps=datetime, now=lambda tz=None: at(7, 1)))
    jobs.run_briefing("business", "schedule")
    assert sent == []
    jobs.run_briefing("business", "schedule")
    assert [item["kind"] for _, item in sent] == ["failure", "failure"]


def test_send_problems_are_recorded_but_briefing_is_kept(gemini, monkeypatch):
    def broken(item):
        raise notify.NotifyError("Telegram bot token is missing.")
    monkeypatch.setitem(notify.SENDERS, "telegram", broken)
    monkeypatch.setitem(notify.SENDERS, "email", lambda item: None)
    result = jobs.run_briefing("business", "manual")
    assert result["status"] == "done" and "telegram" in result["send_problems"][0]
    assert "token is missing" in db.recent_runs()[0]["error"]


def test_same_briefing_cannot_run_twice_at_once():
    db.start_run("business", "2026-10-20", "manual", at(7).isoformat())     # still running
    with pytest.raises(jobs.AlreadyRunning):
        jobs.run_briefing("business", "manual")
    with pytest.raises(jobs.AlreadyRunning):
        jobs.run_in_background("business")


def test_tick_runs_due_briefings(monkeypatch):
    ran = []
    monkeypatch.setattr(jobs, "run_briefing", lambda bid, trigger: ran.append((bid, trigger)))
    jobs.tick(at(7, 0))
    assert ran == [("business", "schedule")]                                 # stock-market is off
    jobs.tick(at(6, 0))
    assert len(ran) == 1


def test_catch_up_window_constant_is_sane():
    assert timedelta(hours=1) <= jobs.CATCH_UP <= timedelta(hours=6)


# ── free mode vs Google Search mode ─────────────────────────
def test_free_mode_sends_collected_news_and_no_google_search(gemini, sent):
    client, _ = gemini
    assert db.get_setting("research_mode") == "free"                       # free is the default
    jobs.run_briefing("business", "manual")
    kwargs = client.models.generate_content.call_args.kwargs
    assert [t.model_dump(exclude_none=True) for t in kwargs["config"].tools] == [{"url_context": {}}]
    assert "Today's news items (use only these):" in kwargs["contents"]
    assert "https://news.example/rbi" in kwargs["contents"]
    assert "cannot search the web" in kwargs["config"].system_instruction


def test_search_mode_uses_google_search_and_no_feeds(gemini, sent):
    client, _ = gemini
    db.set_setting("research_mode", "search")
    jobs.run_briefing("business", "manual")
    kwargs = client.models.generate_content.call_args.kwargs
    assert {"google_search": {}} in [t.model_dump(exclude_none=True) for t in kwargs["config"].tools]
    assert "Today's news items" not in kwargs["contents"]


def test_free_mode_refuses_paid_only_model(gemini, sent):
    b = db.get_briefing("business")
    b.model = "gemini-4-argon"
    db.save_briefings([b])
    result = jobs.run_briefing("business", "manual")
    assert result["status"] == "failed" and "needs Gemini billing" in result["error"]


def test_free_mode_with_no_news_explains(gemini, sent):
    b = db.get_briefing("business")
    b.sources = "https://empty.example/rss"
    db.save_briefings([b])
    result = jobs.run_briefing("business", "manual")
    assert result["status"] == "failed" and "No recent news" in result["error"]


def test_briefing_without_sources_searches_its_name(gemini, sent, monkeypatch):
    asked = []
    monkeypatch.setattr(jobs.news, "collect", lambda sources: asked.append(sources) or [
        jobs.news.NewsItem("T", "https://n.example/1", "S", None, "", True)])
    b = db.get_briefing("business")
    b.sources = ""
    db.save_briefings([b])
    jobs.run_briefing("business", "manual")
    assert asked == [["Daily Business Briefing"]]


# ── overloaded model → backup model ─────────────────────────
def _busy_error():
    from google.genai import errors
    return errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})


def test_overloaded_model_switches_to_backup(gemini, sent):
    client, _ = gemini
    client.models.generate_content.side_effect = [_busy_error(), fakes.response()]
    result = jobs.run_briefing("business", "manual")
    assert result["status"] == "done"
    models = [c.kwargs["model"] for c in client.models.generate_content.call_args_list]
    assert models == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert db.recent_runs()[0]["usage"].count("gemini-3.5-flash-lite") == 1
    assert "gemini-3.5-flash-lite" in db.get_issue(result["url"].rsplit("/", 1)[1])["html"]   # page says which model


def test_backup_also_busy_gives_clear_message(gemini, sent):
    client, _ = gemini
    client.models.generate_content.side_effect = [_busy_error(), _busy_error()]
    result = jobs.run_briefing("business", "manual")
    assert result["status"] == "failed" and "overloaded" in result["error"]


def test_free_mode_never_falls_back_to_paid_model(gemini, sent, monkeypatch):
    client, _ = gemini
    monkeypatch.setitem(db.BACKUP_MODELS, "gemini-3.8-flash", "gemini-4-argon")
    client.models.generate_content.side_effect = [_busy_error()]
    result = jobs.run_briefing("business", "manual")
    assert result["status"] == "failed" and client.models.generate_content.call_count == 1
