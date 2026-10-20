# Daily Scheduler

Get easy-to-understand AI briefings (business news, stock market, anything you want) every day at the time
you choose. You get the link on **Telegram** and **email**.

- **AI writes it**: Google Gemini searches Google for real news and explains it simply, with source links.
- **One small app** runs anywhere: your laptop, a home PC or Raspberry Pi, any VPS, or Docker hosting.
- **Everything is set in the browser**: times, days, topics, keys. No config files, GitHub or tokens needed.

```
┌─────────────────────── Daily Scheduler (one app) ───────────────────────┐
│  Dashboard (password)   ──►  settings, briefings, keys  ──►  data/app.db │
│  Scheduler (every 30 s) ──►  due? → Gemini + Google Search → web page    │
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
   | Gemini API key | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). **Turn on billing**: Google Search (needed for real news) doesn't work on the free tier |
   | Telegram bot token | In Telegram, message **@BotFather** → `/newbot` |
   | Telegram chat id | Send your bot a message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": …}` |
   | Gmail address + app password | Turn on 2-Step Verification, then [create an app password](https://myaccount.google.com/apppasswords) |

3. **Your briefings**: set the time, days and topic, then press **▶ Run now** to get your first briefing.

The dashboard shows a "Finish setting up" checklist until everything is done.

---

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
- **Cost**: the app is free. Gemini is paid per use. With `gemini-3.8-flash`, a long daily briefing is roughly
  **$0.10–0.40 per day** (rough estimate). Google Search includes 5,000 free searches a month.
  Google has announced price rises for Gemini 3.8 Flash (from 1 Jan 2027) and Gemini 4 Argon (from 1 Dec 2026).
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
  generator.py             ← asks Gemini to research and write
  db.py                    ← SQLite storage + validation
  linkcheck.py, render.py, notify.py
briefings/*.md             ← starter topics added on first start
Dockerfile, docker-compose.yml
tests/                     ← pytest (no keys needed)
qa/e2e.py                  ← full browser test with fake Gemini/Telegram/email
```
