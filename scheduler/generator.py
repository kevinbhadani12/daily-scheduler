"""Asks Claude to research the web and write one briefing."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

import anthropic

from .config import Briefing

MAX_CONTINUATIONS = 8

SYSTEM_PROMPT = """\
You write a daily briefing for one reader. Their instructions are in the user message; follow them closely.

Today is {today} (timezone: {tz}).

How to work:
- Use web_search to find what actually happened recently, mostly in the last 24-48 hours. Use web_fetch to read an article when a search snippet isn't enough to get the facts, numbers and dates right.
- Every fact must come from a page you actually found. Link each source with its real URL, copied exactly. If you can't find reliable information on something, say so instead of guessing.
- The user message ends with a list of stories already covered in recent briefings. Skip those unless something meaningfully new happened, and in that case say what changed.

Output format:
- Your final answer is the complete briefing in Markdown. Start it with a level-1 heading (# ...). Write nothing before that heading, such as notes about your searching.
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


class GenerationError(Exception):
    pass


@dataclass
class Result:
    markdown: str
    title: str
    highlights: list[str]
    mood: str
    headlines: list[str]
    usage: dict = field(default_factory=dict)


def _user_message(briefing: Briefing, previous: list[dict]) -> str:
    lines = [briefing.prompt(), "", "---", "Already covered in recent briefings:"]
    if not previous:
        lines.append("(nothing yet, this is the first briefing)")
    for entry in previous:
        for headline in entry.get("headlines", []):
            lines.append(f"- {entry['date']}: {headline}")
    return "\n".join(lines)


def _final_text(content: list) -> str:
    """Text written after the last tool call, which is the finished briefing."""
    last_tool = -1
    for i, block in enumerate(content):
        if block.type not in ("text", "thinking", "redacted_thinking"):
            last_tool = i
    text = "".join(b.text for b in content[last_tool + 1:] if b.type == "text")
    if not text.strip():
        text = "".join(b.text for b in content if b.type == "text")
    return text


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


def _add_usage(total: dict, usage) -> None:
    if usage is None:
        return
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        total[key] = total.get(key, 0) + (getattr(usage, key, None) or 0)
    server = getattr(usage, "server_tool_use", None)
    if server is not None:
        for key in ("web_search_requests", "web_fetch_requests"):
            total[key] = total.get(key, 0) + (getattr(server, key, None) or 0)


def generate(briefing: Briefing, now: datetime, country: str | None, previous: list[dict]) -> Result:
    client = anthropic.Anthropic()

    search_tool = {"type": "web_search_20260209", "name": "web_search", "max_uses": briefing.max_searches}
    if country:
        search_tool["user_location"] = {"type": "approximate", "country": country, "timezone": str(now.tzinfo)}
    tools = [search_tool, {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": briefing.max_fetches}]

    system = SYSTEM_PROMPT.format(today=now.strftime("%A, %d %B %Y"), tz=now.tzinfo)
    messages = [{"role": "user", "content": _user_message(briefing, previous)}]
    assistant_content: list = []
    usage: dict = {}

    for _ in range(MAX_CONTINUATIONS):
        with client.beta.messages.stream(
            model=briefing.model,
            max_tokens=64000,
            system=system,
            messages=messages,
            tools=tools,
            output_config={"effort": briefing.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if the model declines, retry on Anthropic's recommended fallback model
        ) as stream:
            response = stream.get_final_message()

        _add_usage(usage, response.usage)
        assistant_content.extend(response.content)

        if response.stop_reason == "pause_turn":
            # Long research turn: send the work so far back and let it continue
            messages = messages[:1] + [{"role": "assistant", "content": assistant_content}]
            continue
        if response.stop_reason == "refusal":
            raise GenerationError("The AI declined to write this briefing. Try rewording the prompt file.")
        if response.stop_reason == "max_tokens":
            raise GenerationError("The briefing was too long and got cut off. Ask for fewer stories in the prompt file.")
        break
    else:
        raise GenerationError("The AI kept researching without finishing. Try lowering max_searches.")

    markdown, summary = _split_summary(_final_text(assistant_content))
    if len(markdown) < 200:
        raise GenerationError("The AI returned an empty or very short briefing.")

    return Result(
        markdown=markdown,
        title=summary.get("title") or briefing.name,
        highlights=[str(h) for h in summary.get("highlights", [])][:3],
        mood=str(summary.get("mood", "")),
        headlines=[str(h) for h in summary.get("headlines", [])],
        usage=usage,
    )
