@AGENTS.md

## Claude Code notes

- Project skills (in `.claude/skills/`):
  - `/add-briefing`: write a good prompt and add a new scheduled briefing.
  - `/verify`: run every check (tests, browser test, live start, sync, security) and report what passed and what couldn't be checked.
- After finishing any change, run the `/verify` steps before saying it's done.
- The user is learning. Explain results in short, simple sentences.
