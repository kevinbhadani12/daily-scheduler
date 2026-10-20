# Daily Scheduler

Get easy-to-understand AI briefings (business news, stock market, anything you want) every day at the time
you choose. You get the link on **Telegram** and **email**.

- **Free by default**: the app collects today's news from trusted news feeds, and the **free** Gemini tier
  reads the articles and explains them simply, with source links. No billing needed.
- **One small app** runs anywhere: your laptop, a home PC or Raspberry Pi, any VPS, or Docker hosting.
- **Everything is set in the browser**: times, days, topics, keys. No config files, GitHub or tokens needed.

```
┌─────────────────────── Daily Scheduler (one app) ───────────────────────┐
│  Dashboard (password)   ──►  settings, briefings, keys  ──►  data/app.db │
│  Scheduler (every 30 s) ──►  due? → news feeds → Gemini (free) → page    │
│                               └─► Telegram + email with the link         │
│  /b/<secret-link>       ──►  the briefing page you open on your phone    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Start it

### Option A: Docker (recommended for servers)
```bash
docker compose up -d
```

### Option B: Python (3.10 or newer)
```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip ...
.venv/bin/python app.py
```

Then open **http://localhost:8000**.

## First-time setup (about 10 minutes)

1. **Create your password.** The setup page asks for a **setup code**. It's printed in the app's log
   (the terminal, or `docker compose logs`). This stops strangers from claiming your dashboard first.
2. **Connections** (in the dashboard): paste your keys, then press **Send test message**.

   | Key | Where to get it |
   |---|---|
   | Gemini API key | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). A **free** key is enough |
   | Telegram bot token | In Telegram, message **@BotFather** → `/newbot` |
   | Telegram chat id | Send your bot a message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": …}` |
   | Gmail address + app password | Turn on 2-Step Verification, then [create an app password](https://myaccount.google.com/apppasswords) |

3. **Your briefings**: set the time, days and topic, then press **▶ Run now** to get your first briefing.

The dashboard shows a "Finish setting up" checklist until everything is done.

---

## Free mode vs Google Search mode

Choose in *General settings → How briefings find news*.

| | **Free mode** (default) | **Google Search mode** |
|---|---|---|
| Cost | Free (free Gemini key) | Paid per use: turn on billing for your Gemini key |
| How it finds news | The app reads each briefing's **News sources** (news sites' RSS feeds, plus Google News searches), then Gemini opens and reads the articles | Gemini searches Google itself |
| Best for | Daily news from well-known sites | Niche topics that RSS feeds don't cover |

**Your Gemini Pro (Google AI Pro) subscription doesn't include API use.** It works in the Gemini app and the
AI Studio website only. That's why Google Search mode says "limit reached" without billing. Free mode doesn't
need it. If you ever want Search mode, AI Pro includes about $10/month of Google Cloud credits (Google Developer
Program) that can pay for it once billing is on.

**News sources**: each briefing has a box with one source per line: a news site's RSS feed link (best, because
Gemini can read the full article), or search words (searched on Google News, headlines only). The two starter
briefings come with good Indian and global sources. Check your sources any time:
```bash
.venv/bin/python qa/check_sources.py        # ✅ working / ❌ broken or stale, for every briefing
.venv/bin/python qa/check_gemini.py         # what your Gemini key can do (free vs paid features)
```

## Where to host it

The app must **stay on** to send briefings on time. If it was off at the set time, it still sends when it
comes back, up to 2 hours late.

| Where | Good for | Notes |
|---|---|---|
| Your laptop / desktop | Trying it out | Links only open on your home Wi-Fi, and the computer must be on at briefing time |
| Home server / Raspberry Pi | Always-on at home | To open links on mobile data, add a free [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) or Tailscale |
| Any VPS (Hetzner, DigitalOcean, AWS Lightsail…) | Best | `docker compose up -d`. Put it behind a domain with HTTPS (Caddy or nginx) |
| Docker platforms (Railway, Fly.io, Render…) | Easy | Needs an **always-on** plan and a **persistent disk** mounted at `/data`. Free plans that sleep will miss briefings |

After hosting online, set **Public address** in *General settings* (e.g. `https://briefings.example.com`), so
the links in your messages open from anywhere. If you use HTTPS, also set `COOKIE_SECURE=1`.

Run **one copy** of the app only, or every briefing is sent twice.

---

## Everyday use

| I want to… | Do this in the dashboard |
|---|---|
| Change time / days / Telegram or email | Open the briefing card → change → **Save changes** |
| Change what a briefing covers | Edit the "What should this briefing contain?" box |
| Get news from other sites | Edit the briefing's **News sources** box (one RSS link or search words per line) |
| Add a new topic | **+ Add briefing** → name → write the topic in plain English → Save |
| Pause a briefing | Turn its switch off |
| Get one right now | **▶ Run now** |
| See past briefings | "Latest briefings" (each one has its own private link) |

The AI remembers the last 7 days of stories (change it in General settings), so news isn't repeated unless
something new happened.

### Command line (optional)
```bash
python app.py list                 # show briefings
python app.py run business         # make one now and send it (uses AI credit)
python app.py reset-password       # forgot your password
```

### Settings by environment variable (optional)
For automated deploys you can skip the dashboard for some settings. These override what's saved in the
dashboard. See `.env.example`.
`PORT`, `DATA_DIR`, `PUBLIC_URL`, `ADMIN_PASSWORD`, `COOKIE_SECURE`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD`, `EMAIL_TO`.

---

## Good to know

- **Your data**: everything (settings, keys, briefings) is in the `data/` folder (`/data` in Docker).
  **Back it up.** Keys are stored on your server only and are never shown again in the dashboard.
- **Privacy**: briefing pages open without a password, but only through their long secret link.
  The dashboard always needs your password.
- **Cost**: in Free mode, **nothing**. The free Gemini tier has daily limits, so a few briefings a day are fine.
  If you hit the limit you'll get a "free limit used up" message, and it resets daily. Gemini 4 Argon needs billing.
  Google Search mode is paid per use (roughly $0.10–0.40 per long briefing on Gemini 3.8 Flash; rough estimate).
- **If Gemini is busy** ("overloaded", common on the free tier): the app switches to a lighter free model
  (Gemini 3.5 Flash-Lite) for that briefing. The page footer shows which model wrote it.
- **If something fails**: it retries once after 10 minutes. If it still fails, you get a short
  "could not be created today" message, and the reason shows in *Recent activity*.
- **Accuracy**: the AI must use real sources and link them, and every link is checked. Links that don't open
  are marked ⚠️. Double-check before making money decisions.

## Project files

```
app.py                     ← start here: python app.py
scheduler/
  web.py                   ← web server: setup, login, dashboard API, briefing pages
  static/dashboard.html    ← the dashboard (one file, no build step)
  jobs.py                  ← scheduler: when to run, retries, sending
  generator.py             ← asks Gemini to write (free mode or Google Search mode)
  news.py                  ← free mode: collects today's news from RSS feeds / Google News
  db.py                    ← SQLite storage + validation
  linkcheck.py, render.py, notify.py
briefings/*.md             ← starter topics added on first start
Dockerfile, docker-compose.yml
tests/                     ← pytest (no keys needed)
qa/e2e.py                  ← full browser test with fake Gemini/Telegram/email/news
qa/check_gemini.py         ← what your Gemini key allows
qa/check_sources.py        ← are your news sources working and fresh?
```
