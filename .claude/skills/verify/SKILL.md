---
name: verify
description: Check that everything in the daily-scheduler project still works after a change. Runs the tests, the full browser test, a live start of the app, and sync/security checks. Use before saying any change is done, or when the user asks "is everything OK?".
---

# Verify the project

Run every step and report each result. Don't stop at the first failure.

1. **Environment**: create `.venv` if it's missing:
   `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt`

2. **Tests**: `.venv/bin/python -m pytest`. Covers storage and validation, scheduling and retries,
   making and sending briefings (with Gemini faked), login/setup/CSRF, the API, secret handling and Gemini errors.

3. **Browser test** (needs Google Chrome): `.venv/bin/python qa/e2e.py`
   Starts the real app with fake Gemini/Telegram/email and clicks through setup, keys, test message, editing,
   adding, deleting, Run now, the briefing link, log out/in and an XSS check. **Look at the screenshots**
   in `qa/screenshots/` for layout problems (phone and desktop, light and dark).

4. **Live start** with a throwaway database:
   `DATA_DIR=$(mktemp -d) PORT=8799 .venv/bin/python app.py`, run in the background.
   Then `curl -s localhost:8799/healthz` should return `{"ok":true}`, and `/dashboard` should redirect to `/setup`.
   The log should show the setup code. Stop it afterwards.

5. **Sync checks** (AGENTS.md rule 1):
   - `THINKING_LEVELS` in `scheduler/generator.py` has every value of `db.EFFORTS`:
     `.venv/bin/python -c "from scheduler import db, generator; print(set(dict(db.EFFORTS)) - set(generator.THINKING_LEVELS) or 'ok')"`
   - Every `db.SECRETS` name appears in `dashboard.html` `CONNECTIONS` (except smtp_*), `.env.example` and the README.
   - `dashboard.html` doesn't hard-code models or efforts (they come from `/api/state`).

6. **Safety scan**:
   - `grep -n "innerHTML" scheduler/static/dashboard.html` finds nothing.
   - `git status --short` shows no `data/`, `.env`, `qa/screenshots/` or `.venv/`.
   - `grep -rnE "AIza[0-9A-Za-z_-]{20,}|[0-9]{8,10}:[A-Za-z0-9_-]{30,}" --exclude-dir=.venv --exclude-dir=.git .` finds no real keys.

7. **Report** in short, simple sentences:
   - ✅ what passed
   - ❌ what failed and what you fixed (or what the user must do)
   - ⚠️ what can't be checked here: a real Gemini call (needs billing and costs credit), real Telegram/email,
     a Docker build if Docker isn't installed, and hosting on the user's server.
