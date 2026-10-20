"""Checks news sources for Free mode: does each feed work, is it fresh, and are its links openable?

Run:  .venv/bin/python qa/check_sources.py                    # all briefings in the app's database
      .venv/bin/python qa/check_sources.py URL_OR_WORDS ...   # specific sources
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler import db, news  # noqa: E402


def check(source: str) -> None:
    items = news._fetch(source)
    if not items:
        print(f"❌ {source}\n     nothing recent (feed broken, blocked, or no news in the last {news.MAX_AGE_HOURS}h)")
        return
    newest = max((i.published for i in items if i.published), default=None)
    age = f"newest {(time.time() - newest) / 3600:.0f}h ago" if newest else "no dates"
    kind = "full articles" if items[0].readable else "headlines only (Google News)"
    print(f"✅ {source}\n     {len(items)} recent items, {age}, {kind}. e.g. {items[0].title[:70]}")


if len(sys.argv) > 1:
    sources = sys.argv[1:]
else:
    db.init()
    sources = []
    for b in db.list_briefings():
        print(f"\n== {b.name} ==")
        for source in news.parse_sources(b.sources) or [b.name]:
            check(source)
    sys.exit(0)
for source in sources:
    check(source)
