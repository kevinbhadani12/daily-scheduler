"""Fake Gemini responses so tests run without an API key or network."""
from unittest import mock

from google.genai import types

SUMMARY = ('<summary_json>\n{"title": "RBI holds rates", "highlights": ["One.", "Two.", "Three."], '
           '"mood": "Calm day.", "headlines": ["RBI holds repo rate"]}\n</summary_json>')

BODY = (
    "# Business Briefing\n\n### RBI holds rates\nThe Reserve Bank of India (RBI) kept rates.\n\n"
    "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
    "[RBI](https://www.rbi.org.in/) · [Broken](https://dead.example.com/x)\n\n"
    "<script>alert(1)</script>\n\n" + "More text. " * 40 + "\n" + SUMMARY
)


def response(text=BODY, finish=types.FinishReason.STOP, thought="private reasoning"):
    parts = [types.Part(text=thought, thought=True), types.Part(text=text)]
    return types.GenerateContentResponse(
        candidates=[types.Candidate(
            finish_reason=finish,
            content=types.Content(role="model", parts=parts),
            grounding_metadata=types.GroundingMetadata(web_search_queries=["rbi rate"]),
        )],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, candidates_token_count=200, total_token_count=300),
    )


def client(resp=None, error=None):
    fake = mock.MagicMock()
    if error is not None:
        fake.models.generate_content.side_effect = error
    else:
        fake.models.generate_content.return_value = resp or response()
    return fake
