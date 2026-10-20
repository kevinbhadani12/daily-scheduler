from datetime import datetime
from unittest import mock

import main
from scheduler import generator, notify, store

from . import fakes


def generate_now(client, force=True):
    with mock.patch.object(generator.genai, "Client", return_value=client):
        return main.cmd_generate(main.load_config(), "business", force)


def test_full_run_writes_page_history_state_and_outbox(sandbox):
    assert generate_now(fakes.client()) == 0
    today = datetime.now(main.load_config().timezone).date().isoformat()

    page = (sandbox / "docs" / "business" / f"{today}.html").read_text()
    assert "<script>" not in page                                  # AI output is sanitized
    assert "Broken <em>(⚠️ link could not be opened" in page       # dead links are marked
    assert 'target="_blank" href="https://www.rbi.org.in/"' in page
    assert "table-wrap" in page
    assert (sandbox / "docs" / "index.html").exists()

    assert store.load_history("business")[0]["headlines"] == ["RBI holds repo rate"]
    assert store.load_state()["business"]["status"] == "done"
    item = store.load_outbox()[0]
    assert item["kind"] == "briefing" and item["url"].endswith(f"/business/{today}.html")


def test_not_due_again_after_success(sandbox):
    generate_now(fakes.client())
    settings = main.load_config()
    now = datetime.now(settings.timezone)
    assert main.is_due(settings.get("business"), now, store.load_state()) is False


def test_failure_retries_then_notifies(sandbox):
    settings = main.load_config()
    briefing = settings.get("business")
    broken = fakes.client(error=RuntimeError("boom"))
    late = datetime.now(settings.timezone).replace(hour=23, minute=59)

    with mock.patch.object(generator.genai, "Client", return_value=broken), \
         mock.patch.object(main, "datetime", wraps=datetime) as fake_dt:
        fake_dt.now.return_value = late
        assert main.cmd_generate(settings, None, False) == 1   # attempt 1: no message yet
        assert store.load_outbox() == []
        assert main.is_due(briefing, late, store.load_state()) is True
        main.cmd_generate(settings, None, False)               # attempt 2: user is told
        assert store.load_outbox()[0]["kind"] == "failure"
        assert main.is_due(briefing, late, store.load_state()) is False


def test_notify_sends_to_each_channel_and_clears_outbox(sandbox, monkeypatch):
    sent = []
    monkeypatch.setitem(notify.SENDERS, "telegram", lambda item: sent.append(("telegram", item["kind"])))
    monkeypatch.setitem(notify.SENDERS, "email", lambda item: sent.append(("email", item["kind"])))
    monkeypatch.setattr(main, "SENDERS", notify.SENDERS)
    store.add_to_outbox({"kind": "failure", "name": "X", "deliver": ["telegram", "email"], "error": "e"})
    assert main.cmd_notify() == 0
    assert sent == [("telegram", "failure"), ("email", "failure")]
    assert store.load_outbox() == []


def test_missing_secrets_are_reported(monkeypatch):
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "EMAIL_ADDRESS", "EMAIL_APP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    item = {"kind": "failure", "name": "X", "error": "e"}
    for send in notify.SENDERS.values():
        try:
            send(item)
            raise AssertionError("should have failed")
        except notify.NotifyError as exc:
            assert "Missing setting" in str(exc)
