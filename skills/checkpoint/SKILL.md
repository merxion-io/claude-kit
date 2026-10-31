---
name: checkpoint
description: "Write a durable session checkpoint (task, decisions, state, next step, uncommitted work, anchors) to a file so nothing is lost on context compaction or a new session. Use proactively when context gets heavy or before a long/risky operation, and on request. Also the manual check of the context: show window fill and save when high. Triggers: checkpoint, save state, save point, compact, how many tokens, check the context, checkpoint and compact."
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

## Context check (on "compact", "how many tokens", "check the context")

1. Run `bash ~/.claude/hooks/context-fill.sh` (prints `<tokens> <pct> <k>`); tell the operator in one line: `Context: <k>k/<threshold>k · <pct>%` (threshold = `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / 1000, unset → 1000k; pct is of it).
2. `pct >= 75` or the operator asks to save → write the checkpoint as above. Otherwise none; say so.
3. The session has no `/compact`: only the operator or auto-compact (a bit below that threshold) starts it; for an executor the observer may type it. After the checkpoint say in one line: "Checkpoint written, you can press `/compact`".

## After

Tell the path in ONE line, no readback. Never treat another checkpoint (of a different session/task) as current truth, never read it "just in case".
