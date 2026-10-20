---
name: add-briefing
description: Add a new scheduled briefing (e.g. "send me AI news every evening"). Writes a good beginner-friendly prompt and adds it to the app. Use when the user wants a new daily/weekly update on a topic.
---

# Add a briefing

Users normally add briefings in the dashboard (**+ Add briefing**). Use this skill when they ask you to do it,
or want help writing a good prompt.

1. **Collect the details.** Ask only for what's missing, and suggest defaults:
   - Topic and what it should cover (the reader is a beginner unless told otherwise)
   - Name, time (`HH:MM`, 24-hour, in the app's timezone), days (`daily`, `weekdays`, or `mon,wed,fri`)
   - Channels: `telegram,email` (default both)
   - Length: a short read (4–5 min) or a deep read (10–15 min)

2. **Write the prompt** following AGENTS.md rule 6. Use `briefings/stock-market.md` (short) or
   `briefings/business.md` (deep) as the model. Save it as `briefings/<id>.md`. The id uses lowercase letters,
   numbers and dashes.

3. **Pick news sources** (Free mode, the default): follow the `news-sources` skill. Test candidates with
   `.venv/bin/python qa/check_sources.py ...`, and keep only ✅ lines. Save them as `briefings/<id>.sources.txt`.

4. **Add it to the app**:
   - If the user runs the app on this machine (`data/app.db` exists, or they say so), run:
     `.venv/bin/python app.py add <id> --name "<Name>" --prompt-file briefings/<id>.md --sources-file briefings/<id>.sources.txt --time HH:MM --days daily --deliver telegram,email`
     If Docker or a server is used, give them this command, or tell them to paste the prompt in the dashboard.
   - The app doesn't need a restart. The scheduler reads briefings from the database on every check.

5. **Check it**: `.venv/bin/python app.py list` shows the new briefing.

6. **Tell the user**: what was added, when it will first arrive, that they can change it in the dashboard,
   and that **▶ Run now** sends one immediately (free in Free mode, but it uses some of the daily free limit). Don't press it yourself
   without asking.
