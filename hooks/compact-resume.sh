#!/usr/bin/env bash
# SessionStart(compact): after the window is compacted, puts the checkpoint of EXACTLY THIS
# session into the context — whole, as text. Before, the hook only asked to "read the freshest file in
# .claude/checkpoints/", and the freshest there could belong to a completely different task from a week
# ago — and the session came back to not its own work.
input="$(cat)"
q() { printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null; }
tp="$(q .transcript_path)"; cwd="$(q .cwd)"; sid="$(q .session_id)"
[ -n "$sid" ] || sid="$(basename "${tp:-}" .jsonl)"
sess="${sid:0:8}"
[ -n "$cwd" ] || cwd="$PWD"
# The directory is at the NEAREST ANCESTOR with `.claude`: a session in a project subdirectory (measured 2026-08-13:
# cwd=<project>/web) used to fall into $HOME and not find its own note
dir="$HOME/.claude/checkpoints"; d="$cwd"
while [ -n "$d" ] && [ "$d" != / ]; do
  if [ -d "$d/.claude" ] && [ "$d" != "$HOME" ]; then dir="$d/.claude/checkpoints"; break; fi
  d="$(dirname "$d")"
done
cp_file=""; [ -n "$sess" ] && cp_file="$dir/$sess-session.md"
# manual agent notes (`<sess>-<topic>.md`) — paths only: the agent writes them, and they hold decisions that may be missing from the digest
manual="$(ls -t "$dir/$sess"-*.md 2>/dev/null | grep -v -- '-session\.md$' | head -5 | tr '\n' ' ')"

base='The context was just compacted. Treat the summary as incomplete: restore the working state from durable sources and continue the interrupted task (git status --short: uncommitted; the project's spec (its CLAUDE.md names where): the truth about behaviour). The checkpoint is written by another model from a digest: check each "done" in it against the files and git before relying on it.'
[ -n "$sess" ] && [ -n "$manual" ] && base="$base Manual notes of this session, read them: $manual"
if [ -n "$cp_file" ] && [ -s "$cp_file" ]; then
  ctx="$base

--- CHECKPOINT OF THIS SESSION ($cp_file) ---
$(head -c 24000 "$cp_file")
--- end of checkpoint ---"
else
  ctx="$base This session has no checkpoint. Do NOT take other files from .claude/checkpoints/: they belong to other tasks."
fi
jq -cn --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
