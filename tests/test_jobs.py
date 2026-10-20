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
