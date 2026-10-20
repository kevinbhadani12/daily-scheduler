# Daily Scheduler: rules for AI coding assistants

These rules apply to every assistant working in this repo (Claude Code, Cursor, etc.).
`CLAUDE.md` and `.cursor/rules/` build on this file. Keep this file as the single source of truth.

## What this project is

One self-hosted app that writes AI briefings on a schedule and sends the link by Telegram and email.
It must **run anywhere** (laptop, Raspberry Pi, VPS, Docker platforms) with **no external setup** other than
the user's own API keys. **Don't add dependencies on GitHub, cloud services or extra servers** (no Redis,
no Postgres, no cron, no CI deploys).
The **reader is a beginner**. Everything they see (briefings, messages, errors, dashboard, README) must be in
simple, short, plain English.

```
app.py ─┬─ web.py (Flask, served by Waitress)
        │    /setup /login /dashboard  /api/*  (password + CSRF)      /b/<token> (public secret link)
        └─ jobs.py scheduler thread (every 30 s) → is_due → run_briefing
               → generator.py (Gemini + Google Search) → linkcheck → render → db.save_issue
               → notify.py (Telegram + email with PUBLIC_URL/b/<token>)
db.py: SQLite in DATA_DIR/app.db: settings, secrets, briefings, runs, issues
```

| Path | Role |
|---|---|
| `app.py` | Entry point and CLI: serve (default), `list`, `run`, `reset-password`, `add` |
| `scheduler/db.py` | Schema, settings, secrets, briefings, runs, issues, **all validation**, `MODELS`/`EFFORTS` |
| `scheduler/jobs.py` | `is_due`, `run_briefing`, retries, scheduler loop |
| `scheduler/web.py` | Flask app: setup, login, dashboard, JSON API, briefing pages |
| `scheduler/static/dashboard.html` | Single-file dashboard (vanilla JS, no build step, no CDN) |
| `scheduler/generator.py` | Gemini call, system prompt, `<summary_json>` parsing |
| `scheduler/notify.py` | Telegram and Gmail senders (read keys via `db.get_secret`) |
| `scheduler/render.py` / `linkcheck.py` | Sanitized HTML pages / dead-link marking |
| `briefings/*.md` | Starter prompts, imported once on first start |
| `Dockerfile`, `docker-compose.yml` | Container deploy (data volume at `/data`) |
| `tests/` | pytest suite. Fakes Gemini, network and data folder |
| `qa/e2e.py` | Real app + real Chrome, fake Gemini/Telegram/email |

## Commands

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt   # setup
.venv/bin/python -m pytest          # all unit/integration tests (no keys, no cost)
.venv/bin/python qa/e2e.py          # full browser test (needs Google Chrome), screenshots in qa/screenshots/
DATA_DIR=/tmp/ds .venv/bin/python app.py    # run locally with a throwaway database
```
`app.py run <id>` and the dashboard's Run now / Send test message call paid APIs or send real messages.
**Ask the user before using them with real keys.** Never use the user's real `data/` folder for experiments.

## Rules

### 1. Keep things in sync
- **Lists of choices live in `db.py` only** (`MODELS`, `EFFORTS`, `ALL_DAYS`, `CHANNELS`). The dashboard gets
  them from `/api/state`. Never hard-code them in `dashboard.html`. `generator.THINKING_LEVELS` must have a key
  for every `EFFORTS` value.
- **New setting**: `db.DEFAULT_SETTINGS` + `db.validate_settings` + dashboard General settings + README + tests.
- **New briefing field**: `Briefing` dataclass + `SCHEMA` (add a migration for existing databases) +
  `validate_briefing` + `save_briefings`/`_row_to_briefing` + dashboard card + tests.
- **New secret**: `db.SECRETS` + dashboard `CONNECTIONS` + `.env.example` + README key table.
- **Summary contract**: `SYSTEM_PROMPT` asks for `<summary_json>` (`title, highlights, mood, headlines`).
  `_split_summary`, `jobs._run` and `notify.py` use those keys. Change them together.

### 2. Gemini API
- Official `google-genai` SDK: `genai.Client(api_key=...)` + `client.models.generate_content(...)`.
  The key comes from `db.get_secret("gemini_api_key")` (env `GEMINI_API_KEY` wins).
- **Never guess SDK names or model IDs.** Inspect the installed SDK or check ai.google.dev first.
- Tools: `google_search` + `url_context`. Grounding needs a billing-enabled key (a 429 means billing is off).
- Never show `part.thought` text. The SDK auto-resumes `CONTINUATION`, so don't add a manual loop.
- Every failure becomes a `GenerationError` that tells a beginner what to do.

### 3. Security (the app may be on the public internet)
- Dashboard and `/api/*` need login. Every non-GET API call needs the `X-CSRF-Token` header (`login_required`).
- First-time setup needs the one-time code printed in the log. Keep that.
- Secrets: never return them from the API (only `secret_status`), never log them, and never put them in
  exception text. Telegram URLs contain the token, so wrap `requests` errors.
- AI output is untrusted. Render only through `render.markdown_to_html` (nh3). Briefing pages send a strict CSP.
- Dashboard: build DOM with `h()` / `textContent`. **Never `innerHTML`** with server or user data.
- Briefing links use `secrets.token_urlsafe`. Never switch to guessable ids.

### 4. Scheduling behaviour (don't break these)
- `is_due`: enabled, day selected, within `[time, time + CATCH_UP]`, not running, no scheduled success today,
  fewer than `MAX_ATTEMPTS` failures, `RETRY_AFTER` since the last failure. Manual runs don't count.
- Only the last failed scheduled try (or any failed Run now) sends a "failed" message.
- `db.init()` marks leftover `running` runs as failed. One app instance only (documented in README).

### 5. Code style
- Python 3.10+ (CI/Docker use 3.12). `from __future__ import annotations` at the top of modules.
- Match existing style: small functions, short docstrings, few comments, friendly error text.
- Tests use the autouse `sandbox` fixture (temp `DATA_DIR`, no env keys, fake link checker) and `tests/fakes.py`.
  Never call real APIs in tests.
- Runtime dependency → `requirements.txt`. Test-only → `requirements-dev.txt`. Keep the dependency list small.

### 6. Writing briefing prompts
Plain-English instructions, written for a beginner reader: what to cover and how many items, the structure for
each item, simple-language rules, "only real recent facts from reliable sources, link every source, never invent
facts", education-not-advice wording for money or health, and a target reading time. Don't describe the output
format: `SYSTEM_PROMPT` adds it. Users edit prompts in the dashboard. `briefings/*.md` are only first-start seeds.

## Definition of done
1. `.venv/bin/python -m pytest` passes, with tests added or updated for the changed behaviour.
2. UI or API change → `.venv/bin/python qa/e2e.py` passes, and you've looked at the screenshots.
3. Rule 1 items your change touches are updated, and the README is updated if the user would act differently.
4. Tell the user what you could **not** verify (real Gemini call, real Telegram/email, Docker build, hosting).
