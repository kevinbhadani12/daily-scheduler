"""End-to-end QA of docs/dashboard.html in real Chrome with a simulated GitHub API.

Nothing touches the real repo. Needs Google Chrome and `playwright` (requirements-dev.txt).
Run:  .venv/bin/python qa/dashboard_e2e.py      Screenshots go to qa/screenshots/ (git-ignored).
"""
import base64
import functools
import http.server
import json
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "qa" / "screenshots"
OUT.mkdir(exist_ok=True)
TOKEN = "github_pat_TEST"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def b64(s):
    return base64.b64encode(s.encode()).decode()


# Serve docs/ like GitHub Pages
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "docs"))
handler.log_message = lambda *a: None
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"


class FakeGitHub:
    def __init__(self, config_text):
        self.files = {
            "config.yaml": (config_text, "sha-config"),
            "briefings/business.md": ((ROOT / "briefings/business.md").read_text(), "sha-business"),
            "briefings/stock-market.md": ((ROOT / "briefings/stock-market.md").read_text(), "sha-stock"),
        }
        self.writes, self.deletes, self.dispatches, self.bad_auth = [], [], [], 0
        self.forbid_dispatch = False

    def handle(self, route):
        req = route.request
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            self.bad_auth += 1
            return route.fulfill(status=401, json={"message": "Bad credentials"})
        path = urlparse(req.url).path.removeprefix("/repos/kevin/daily-scheduler")
        if path == "" and req.method == "GET":
            return route.fulfill(json={"default_branch": "main"})
        if path.startswith("/contents/"):
            name = path.removeprefix("/contents/")
            if req.method == "GET":
                if name not in self.files:
                    return route.fulfill(status=404, json={"message": "Not Found"})
                text, sha = self.files[name]
                return route.fulfill(json={"content": b64(text), "sha": sha})
            body = json.loads(req.post_data)
            if req.method == "PUT":
                current = self.files.get(name)
                if current and body.get("sha") != current[1]:
                    return route.fulfill(status=409, json={"message": "sha mismatch"})
                text = base64.b64decode(body["content"]).decode()
                self.files[name] = (text, f"sha-{len(self.writes)}")
                self.writes.append((name, body.get("sha"), text, body["branch"]))
                return route.fulfill(json={"content": {"sha": self.files[name][1]}})
            if req.method == "DELETE":
                self.deletes.append((name, body["sha"]))
                self.files.pop(name, None)
                return route.fulfill(json={})
        if path.endswith("/runs"):
            return route.fulfill(json={"workflow_runs": [
                {"event": "workflow_dispatch", "status": "completed", "conclusion": "success",
                 "created_at": "2026-10-20T07:00:00Z", "html_url": "https://github.com/x"},
                {"event": "schedule", "status": "in_progress", "conclusion": None,
                 "created_at": "2026-10-20T07:15:00Z", "html_url": "https://github.com/y"}]})
        if path.endswith("/dispatches") and req.method == "POST":
            if self.forbid_dispatch:
                return route.fulfill(status=403, json={"message": "Resource not accessible by personal access token"})
            self.dispatches.append(json.loads(req.post_data))
            return route.fulfill(status=204, body="")
        return route.fulfill(status=404, json={"message": f"unexpected {req.method} {path}"})


def new_page(browser, gh, dark=False, width=390):
    ctx = browser.new_context(viewport={"width": width, "height": 844}, color_scheme="dark" if dark else "light")
    ctx.route("https://api.github.com/**", gh.handle)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and "status of 40" not in m.text and errors.append(m.text))
    return ctx, page, errors


def no_horizontal_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


