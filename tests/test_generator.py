from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from google.genai import errors, types

from scheduler import generator
from scheduler.config import load_config

from . import fakes

NOW = datetime(2026, 10, 20, 7, 5, tzinfo=ZoneInfo("Asia/Kolkata"))


def run(client, previous=()):
    briefing = load_config().get("business")
    with mock.patch.object(generator.genai, "Client", return_value=client):
        return generator.generate(briefing, NOW, "IN", list(previous))


def test_parses_briefing_and_summary():
    client = fakes.client()
    result = run(client)
    assert result.markdown.startswith("# Business Briefing")
    assert "<summary_json>" not in result.markdown
    assert "private reasoning" not in result.markdown       # thoughts are never shown
    assert result.title == "RBI holds rates"
    assert result.highlights == ["One.", "Two.", "Three."]
    assert result.headlines == ["RBI holds repo rate"]
    assert result.usage["search_queries"] == 1


def test_request_uses_search_tools_and_thinking_level():
    client = fakes.client()
    run(client, previous=[{"date": "2026-10-19", "headlines": ["Old story"]}])
    kwargs = client.models.generate_content.call_args.kwargs
    config = kwargs["config"]
    assert kwargs["model"] == load_config().get("business").model
    assert [t.model_dump(exclude_none=True) for t in config.tools] == [{"google_search": {}}, {"url_context": {}}]
    assert config.thinking_config.thinking_level == types.ThinkingLevel.HIGH
    assert "2026-10-19: Old story" in kwargs["contents"]           # history is passed to avoid repeats
    assert "Tuesday, 20 October 2026" in config.system_instruction


def test_text_before_heading_is_dropped():
    result = run(fakes.client(fakes.response(text="Sure! Here it is.\n\n" + fakes.BODY)))
    assert result.markdown.startswith("# Business Briefing")


def test_missing_summary_still_works():
    body = fakes.BODY.split("<summary_json>")[0]
    result = run(fakes.client(fakes.response(text=body)))
    assert result.title == "Daily Business Briefing" and result.highlights == []


@pytest.mark.parametrize("finish, message", [
    (types.FinishReason.MAX_TOKENS, "cut off"),
    (types.FinishReason.SAFETY, "safety"),
])
def test_bad_finish_reasons_raise(finish, message):
    with pytest.raises(generator.GenerationError, match=message):
        run(fakes.client(fakes.response(finish=finish)))


def test_empty_answer_raises():
    with pytest.raises(generator.GenerationError, match="empty"):
        run(fakes.client(fakes.response(text="# Hi")))


def test_quota_error_explains_billing():
    err = errors.ClientError(429, {"error": {"code": 429, "message": "You exceeded your current quota",
                                             "status": "RESOURCE_EXHAUSTED"}})
    with pytest.raises(generator.GenerationError, match="turn on billing"):
        run(fakes.client(error=err))


def test_api_errors_become_friendly():
    err = errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}})
    with pytest.raises(generator.GenerationError, match="API key not valid"):
        run(fakes.client(error=err))
