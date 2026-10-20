---
name: verify
description: Check that everything in the daily-scheduler project still works after a change. Runs the test suite and config check, and confirms the files that must stay in sync really are. Use before saying any change is done, or when the user asks "is everything OK?".
---

# Verify the project

Run every step and report each result. Don't stop at the first failure.

1. **Environment**: create `.venv` if it's missing:
   `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt`

2. **Tests**: `.venv/bin/python -m pytest`
   These cover config validation, Gemini response handling (faked), the full generate pipeline, retries and failure
   messages, notifications, and the dashboard's save format (runs its JavaScript in Node).
   Note any **skipped** tests and why (e.g. no Node or no internet).

3. **Config**: `.venv/bin/python main.py list` must print the schedule without "Problem in config.yaml".

3b. **Dashboard in a real browser** (needs Google Chrome): `.venv/bin/python qa/dashboard_e2e.py`
   It clicks through connect, edit, add, delete, save, Run now, reload and an XSS check against a fake GitHub API,
   then saves screenshots in `qa/screenshots/`. Look at them for layout problems.

4. **Sync checks** (AGENTS.md rule 1). For each item, compare the places and fix any mismatch:
   - Secrets: the names under `env:` in `.github/workflows/daily.yml` match `.env.example` and the README secrets table.
     Check with `grep -ho "[A-Z_]*_\(KEY\|TOKEN\|ID\|ADDRESS\|PASSWORD\|TO\)\b" .github/workflows/daily.yml .env.example README.md | sort | uniq -c`
   - Effort levels: `EFFORTS` in `scheduler/config.py` = keys of `THINKING_LEVELS` in `scheduler/generator.py`
     = `EFFORTS` in `docs/dashboard.html`.
   - Every `prompt_file` in `config.yaml` exists, and no file in `briefings/` is left unused (unused files are only a warning).
   - The model IDs in `config.yaml` appear in the dashboard `MODELS` list.

5. **Safety scan**:
   - `git status --short` shows no `.env`, `.outbox.json`, `preview/` or `.venv/`.
   - `grep -n "innerHTML" docs/dashboard.html` finds nothing.
   - `grep -rn "AIza\|github_pat_\|sk-ant-" --exclude-dir=.venv .` finds no real-looking keys (placeholders in `.env.example` are fine).

6. **Report** in short, simple sentences:
   - ✅ what passed
   - ❌ what failed and what you fixed (or what the user must do)
   - ⚠️ what can't be checked here: a real Gemini call (needs the key and costs credit), real Telegram/email delivery,
     GitHub Actions and Pages in the cloud, and the dashboard in a real browser.
