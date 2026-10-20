"""Checks that every source link in a briefing actually opens."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import requests

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}
DEAD_STATUSES = {404, 410}


def _is_dead(url: str) -> bool:
    """Only clear failures count as dead. Many news sites block bots (403/429),
    which doesn't mean the link is wrong."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True, stream=True)
        resp.close()
        return resp.status_code in DEAD_STATUSES
    except requests.exceptions.ConnectionError:
        return True
    except requests.RequestException:
        return False


def mark_dead_links(markdown: str) -> tuple[str, list[str]]:
    urls = sorted({m.group(2) for m in LINK_RE.finditer(markdown)})
    if not urls:
        return markdown, []

    with ThreadPoolExecutor(max_workers=8) as pool:
        dead = {url for url, is_dead in zip(urls, pool.map(_is_dead, urls)) if is_dead}

    def replace(match: re.Match) -> str:
        if match.group(2) in dead:
            return f"{match.group(1)} *(⚠️ link could not be opened when checked)*"
        return match.group(0)

    return LINK_RE.sub(replace, markdown), sorted(dead)
