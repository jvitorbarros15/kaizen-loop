---
name: kaizen
description: Use when the user asks about their recorded Claude Code sessions, how well recent sessions went, or wants to grade, score or report on them with kaizen.
---

# kaizen

kaizen records every Claude Code session when it ends: the tool calls, token use, test runs and pull request links. Recordings stay on this machine, under `~/.kaizen`, with secrets removed before anything is written.

Commands the user can ask for:

- `kaizen report`: print the report for the last 20 sessions.
- `kaizen score --pending`: grade sessions that have no score yet.
- `kaizen import`: record sessions that already exist on disk.
- `kaizen calibrate`: grade a few sessions by hand and compare with the judge.
- `kaizen audit`: scan the store for secrets.
- `kaizen score --show-packet <id>`: show exactly what grading would send for one session, without sending it.

Privacy: grading sends a redacted summary of the session to a small model through the user's own Claude subscription. It goes to Codex only for repositories the user has listed in `~/.kaizen/config.toml`.
