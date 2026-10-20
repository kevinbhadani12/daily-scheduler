# Daily Scheduler: rules for AI coding assistants

These rules apply to every assistant working in this repo (Claude Code, Cursor, etc.).
`CLAUDE.md` and `.cursor/rules/` build on this file. Keep this file as the single source of truth.

## What this project is

The app writes AI briefings (business news, stock market, …) on a schedule and sends the link by Telegram and email.
The **reader is a beginner**. Everything they see (briefings, notifications, error messages, dashboard, README)
must be in simple, short, plain English.

```
GitHub Actions (every 15 min) → main.py generate → Gemini + Google Search → Markdown
  → linkcheck marks dead links → render.py (sanitized HTML) → docs/<id>/<date>.html
  → git push (GitHub Pages) → main.py notify → Telegram + email with the link
docs/dashboard.html → GitHub API → edits config.yaml and briefings/*.md
```

| Path | Role |
|---|---|
| `config.yaml` | Schedule and settings (times, days, channels, model, effort) |
| `briefings/*.md` | One plain-English prompt per briefing |
| `main.py` | CLI: `generate`, `notify`, `preview`, `test-notify`, `list` |
| `scheduler/config.py` | Loads and **validates** `config.yaml` |
| `scheduler/generator.py` | Gemini call, system prompt, `<summary_json>` parsing |
| `scheduler/linkcheck.py` | Marks source links that don't open |
| `scheduler/render.py` | Markdown → sanitized HTML pages and `docs/index.html` |
| `scheduler/notify.py` | Telegram and Gmail senders |
| `scheduler/store.py` | `data/history/*.json`, `data/state.json`, `.outbox.json` |
| `docs/dashboard.html` | Single-file settings dashboard (no build step) |
| `.github/workflows/daily.yml` | Schedule: generate → commit/push → notify |
| `tests/` | pytest suite. Fakes Gemini, network and file paths |

## Commands

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt   # setup
.venv/bin/python -m pytest          # run ALL tests (no API key or cost needed)
.venv/bin/python main.py list       # check config.yaml loads and see the schedule
```
`main.py preview <id>`, `generate` and `test-notify` call paid APIs or send real messages.
**Ask the user before running them.**

## Rules

### 1. Keep things in sync (most common source of bugs)
Some facts live in several places. When you change one, update all of them in the same change:

- **Config fields** (a new setting, renamed key, new allowed value):
  `scheduler/config.py` (parse + validate) · `docs/dashboard.html` (`normalize`, `toYaml`, `validate`, UI) ·
  `config.yaml` (with a comment) · `README.md` · `tests/test_config.py`.
- **Models / effort levels**: `config.py` `EFFORTS`, `generator.py` `THINKING_LEVELS`,
  dashboard `MODELS` / `EFFORTS`, `config.yaml` comments, README cost notes.
- **Secrets / env vars**: `.github/workflows/daily.yml` `env:`, `.env.example`, README secrets table, `notify.py`/`generator.py`.
- **Summary contract**: `SYSTEM_PROMPT` asks for `<summary_json>` with `title, highlights, mood, headlines`.
  `_split_summary`, `main.py` (history/outbox) and `notify.py` read those keys. Change all of them together.

### 2. Gemini API
- Use the official `google-genai` SDK: `genai.Client()` + `client.models.generate_content(...)`.
  Key comes from `GEMINI_API_KEY`.
- **Never guess SDK names or model IDs.** Check the installed SDK
  (`.venv/bin/python -c "from google.genai import types; print(types.X.model_fields)"`) or the official docs
  at ai.google.dev. Models change often, so confirm an ID exists before using it.
- Tools: `google_search` + `url_context`. Grounding needs a paid (billing-enabled) key.
- Never show `part.thought` text to the reader. The SDK auto-resumes `CONTINUATION` responses, so don't add a manual loop.
- Turn API failures into `GenerationError` with a message that tells a beginner what to do.

### 3. Safety and security
- Never commit secrets. `.env` (root or `scheduler/`) is git-ignored. Never print or log key values.
- AI output is untrusted. It's rendered only through `render.markdown_to_html` (nh3 sanitizer). Don't bypass it.
- `docs/dashboard.html`: build DOM with the `h()` helper / `textContent`. **Never `innerHTML` with repo or user data.**
  External scripts only from cdnjs with an **exact version + `integrity` (SRI) hash**. The GitHub token stays in
  `localStorage` only, so never send it anywhere except `api.github.com`.
- The workflow passes `workflow_dispatch` inputs through `env:`, never by interpolating `${{ }}` into shell code.

### 4. Workflow behaviour (don't break these)
- Order is **generate → commit/push → notify**, so links work when the message arrives.
- Checkout uses the default branch (latest commit) and `git pull --rebase` before push (the dashboard may commit meanwhile).
- `data/` and `docs/<id>/` are written by the bot. Don't hand-edit them. `docs/dashboard.html` is hand-written.
- A briefing is tried at most `MAX_ATTEMPTS` per day. Only the last failure sends a "failed" message.

### 5. Code style
- Python 3.12 in CI. Keep `from __future__ import annotations` at the top of modules. Stdlib + `requirements.txt` only.
- Match existing style: small functions, short docstrings, few comments, friendly error text.
- Tests must never touch the real `docs/`, `data/`, network or APIs. Use the `sandbox` fixture and `tests/fakes.py`.
- New dependency → `requirements.txt` (runtime) or `requirements-dev.txt` (tests only).

### 6. Writing briefing prompts (`briefings/*.md`)
Plain English instructions to the AI. Include: what to cover, how many items, structure per item,
beginner-friendly language rules, "only real sources with links, never invent facts", and target reading time.
Output format (Markdown, `<summary_json>`) is handled by `SYSTEM_PROMPT`. Don't repeat it in prompt files.

## Definition of done
1. `.venv/bin/python -m pytest` passes. Add or adjust tests for the behaviour you changed.
2. `.venv/bin/python main.py list` runs without a config error.
3. Everything in rule 1 that your change touches is updated.
4. README updated if the user would do anything differently.
5. Tell the user what you could **not** verify (e.g. real Gemini call, real Telegram send, dashboard in a browser).
