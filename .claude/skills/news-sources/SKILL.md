---
name: news-sources
description: Pick, test or fix the news sources (RSS feeds / Google News searches) a briefing uses in Free mode. Use when briefings miss topics, are thin or stale, say "no recent news", or the user wants news from specific sites.
---

# News sources for Free mode

Each briefing has a **News sources** box in the dashboard. Each line is either an RSS feed link or search words
(searched on Google News).

1. **See what's happening now:**
   - All briefings in the app: `.venv/bin/python qa/check_sources.py`
   - Specific candidates: `.venv/bin/python qa/check_sources.py "https://site/rss" "search words"`

   ✅ = working and fresh. "full articles" = Gemini can open the links (best). "headlines only" = Google News,
   for coverage only. ❌ = broken, blocked or stale: remove it.

2. **Find a feed for a site:** try `https://site/rss`, `/feed`, `/rss.xml`, or the site's "RSS" page, and test each
   one with the checker. Prefer the site's section feeds (markets, tech, economy) over "all news".

3. **A good mix per briefing:** 4–10 publisher feeds with full articles, plus 1–3 search-word lines for gaps.
   Mix Indian and global sources when the prompt asks for both. Keep it at 30 lines or fewer.

4. **Apply it:**
   - For the user: give them the lines to paste into the briefing's **News sources** box (dashboard → open the
     briefing → Save changes). If the app runs on this machine, you can also update the database with
     `db.get_briefing` / `db.save_briefings`. Ask first, because it's their data.
   - For the built-in starters: edit `STARTER_SOURCES` in `scheduler/news.py` (only affects new installs).
     Run `.venv/bin/python -m pytest tests/test_news.py tests/test_db.py`.

5. Don't add paid news APIs or scraping of sites without RSS. Free mode must stay free and simple.
