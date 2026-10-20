---
name: add-briefing
description: Add a new scheduled briefing (e.g. "send me AI news every evening"). Creates the prompt file, adds it to config.yaml, and checks it loads. Use when the user wants a new daily/weekly update on a topic.
---

# Add a briefing

1. **Collect the details.** Ask only for what's missing, and suggest defaults:
   - Topic and what it should cover (who it's for: a beginner unless told otherwise)
   - Name (shown in messages), time (`"HH:MM"`, 24-hour, in the `timezone` from `config.yaml`)
   - Days: `daily`, `weekdays`, or a list like `[mon, wed, fri]`
   - Channels: `[telegram, email]` (default both)
   - Length: a short read (4–5 min) or a deep read (10–15 min)

2. **Pick an id**: lowercase letters, numbers and dashes (e.g. `ai-news`). It must be unique in `config.yaml`.

3. **Write `briefings/<id>.md`** following AGENTS.md rule 6. Use `briefings/stock-market.md` as the model for a
   short briefing and `briefings/business.md` for a deep one. Always include:
   - what to cover and how many items
   - simple language rules (short sentences, expand abbreviations, everyday examples, rupee values when relevant)
   - "only real, recent information from reliable sources; link every source; never invent facts or numbers"
   - education-not-advice wording for finance or health topics
   - target reading time

   Don't describe the output format (Markdown or `<summary_json>`). The system prompt handles that.

4. **Add a block to `config.yaml`** under `briefings:`, in the same style as the existing ones:
   ```yaml
     - id: ai-news
       name: AI News
       prompt_file: briefings/ai-news.md
       time: "19:00"
       days: daily
       deliver: [telegram, email]
       enabled: true
   ```
   Only add `model:` / `effort:` if the user wants something different from `defaults`.

5. **Check it**:
   ```bash
   .venv/bin/python main.py list
   .venv/bin/python -m pytest
   ```

6. **Tell the user**: what was added, when it will first arrive, that it can be changed from the dashboard,
   and that they can test it now with **Actions → Daily briefings → Run workflow → `<id>`**.
   Running it costs a little Gemini credit. Don't run `main.py preview` yourself without asking.
