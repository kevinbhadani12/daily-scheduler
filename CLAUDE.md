@AGENTS.md

## Claude Code notes

- Project skills (in `.claude/skills/`):
  - `/add-briefing`: write a good prompt and add a new scheduled briefing.
  - `/check-gemini`: why Gemini fails / what the key allows (free vs paid, "I have Gemini Pro").
  - `/news-sources`: pick, test or fix the news feeds a briefing uses in Free mode.
  - `/verify`: run every check (tests, browser test, live start, sync, security) and report what passed and what couldn't be checked.
- After finishing any change, run the `/verify` steps before saying it's done.
- The user is learning. Explain results in short, simple sentences.
