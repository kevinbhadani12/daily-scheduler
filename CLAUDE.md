@AGENTS.md

## Claude Code notes

- Project skills (in `.claude/skills/`):
  - `/add-briefing`: add a new scheduled briefing end to end.
  - `/verify`: run every check (tests, config, sync between files) and report what passed and what couldn't be checked.
- After finishing any change, run the `/verify` steps before saying it's done.
- The user is learning. Explain results in short, simple sentences.