config_text = (ROOT / "config.yaml").read_text()

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    # ── 1. Connect ───────────────────────────────────────────
    gh = FakeGitHub(config_text)
    ctx, page, errors = new_page(browser, gh)
    page.goto(f"{BASE}/dashboard.html")
    check("connect form shown on first visit", page.locator("#connect").is_visible())
    page.screenshot(path=OUT / "1-connect-mobile.png", full_page=True)
    page.click("#c-go")
    check("empty fields → error", "Fill in all three" in page.locator("#notice").inner_text())

    page.fill("#c-owner", "kevin"); page.fill("#c-repo", "daily-scheduler"); page.fill("#c-token", "wrong")
    page.click("#c-go")
    page.wait_for_selector(".notice.error")
    check("wrong token → friendly error", "isn't valid" in page.locator("#notice").inner_text(),
          page.locator("#notice").inner_text())

    page.fill("#c-token", TOKEN); page.click("#c-go")
    page.wait_for_selector("#app:not(.hidden)")
    cards = page.locator("#briefings > section")
    check("two briefings listed", cards.count() == 2, str(cards.count()))
    first_sub = cards.nth(0).locator(".sub").inner_text()
    check("summary line shows time/days/channels/next", "07:00" in first_sub and "Every day" in first_sub
          and "Telegram + Email" in first_sub and "Next:" in first_sub, first_sub)
    check("disabled briefing shows Off", "Off" in cards.nth(1).locator(".sub").inner_text())
    page.wait_for_selector("#runs li")
    runs_text = page.locator("#runs").inner_text()
    check("recent runs listed", "✅ Run now" in runs_text and "⏳ Scheduled check" in runs_text, runs_text)
    check("general settings filled", page.input_value("#g-tz") == "Asia/Kolkata"
          and page.input_value("#g-site").startswith("https://"))
    check("no horizontal scroll (phone)", no_horizontal_scroll(page))
    page.screenshot(path=OUT / "2-list-mobile.png", full_page=True)

    # ── 2. Edit business ─────────────────────────────────────
    cards.nth(0).locator(".b-head .info").click()
    page.wait_for_function("document.querySelector('textarea') && !document.querySelector('textarea').disabled")
    check("prompt loaded into editor", "business developments" in page.locator("textarea").input_value())
    page.locator("input[type=time]").fill("06:30")
    page.locator("input[type=time]").dispatch_event("change")
    page.locator("label.chip", has_text="Sat").click()
    page.locator("label.chip", has_text="Email").click()
    page.locator("textarea").fill(page.locator("textarea").input_value() + "\nQA extra line.")
    check("save bar appears after edit", page.locator("#savebar").is_visible())
    check("no horizontal scroll (expanded card)", no_horizontal_scroll(page))
    page.screenshot(path=OUT / "3-edit-mobile.png", full_page=True)

    # ── 3. Validation: new briefing with empty prompt ────────
    page.once("dialog", lambda d: d.accept("AI & Tech News"))
    page.click("#add")
    page.click("#save")
    check("empty prompt blocked with message", "write what the briefing should contain" in page.locator("#notice").inner_text(),
          page.locator("#notice").inner_text())
    check("nothing written when invalid", not gh.writes)
    page.locator("textarea").last.fill("Every evening, explain the 3 biggest AI news stories simply.")

    # ── 4. Delete stock-market ───────────────────────────────
    stock = page.locator("#briefings > section", has_text="Stock Market Update")
    stock.locator(".b-head .info").click()
    page.once("dialog", lambda d: d.accept())
    stock.locator("button.danger").click()
    check("deleted briefing removed from list", page.locator("#briefings > section", has_text="Stock Market Update").count() == 0)

    # ── 5. Save ──────────────────────────────────────────────
    page.click("#save")
    page.wait_for_selector(".notice.ok", timeout=10000)
    written = {w[0]: w for w in gh.writes}
    check("save success message", "Saved" in page.locator("#notice").inner_text())
    check("edited prompt saved with its sha", written.get("briefings/business.md", (0, 0))[1] == "sha-business"
          and "QA extra line." in written["briefings/business.md"][2])
    check("new prompt file created", "briefings/ai-tech-news.md" in written
          and written["briefings/ai-tech-news.md"][1] is None)
    check("deleted briefing's prompt removed", gh.deletes == [("briefings/stock-market.md", "sha-stock")], str(gh.deletes))
    check("config saved last, with sha, on main", gh.writes[-1][0] == "config.yaml" and gh.writes[-1][1] == "sha-config"
          and gh.writes[-1][3] == "main")
    saved = yaml.safe_load(gh.writes[-1][2])
    b = {x["id"]: x for x in saved["briefings"]}
    check("config: business edited correctly", b["business"]["time"] == "06:30"
          and b["business"]["days"] == ["mon", "tue", "wed", "thu", "fri", "sun"]
          and b["business"]["deliver"] == ["telegram"], str(b.get("business")))
    check("config: new briefing added", b.get("ai-tech-news", {}).get("name") == "AI & Tech News"
          and b["ai-tech-news"]["time"] == "08:00")
    check("config: stock-market gone", "stock-market" not in b)
    check("config: settings kept", saved["timezone"] == "Asia/Kolkata" and saved["country"] == "IN"
          and saved["site_url"] == yaml.safe_load(config_text)["site_url"])
    check("save bar hidden after save", not page.locator("#savebar").is_visible())
    (OUT / "saved-config.yaml").write_text(gh.writes[-1][2])

    # second save uses the new sha (no 409)
    page.locator("#briefings > section").first.locator("input[type=time]").fill("06:45")
    page.locator("#briefings > section").first.locator("input[type=time]").dispatch_event("change")
    page.evaluate("document.querySelector('#notice').replaceChildren()")
    page.click("#save")
    check("page locked while saving", page.evaluate("document.querySelector('#app').inert") is True)
    page.wait_for_function("document.querySelector('#notice').innerText.includes('Saved')")
    check("second save works (sha updated)", yaml.safe_load(gh.writes[-1][2])["briefings"][0]["time"] == "06:45")

    # ── 6. Run now ───────────────────────────────────────────
    page.locator("#briefings > section").first.locator("input[type=time]").fill("07:10")
    page.locator("#briefings > section").first.locator("input[type=time]").dispatch_event("change")
    page.locator("#briefings > section").first.locator("button", has_text="Run now").click()
    check("run now blocked while unsaved", "Save your changes first" in page.locator("#notice").inner_text())
    page.click("#discard")
    check("discard restores saved value", page.locator("#briefings > section").first.locator(".sub").inner_text().startswith("06:45"))
    page.once("dialog", lambda d: d.accept())
    page.locator("#briefings > section").first.locator("button", has_text="Run now").click()
    page.wait_for_function("document.querySelector('#notice').innerText.includes('Started')")
    check("run now triggers workflow", gh.dispatches == [{"ref": "main", "inputs": {"briefing": "business"}}], str(gh.dispatches))

    # ── 7. Reload remembers token ────────────────────────────
    page.reload()
    page.wait_for_selector("#app:not(.hidden)")
    check("reload auto-connects (token remembered)", page.locator("#briefings > section").count() == 2)
    page.click("#disconnect")
    page.wait_for_selector("#connect:not(.hidden)")
    check("disconnect forgets token", page.evaluate("localStorage.getItem('daily-scheduler-connection')") is None)
    check("token only sent to api.github.com, no JS errors", not errors, "; ".join(errors))
    ctx.close()

    # ── 8. Security: malicious names are shown as text ───────
    evil = config_text.replace("name: Daily Business Briefing", 'name: "<img src=x onerror=alert(1)>"')
    evil = evil.replace("model: gemini-3.8-flash", "model: claude-opus-5-5")   # old settings still on GitHub
    gh2 = FakeGitHub(evil)
    ctx, page, errors = new_page(browser, gh2, dark=True)
    alerts = []
    catch_alerts = lambda d: (alerts.append(d.message), d.dismiss())
    page.on("dialog", catch_alerts)
    page.goto(f"{BASE}/dashboard.html")
    page.fill("#c-owner", "kevin"); page.fill("#c-repo", "daily-scheduler"); page.fill("#c-token", TOKEN)
    page.click("#c-go")
    page.wait_for_selector("#app:not(.hidden)")
    page.wait_for_timeout(500)
    check("XSS: no script ran", not alerts and page.locator("#briefings img").count() == 0)
    check("XSS: name shown as plain text", "<img src=x" in page.locator(".name").first.inner_text())
    check("old/unknown model → warning to push code", "claude-opus-5-5" in page.locator(".notice.warn").inner_text()
          and "push the latest code" in page.locator(".notice.warn").inner_text())
    gh2.forbid_dispatch = True
    page.remove_listener("dialog", catch_alerts)
    page.once("dialog", lambda d: d.accept())
    page.locator("#briefings > section").first.locator("button", has_text="Run now").click()
    page.wait_for_selector(".notice.error")
    msg = page.locator(".notice.error").inner_text()
    check("token without Actions permission → step-by-step fix", "Actions" in msg and "Read and write" in msg
          and "Fine-grained tokens" in msg, msg)
    page.screenshot(path=OUT / "4-dark-mobile.png", full_page=True)
    ctx.close()

    # ── 9. Desktop + GitHub Pages address auto-fill ──────────
    gh3 = FakeGitHub(config_text)
    ctx, page, errors = new_page(browser, gh3, width=1280)
    ctx.route("https://kevin.github.io/daily-scheduler/dashboard.html",
              lambda r: r.fulfill(body=(ROOT / "docs/dashboard.html").read_text(), content_type="text/html"))
    page.goto("https://kevin.github.io/daily-scheduler/dashboard.html")
    check("Pages URL pre-fills username and repo", page.input_value("#c-owner") == "kevin"
          and page.input_value("#c-repo") == "daily-scheduler")
    page.screenshot(path=OUT / "5-connect-desktop.png")
    ctx.close()

    browser.close()

server.shutdown()
failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
