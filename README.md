# Daily Scheduler

Get easy-to-understand AI briefings (business news, stock market, anything you want) every day at the time you choose.

- **AI writes it**: Google Gemini searches Google for real news and explains it simply, with source links.
- **Full briefing is a web page**: it's easy to read on phone or laptop, with tables, sections and a quiz.
- **You get a link**: a Telegram message and an email with the top 3 points and a "Read the full briefing" button.
- **Runs in the cloud for free** (GitHub Actions), so your laptop can be off.

```
Every 15 min GitHub checks config.yaml → a briefing is due?
   → Gemini researches with Google Search and writes it (using your prompt file)
   → dead source links are checked and marked
   → page is published on GitHub Pages
   → link sent to Telegram + email
```

---

## ⚙️ Settings dashboard (easiest way)

Open **`https://YOUR-GITHUB-USERNAME.github.io/daily-scheduler/dashboard.html`** on your phone or laptop. You can:

- turn briefings on/off, change **time**, **days**, and **Telegram/Email**
- edit what each briefing should contain (the prompt), or **add / delete** briefings
- press **▶ Run now** to get a briefing immediately
- see recent runs and whether they worked

The first time, it asks for a GitHub token (it's kept only in that browser):
GitHub → Settings → Developer settings → **Fine-grained tokens** → *Only select repositories*: `daily-scheduler` →
Permissions: **Contents: Read and write**, **Actions: Read and write**.

Saved changes go straight into the repo and apply from the next check (within 15 minutes).
The dashboard page is public, but nobody can change anything without your token.

## How to change things by editing files

| I want to… | Do this |
|---|---|
| Change the time | Edit `time: "07:00"` in `config.yaml` |
| Change which days | `days: daily`, `days: weekdays`, or `days: [mon, wed, fri]` |
| Change what the briefing says | Edit the prompt file, e.g. `briefings/business.md` |
| Add a new briefing | Create `briefings/my-topic.md` with your instructions in plain English, then add a block to `config.yaml` (copy an existing one and change `id`, `name`, `prompt_file`, `time`) |
| Turn a briefing off | `enabled: false` |
| Only Telegram (or only email) | `deliver: [telegram]` |
| Get a briefing right now | GitHub → **Actions** → **Daily briefings** → **Run workflow** → type the id (e.g. `business`) |

The AI remembers the last 7 days of stories (`data/history/`), so it won't repeat news unless something new happened.

---

## One-time setup (about 20 minutes)

### 1. Put the project on GitHub
Create a **public** repository named `daily-scheduler` on github.com, then from this folder:
```bash
git init && git add . && git commit -m "Daily scheduler"
git branch -M main
git remote add origin https://github.com/YOUR-GITHUB-USERNAME/daily-scheduler.git
git push -u origin main
```
> Why public? GitHub Pages and unlimited Actions minutes are free only for public repos. Your briefings (public news summaries) will be visible to anyone who has the link. Your keys stay private in Secrets.

### 2. Get your keys

**Gemini API key**: [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → Create API key.
Then **turn on billing** for that project (AI Studio → Billing). Google Search grounding is not available on the free tier, and the briefings need it to find real news.

**Telegram bot**
1. In Telegram, open **@BotFather** → send `/newbot` → pick a name. Copy the **token**.
2. Open your new bot and send it any message (e.g. "hi").
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and find `"chat":{"id": 123456789` (that number is your **chat id**).

**Gmail app password**
1. Turn on 2-Step Verification in your Google account.
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) → create one called "Daily Scheduler". Copy the 16-letter password.

### 3. Add the keys to GitHub
Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | your Gemini key |
| `TELEGRAM_BOT_TOKEN` | bot token |
| `TELEGRAM_CHAT_ID` | your chat id |
| `EMAIL_ADDRESS` | your Gmail address |
| `EMAIL_APP_PASSWORD` | the 16-letter app password |
| `EMAIL_TO` | *(optional)* where to send, comma-separated. Defaults to `EMAIL_ADDRESS` |

### 4. Turn on the web pages
Repo → **Settings → Pages** → Source: **Deploy from a branch** → Branch: `main`, folder: `/docs` → Save.

Then in `config.yaml`, replace `YOUR-GITHUB-USERNAME` in `site_url` with your username, and commit and push.

### 5. Test it
Repo → **Actions** → **Daily briefings** → **Run workflow** → type `business` → Run.
In about 5–10 minutes you should get a Telegram message and an email. 🎉

From now on, it runs by itself every day.

---

## Testing on your laptop (optional)

```bash
uv venv --python 3.12 .venv && uv pip install -r requirements.txt
cp .env.example .env              # then fill in your keys
.venv/bin/python main.py list            # see your briefings and times
.venv/bin/python main.py test-notify     # check Telegram + email work
.venv/bin/python main.py preview business  # write one briefing into preview/ (nothing is sent)
```

---

## Good to know

- **Timing:** GitHub checks every 15 minutes and is sometimes a few minutes late, and writing a long briefing takes ~5–10 minutes. Expect it **10–30 minutes after** the time you set. Set the time a bit earlier if you want it ready by a fixed time.
- **Cost:** GitHub is free. Gemini is paid per use. With the default `gemini-3.8-flash`, a long briefing like `business.md` is roughly **$0.10–0.40 per day** (rough estimate; token usage and the number of searches are printed in each Actions run log). Google Search gives 5,000 free searches a month, which is far more than daily briefings use. Note that Google has announced Gemini 3.8 Flash prices will double from 1 January 2027. For the best quality, set `model: gemini-4-argon` (about 3× the price, and its price also doubles from 1 December 2026).
- **If something fails:** it retries once on the next check. If it still fails, you get a "could not be created today" message instead of silence.
- **Accuracy:** Gemini is told to use only real sources and link them, and every link is checked. Links that don't open are marked ⚠️. Still double-check sources before making money decisions.
- **Inactivity:** GitHub pauses scheduled workflows in repos with no activity for 60 days. Daily briefings commit to the repo, so this won't happen while it's running.

## Project files

```
config.yaml                 ← your settings (times, days, on/off)
briefings/*.md              ← what each briefing should contain (plain English)
main.py                     ← commands: generate, notify, preview, test-notify, list
scheduler/
  generator.py              ← asks Gemini to research and write
  linkcheck.py              ← checks source links
  render.py                 ← builds the web pages
  notify.py                 ← Telegram + email
  store.py                  ← history and daily state
  config.py                 ← reads config.yaml
docs/                       ← published web pages (GitHub Pages)
data/                       ← memory of past briefings
.github/workflows/daily.yml ← the cloud schedule
```
