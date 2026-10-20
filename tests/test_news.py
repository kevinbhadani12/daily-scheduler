import time

import pytest

from scheduler import news

from .conftest import REAL_FETCH


class FakeResp:
    def __init__(self, body):
        self.content = body.encode()

    def raise_for_status(self):
        pass


def rfc822(seconds_ago):
    return time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(time.time() - seconds_ago))


@pytest.fixture
def feed(monkeypatch):
    """Use the real feed reader, but serve the given RSS text instead of the internet."""
    monkeypatch.setattr(news, "_fetch", REAL_FETCH)

    def serve(body):
        monkeypatch.setattr(news.requests, "get", lambda url, **kw: FakeResp(body))
    return serve


def test_parse_sources_skips_blanks_and_comments():
    assert news.parse_sources("  https://a.example/rss \n\n# note\nIndia startups\n") == \
        ["https://a.example/rss", "India startups"]


def test_search_words_become_google_news_search():
    assert news._feed_url("Sensex Nifty today").startswith(
        "https://news.google.com/rss/search?q=Sensex+Nifty+today+when%3A1d")
    assert news._feed_url("https://feeds.example/rss") == "https://feeds.example/rss"


def test_fresh_items_kept_old_dropped_text_cleaned_duplicates_removed(feed):
    feed(f"""<rss version="2.0"><channel><title>Example Business</title>
<item><title>Fresh story</title><link>https://ex.example/fresh</link><pubDate>{rfc822(3600)}</pubDate>
<description>&lt;p&gt;Short &lt;b&gt;summary&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>Old story</title><link>https://ex.example/old</link><pubDate>{rfc822(5 * 86400)}</pubDate></item>
<item><title>Fresh story!</title><link>https://ex.example/dupe</link><pubDate>{rfc822(60)}</pubDate></item>
<item><title>No link</title><pubDate>{rfc822(60)}</pubDate></item>
</channel></rss>""")
    items = news.collect(["https://ex.example/rss"])
    assert [i.link for i in items] == ["https://ex.example/dupe"]          # newest kept, same story once, old dropped
    first = news._fetch("https://ex.example/rss")[0]
    assert first.summary == "Short summary" and first.source == "Example Business" and first.readable


def test_google_news_items_are_headline_only(feed):
    feed(f"""<rss><channel><title>Google News</title><item><title>Big deal - Mint</title>
<link>https://news.google.com/rss/articles/abc</link><source url="https://livemint.com">Mint</source>
<pubDate>{rfc822(60)}</pubDate></item></channel></rss>""")
    item = news._fetch("India deals")[0]
    assert (item.title, item.source, item.readable) == ("Big deal", "Mint", False)
    assert "headline only" in news.as_prompt([item])


def test_only_first_links_are_openable():
    items = [news.NewsItem(f"T{i}", f"https://x.example/{i}", "S", time.time(), "", True) for i in range(25)]
    assert news.as_prompt(items).count("headline only") == 25 - news.MAX_READABLE


def test_feed_errors_are_skipped(monkeypatch):
    monkeypatch.setattr(news, "_fetch", REAL_FETCH)

    def offline(url, **kw):
        raise news.requests.ConnectionError("offline")
    monkeypatch.setattr(news.requests, "get", offline)
    assert news.collect(["https://a.example/rss", "some words"]) == []
