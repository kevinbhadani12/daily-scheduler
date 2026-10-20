"""End-to-end QA: runs the real app (web server + jobs) with a fake Gemini and fake Telegram/email,
then clicks through everything in real Chrome. Nothing real is called and no data of yours is touched.

Needs Google Chrome and `playwright` (requirements-dev.txt).
Run:  .venv/bin/python qa/e2e.py       Screenshots go to qa/screenshots/ (git-ignored).
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "qa" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="daily-scheduler-qa-")
for name in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "EMAIL_ADDRESS", "EMAIL_APP_PASSWORD",
             "EMAIL_TO", "PUBLIC_URL", "ADMIN_PASSWORD"):
    os.environ.pop(name, None)

from playwright.sync_api import sync_playwright  # noqa: E402
from waitress.server import create_server  # noqa: E402

from scheduler import db, generator, jobs, linkcheck, notify, web  # noqa: E402
from tests import fakes  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


# ── start the real app with fakes ───────────────────────────
db.init()
sent = []
for channel in ("telegram", "email"):
    notify.SENDERS[channel] = (lambda ch: lambda item: sent.append((ch, item)))(channel)
linkcheck._is_dead = lambda url: "dead" in url
from tests.conftest import fake_fetch  # noqa: E402
import scheduler.news as news_module  # noqa: E402
news_module._fetch = fake_fetch
gemini = mock.patch.object(generator.genai, "Client", return_value=fakes.client())
gemini.start()
web.time.sleep = lambda s: None

app = web.create_app()
server = create_server(app, host="127.0.0.1", port=0, threads=4)
threading.Thread(target=server.run, daemon=True).start()
BASE = f"http://127.0.0.1:{server.effective_port}"
PASSWORD = "qa-password-123"


def new_page(browser, width=390, dark=False):
    ctx = browser.new_context(viewport={"width": width, "height": 844}, color_scheme="dark" if dark else "light")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and "status of 4" not in m.text and errors.append(m.text))
    return ctx, page, errors


def no_sideways_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def notice(page):
    return page.locator("#notice").inner_text()


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx, page, errors = new_page(browser)

    # 1. First-time setup
    page.goto(f"{BASE}/")
    check("first visit goes to setup", page.url.endswith("/setup"))
    page.screenshot(path=OUT / "1-setup.png", full_page=True)
    page.fill("#code", "WRONG1"); page.fill("#pw", PASSWORD); page.fill("#pw2", PASSWORD); page.click("button")
    check("wrong setup code refused", "setup code is wrong" in page.inner_text("body"))
    page.fill("#code", app.config["SETUP_CODE"]); page.fill("#pw", PASSWORD); page.fill("#pw2", PASSWORD)
    page.click("button")
    page.wait_for_url("**/dashboard")
    page.wait_for_selector("#briefings > section")
    check("setup logs you in to the dashboard", page.locator("#briefings > section").count() == 2)
    check("checklist asks for keys", "Add your Gemini API key" in page.inner_text("#checklist"))
    check("public address learned automatically", db.public_url() == BASE)
    check("free mode is the default and explained", page.input_value("#g-research_mode") == "free"
          and "No billing needed" in page.inner_text("#mode-help"))
    check("no sideways scroll on phone", no_sideways_scroll(page))
    page.screenshot(path=OUT / "2-dashboard-new.png", full_page=True)

    # 2. Connections
    page.fill("#c-gemini_api_key", "AIza-test-key-123")
    page.fill("#c-telegram_bot_token", "123:telegram-secret")
    page.fill("#c-telegram_chat_id", "55512345")
    page.fill("#c-email_address", "me@example.com")
    page.fill("#c-email_app_password", "abcd efgh ijkl mnop")
    page.click("#save-conn")
    page.wait_for_function("document.querySelector('#notice').innerText.includes('Connections saved')")
    check("keys saved on the server", db.get_secret("gemini_api_key") == "AIza-test-key-123"
          and db.get_secret("telegram_chat_id") == "55512345")
    check("saved keys are hidden, harmless ids hinted",
          "Saved ✓" in page.get_attribute("#c-gemini_api_key", "placeholder")
          and page.input_value("#c-gemini_api_key") == ""
          and "…2345" in page.get_attribute("#c-telegram_chat_id", "placeholder"))
    check("secret values never sent back to the browser", "telegram-secret" not in page.content()
          and "test-key-123" not in page.content())
    check("checklist now only warns about the local address",
          page.locator("#check-items li", has_text="⬜").count() == 1
          and "local address" in page.inner_text("#checklist"))
    page.click("#test")
    page.wait_for_function("document.querySelector('#notice').innerText.includes('Telegram')")
    check("test message sent to both", "Telegram: ✅ sent" in notice(page) and "Email: ✅ sent" in notice(page)
          and [c for c, _ in sent] == ["telegram", "email"])
    sent.clear()

    # 3. Edit a briefing
    cards = page.locator("#briefings > section")
    cards.nth(0).locator(".b-head .info").click()
    page.locator("input[type=time]").fill("06:30")
    page.locator("input[type=time]").dispatch_event("change")
    page.locator("label.chip", has_text="Sat").click()
    page.locator("label.chip", has_text="Email").click()
    page.locator("textarea").first.fill(page.locator("textarea").first.input_value() + "\nQA extra line.")
    check("news sources shown for the briefing", "economictimes" in page.locator("textarea.small").first.input_value())
    page.locator("textarea.small").first.fill("https://www.livemint.com/rss/markets\nIndia electric vehicles")
    check("save bar appears", page.locator("#savebar").is_visible())
    page.screenshot(path=OUT / "3-edit.png", full_page=True)

    # 4. Add (with a mistake first) and delete
    page.once("dialog", lambda d: d.accept("AI & Tech News"))
    page.click("#add")
    page.click("#save")
    page.wait_for_selector(".notice.error")
    check("empty prompt refused with a clear message", "should contain" in notice(page), notice(page))
    check("nothing saved after an error", db.get_briefing("ai-tech-news") is None)
    page.locator("textarea:not(.small)").last.fill("Every evening, explain the 3 biggest AI news stories simply.")
    stock = page.locator("#briefings > section", has_text="Stock Market Update")
    stock.locator(".b-head .info").click()
    page.once("dialog", lambda d: d.accept())
    stock.locator("button.danger").click()
    page.select_option("#g-research_mode", "search")
    check("mode help text updates", "needs billing" in page.inner_text("#mode-help"))
    page.select_option("#g-research_mode", "free")
    page.fill("#g-public_url", "https://brief.example")
    page.locator("#g-public_url").dispatch_event("input")
    page.click("#save")
    page.wait_for_function("document.querySelector('#notice').innerText.includes('Saved')")
    b = db.get_briefing("business")
    check("edits saved", b.time == "06:30" and "sat" not in b.days and b.deliver == ["telegram"]
          and b.prompt.endswith("QA extra line.")
          and b.sources == "https://www.livemint.com/rss/markets\nIndia electric vehicles")
    check("new briefing gets its name as a news search", db.get_briefing("ai-tech-news").sources == "AI & Tech News")
    check("new briefing saved", db.get_briefing("ai-tech-news") is not None)
    check("deleted briefing gone", db.get_briefing("stock-market") is None)
    check("public address saved", db.public_url() == "https://brief.example")
    check("checklist hidden when all set", page.locator("#checklist").is_hidden())

    # 5. Run now → link → page
    page.once("dialog", lambda d: d.accept())
    page.locator("#briefings > section").first.locator("button", has_text="Run now").click()
    page.wait_for_function("document.querySelector('#notice').innerText.includes('Started')")
    for _ in range(40):
        if any(r["status"] == "done" for r in db.recent_runs()):
            break
        time.sleep(0.25)
    page.click("#refresh")
    page.wait_for_function("document.querySelector('#runs').innerText.includes('✅')", timeout=15000)
    check("activity shows the finished run", "✅ Daily Business Briefing · Run now" in page.inner_text("#runs")
          and page.locator("#issues a").count() == 1)
    check("link sent to Telegram only (as set)", [c for c, _ in sent] == ["telegram"]
          and sent[0][1]["url"].startswith("https://brief.example/b/"))
    token = sent[0][1]["url"].rsplit("/", 1)[1]
    reader = browser.new_context(viewport={"width": 390, "height": 844}).new_page()   # a phone, not logged in
    reader.goto(f"{BASE}/b/{token}")
    check("briefing link opens without login", "Business Briefing" in reader.inner_text("h1"))
    check("briefing page is sanitized, dead links marked", reader.locator("script").count() == 0
          and "link could not be opened" in reader.inner_text("body"))
    check("briefing page fits a phone", no_sideways_scroll(reader))
    reader.screenshot(path=OUT / "4-briefing-phone.png", full_page=True)
    page.screenshot(path=OUT / "5-dashboard-after-run.png", full_page=True)

    # 6. Run now twice at the same time
    db.start_run("ai-tech-news", "2026-10-20", "manual", "2026-10-20T07:00:00+05:30")
    page.once("dialog", lambda d: d.accept())
    page.locator("#briefings > section", has_text="AI & Tech News").locator("button", has_text="Run now").click()
    page.wait_for_selector(".notice.error")
    check("double Run now refused", "already being made" in notice(page), notice(page))

    # 7. Log out / in
    page.click("text=Log out")
    page.wait_for_url("**/login")
    page.fill("#pw", "wrong-password"); page.click("button")
    check("wrong password refused", "Wrong password" in page.inner_text("body"))
    page.fill("#pw", PASSWORD); page.click("button")
    page.wait_for_url("**/dashboard")
    page.wait_for_selector("#briefings > section")
    check("log in again works", page.locator("#briefings > section").count() >= 2)
    check("no JavaScript errors", not errors, "; ".join(errors))
    ctx.close()

    # 8. Security: a malicious name is shown as text, never run
    items = [x.to_dict() for x in db.list_briefings()]
    items[0]["name"] = "<img src=x onerror=alert(1)>"
    db.save_briefings([db.validate_briefing(x) for x in items])
    ctx, page, errors = new_page(browser, dark=True)
    alerts = []
    page.on("dialog", lambda d: (alerts.append(d.message), d.dismiss()))
    page.goto(f"{BASE}/login"); page.fill("#pw", PASSWORD); page.click("button")
    page.wait_for_selector("#briefings > section")
    page.wait_for_timeout(300)
    check("XSS: no script ran, name shown as text", not alerts and page.locator("#briefings img").count() == 0
          and "<img src=x" in page.locator(".name").first.inner_text())
    page.screenshot(path=OUT / "6-dark.png", full_page=True)
    ctx.close()

    # 9. Desktop layout
    ctx, page, errors = new_page(browser, width=1280)
    page.goto(f"{BASE}/login"); page.fill("#pw", PASSWORD); page.click("button")
    page.wait_for_selector("#briefings > section")
    page.screenshot(path=OUT / "7-desktop.png")
    ctx.close()
    browser.close()

gemini.stop()   # the server thread is a daemon and stops with the script
failed = [name for name, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
