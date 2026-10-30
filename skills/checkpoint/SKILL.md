---
name: checkpoint
description: "Write a durable session checkpoint (task, decisions, state, next step, uncommitted work, anchors) to a file so nothing is lost on context compaction or a new session. Use proactively when context gets heavy or before a long/risky operation, and on request. Triggers: checkpoint, save state, save point."
---

Resume-handoff: tight, factual, skimmable.

## Where

One topic = ONE file, rewritten whole; no dated copies.
- In a project: `.claude/checkpoints/<first-8-chars-of-session_id>-<topic>.md`. `<sess>-session.md` is TAKEN: the hook overwrites it before every compaction; write nothing there. Session id unknown → `<YYYY-MM-DD>-<topic>.md`; never take the freshest file in the directory (may be another session's).
- Outside a project: the same in `~/.claude/checkpoints/`.
- A durable milestone (not just state) is recorded in memory or the project's spec (its CLAUDE.md names where) by their rules. A checkpoint is ephemeral, memory permanent; do not duplicate one into the other.

## What (omit a heading only if empty)

- **Task & goal** — what, and why.
- **Decisions** — each with its rationale.
- **State** — done / in progress / blocked; verified vs assumed.
- **Next action** — the single exact step.
- **Uncommitted work** — from `git status --short`.
- **Key anchors** — `file:line`, IDs, commands, URLs.
- **Open questions** — awaiting the user.

## After

Tell the path in ONE line, no readback. Never treat another checkpoint (of a different session/task) as current truth, never read it "just in case".
