"""Asks Gemini to write one briefing, from collected news (free mode) or its own Google Search (paid)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from google import genai
from google.genai import errors, types

from .db import Briefing

THINKING_LEVELS = {
    "minimal": types.ThinkingLevel.MINIMAL,
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}
BLOCKED_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}

SYSTEM_PROMPT = """\
You write a daily briefing for one reader. Their instructions are in the user message; follow them closely.

Today is {today} (timezone: {tz}).{country}

How to work:
{how_to_work}
- Every fact must come from a page you actually found. Link each source with the article's real, full URL, copied exactly. Never make up or guess a URL. If you can't find reliable information on something, say so instead of guessing.
- The user message ends with a list of stories already covered in recent briefings. Skip those unless something meaningfully new happened, and in that case say what changed.

Output format:
- Your final answer is the complete briefing in Markdown. Start it with a level-1 heading (# ...). Write nothing before that heading.
- Use ## for main sections and ### for each story. Small Markdown tables are fine.
- After the briefing, end with this block, exactly once:

<summary_json>
{{"title": "...", "highlights": ["...", "...", "..."], "mood": "...", "headlines": ["...", "..."]}}
</summary_json>

  title: a short title for today's briefing.
  highlights: the 3 most important points, one short plain-English sentence each. These are shown in a phone notification, so a beginner must understand them without reading the full briefing.
  mood: one or two plain sentences on the overall picture today.
  headlines: a short label for every story you covered (used to avoid repeats tomorrow).
"""


SEARCH_WORK = """\
- Use Google Search to find what actually happened recently, mostly in the last 24-48 hours. Read an article (URL context) when a search snippet isn't enough to get the facts, numbers and dates right."""

FREE_WORK = """\
- The user message ends with today's news items, collected from news feeds. Pick the stories from that list only. You cannot search the web.
- Open the links of the stories you choose (URL context) to read the full article before explaining it. Don't open links marked "headline only".
- If an article can't be opened, use only what its headline and summary say, and say that details are limited.
- If the list has too few useful stories for a section, write fewer stories instead of filling the gap from memory."""


class GenerationError(Exception):
    pass


class ModelBusy(GenerationError):
    """Gemini is overloaded right now (503). Another model may still work."""


@dataclass
class Result:
    markdown: str
    title: str
    highlights: list[str]
    mood: str
    headlines: list[str]
    usage: dict = field(default_factory=dict)


def _user_message(briefing: Briefing, previous: list[dict], news_text: str | None) -> str:
    lines = [briefing.prompt, "", "---", "Already covered in recent briefings:"]
    if not previous:
        lines.append("(nothing yet, this is the first briefing)")
    for entry in previous:
        for headline in entry.get("headlines", []):
            lines.append(f"- {entry['date']}: {headline}")
    if news_text is not None:
        lines += ["", "---", "Today's news items (use only these):", news_text]
    return "\n".join(lines)


def _split_summary(text: str) -> tuple[str, dict]:
    match = re.search(r"<summary_json>\s*(\{.*?\})\s*</summary_json>", text, re.DOTALL)
    summary = {}
    if match:
        try:
            summary = json.loads(match.group(1))
        except json.JSONDecodeError:
            summary = {}
        text = text[:match.start()] + text[match.end():]

    heading = re.search(r"^# ", text, re.MULTILINE)
    if heading:
        text = text[heading.start():]
    return text.strip(), summary


def _usage(response: types.GenerateContentResponse) -> dict:
    usage = {}
    meta = response.usage_metadata
    if meta is not None:
        for key in ("prompt_token_count", "candidates_token_count", "thoughts_token_count",
                    "tool_use_prompt_token_count", "total_token_count"):
            usage[key] = getattr(meta, key, None) or 0
    grounding = response.candidates[0].grounding_metadata if response.candidates else None
    if grounding is not None:
        usage["search_queries"] = len(grounding.web_search_queries or [])
    return usage


def generate(briefing: Briefing, now: datetime, country: str | None, previous: list[dict], *,
             model: str, effort: str, api_key: str, news_text: str | None = None) -> Result:
    """news_text given = free mode (no Google Search). None = Google Search mode (needs billing)."""
    free = news_text is not None
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=15 * 60 * 1000,  # milliseconds; deep research can take several minutes
            retry_options=types.HttpRetryOptions(attempts=2),   # busy models are slow to fail; we switch model instead
        ),
    )

    system = SYSTEM_PROMPT.format(
        today=now.strftime("%A, %d %B %Y"),
        tz=now.tzinfo,
        country=f"\nThe reader lives in country code {country}." if country else "",
        how_to_work=FREE_WORK if free else SEARCH_WORK,
    )
    tools = [types.Tool(url_context=types.UrlContext())]
    if not free:
        tools.insert(0, types.Tool(google_search=types.GoogleSearch()))
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools,
        thinking_config=types.ThinkingConfig(thinking_level=THINKING_LEVELS[effort]),
    )

    try:
        # The SDK automatically resumes long answers (finish reason CONTINUATION) and merges them
        response = client.models.generate_content(
            model=model,
            contents=_user_message(briefing, previous, news_text),
            config=config,
        )
    except errors.ClientError as exc:
        if exc.code == 429 and free:
            raise GenerationError(
                "Gemini's free limit is used up for now. It resets daily (sometimes per minute): "
                "try again later. Tip: use fewer briefings or a lower 'thinking effort'.") from exc
        if exc.code == 429:
            raise GenerationError(
                "Gemini quota exceeded. Google Search only works on a paid key: open aistudio.google.com, "
                "turn on billing for this API key's project, then try again. (If billing is already on, "
                "you hit a rate limit; wait a few minutes.)") from exc
        if exc.code in (400, 401, 403) and "key" in (exc.message or "").lower():
            raise GenerationError(f"Your Gemini API key was not accepted ({exc.message}). "
                                  "Paste a new key in the dashboard under Connections.") from exc
        raise GenerationError(f"Gemini rejected the request ({exc.code}): {exc.message}") from exc
    except errors.ServerError as exc:
        if exc.code in (500, 503, 504):
            raise ModelBusy(f"Gemini ({model}) is overloaded right now. This is on Google's side and usually "
                            "passes within an hour; the app tries again automatically.") from exc
        raise GenerationError(f"Gemini server error ({exc.code}), try again later: {exc.message}") from exc

    if not response.candidates:
        reason = getattr(response.prompt_feedback, "block_reason", None)
        raise GenerationError(f"Gemini returned no answer (blocked: {reason}). Try rewording the prompt file.")

    candidate = response.candidates[0]
    finish = candidate.finish_reason.name if candidate.finish_reason else "STOP"
    if finish == "MAX_TOKENS":
        raise GenerationError("The briefing was too long and got cut off. Ask for fewer stories in the prompt file.")
    if finish in BLOCKED_REASONS:
        raise GenerationError(f"Gemini stopped for safety reasons ({finish}). Try rewording the prompt file.")

    parts = candidate.content.parts if candidate.content and candidate.content.parts else []
    text = "".join(p.text for p in parts if p.text and not p.thought)

    markdown, summary = _split_summary(text)
    if len(markdown) < 200:
        raise GenerationError(f"Gemini returned an empty or very short briefing (finish reason: {finish}).")

    return Result(
        markdown=markdown,
        title=summary.get("title") or briefing.name,
        highlights=[str(h) for h in summary.get("highlights", [])][:3],
        mood=str(summary.get("mood", "")),
        headlines=[str(h) for h in summary.get("headlines", [])],
        usage=_usage(response),
    )
