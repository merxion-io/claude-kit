---
name: compact-now
description: "Manual check-and-compact of the context: show window fill (tokens/%), write a checkpoint if high, prompt the operator to press /compact. Triggers: /compact-now, compact, how many tokens, check the context, checkpoint and compact."
---

Manual counterpart of the `context-guard` Stop hook.

1. Run `bash ~/.claude/hooks/context-fill.sh` (prints `<tokens> <pct> <k>`); tell the operator in one line: `Context: <k>k/<threshold>k · <pct>%` (threshold = `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / 1000, unset → 1000k; pct is of it).
2. `pct >= 75` or the operator explicitly asks to save → skill `checkpoint`. Otherwise no checkpoint; say so.
3. You have no `/compact`: only the operator or auto-compact (a bit below that threshold) starts it; for an executor the observer may type it (its role text). After the checkpoint say in one line: "Checkpoint written, you can press `/compact`".

Give only the checkpoint path, do not retell it.
