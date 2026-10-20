"""Turns briefing Markdown into clean, mobile-friendly web pages."""
from __future__ import annotations

import html
import math
import re

import markdown as md
import nh3

STYLE = """
:root { --bg:#fbfaf7; --card:#ffffff; --text:#1d1d1f; --muted:#6b6b70; --line:#e6e3dc;
        --accent:#0b6e4f; --accent-soft:#e3f2ec; --code:#f2f0eb; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#141416; --card:#1c1c1f; --text:#ececee; --muted:#a0a0a8; --line:#2e2e33;
          --accent:#5fd3a6; --accent-soft:#1d332b; --code:#26262b; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:17px/1.7 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
header { border-bottom:1px solid var(--line); background:var(--card); }
.bar { max-width:760px; margin:0 auto; padding:14px 16px; display:flex; justify-content:space-between;
       gap:12px; font-size:14px; color:var(--muted); }
.bar a { color:var(--accent); text-decoration:none; font-weight:600; }
main { max-width:760px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:1.9rem; line-height:1.25; margin:0.4em 0 0.3em; }
h2 { font-size:1.4rem; line-height:1.3; margin:2.2em 0 0.6em; padding-top:1em; border-top:1px solid var(--line); }
h3 { font-size:1.15rem; line-height:1.35; margin:1.8em 0 0.5em; color:var(--accent); }
p, li { overflow-wrap:anywhere; }
a { color:var(--accent); }
strong { font-weight:650; }
blockquote { margin:1em 0; padding:0.6em 1em; background:var(--accent-soft); border-left:4px solid var(--accent);
             border-radius:6px; }
code { background:var(--code); padding:0.1em 0.35em; border-radius:4px; font-size:0.9em; }
pre { background:var(--code); padding:12px; border-radius:8px; overflow-x:auto; line-height:1.4; }
pre code { padding:0; background:none; }
.table-wrap { overflow-x:auto; margin:1em 0; }
table { border-collapse:collapse; width:100%; font-size:0.92em; }
th, td { border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }
th { background:var(--code); }
.meta { color:var(--muted); font-size:14px; margin-bottom:1.5em; }
.list a { display:block; padding:14px 16px; margin:10px 0; background:var(--card); border:1px solid var(--line);
          border-radius:10px; text-decoration:none; color:var(--text); }
.list a:hover { border-color:var(--accent); }
.list .date { color:var(--muted); font-size:14px; }
.list .name { color:var(--accent); font-size:13px; font-weight:600; text-transform:uppercase; letter-spacing:0.04em; }
footer { color:var(--muted); font-size:13px; margin-top:3em; border-top:1px solid var(--line); padding-top:1em; }
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__STYLE__</style>
</head>
<body>
<header><div class="bar"><a href="__HOME__">__HOMELABEL__</a><span>__NAV__</span></div></header>
<main>
__BODY__
</main>
</body>
</html>
"""


def page(title: str, body: str, home: str = "/dashboard", nav: str = "", home_label: str = "← Dashboard") -> str:
    return (PAGE.replace("__TITLE__", html.escape(title))
                .replace("__HOMELABEL__", html.escape(home_label))
                .replace("__STYLE__", STYLE)
                .replace("__HOME__", home)
                .replace("__NAV__", html.escape(nav))
                .replace("__BODY__", body))


def markdown_to_html(text: str) -> str:
    raw = md.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    raw = raw.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    clean = nh3.clean(raw, attributes={"div": {"class"}, "a": {"href", "title"}, "th": {"align"}, "td": {"align"}})
    # Open source links in a new tab
    return re.sub(r'<a href="(https?://)', r'<a target="_blank" href="\1', clean)


def briefing_page(name: str, date_label: str, markdown_text: str, model: str) -> str:
    minutes = max(1, math.ceil(len(markdown_text.split()) / 200))
    body = (
        markdown_to_html(markdown_text)
        + f'<footer>{html.escape(name)} · {html.escape(date_label)} · about {minutes} min read<br>'
        + f"Written by AI ({html.escape(model)}) from web sources. Check the sources before acting on anything."
        + "</footer>"
    )
    body = body.replace("</h1>", f'</h1><p class="meta">{html.escape(date_label)} · {minutes} min read</p>', 1)
    return page(f"{name} – {date_label}", body, nav=name)
