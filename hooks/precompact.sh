#!/usr/bin/env bash
# PreCompact: the only DETERMINISTIC moment — fires exactly at compaction,
# both auto and manual. Does two things: makes sure the session checkpoint exists, and
# prints instructions for the compaction itself to stdout (PreCompact stdout = custom compaction
# instructions, that is how the CLI works).
#
# There are NO thresholds here: the hook fires exactly at the moment of compaction, no need to guess "how long before"
input="$(cat)"
q() { printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null; }
tp="$(q .transcript_path)"; cwd="$(q .cwd)"; sid="$(q .session_id)"; trg="$(q .trigger)"
[ -n "$sid" ] || sid="$(basename "${tp:-}" .jsonl)"
sess="${sid:0:8}"
[ -n "$cwd" ] || cwd="$PWD"
dir="$HOME/.claude/checkpoints"; d="$cwd"
while [ -n "$d" ] && [ "$d" != / ]; do
  if [ -d "$d/.claude" ] && [ "$d" != "$HOME" ]; then dir="$d/.claude/checkpoints"; break; fi
  d="$(dirname "$d")"
done
cp_file="$dir/$sess-session.md"

watch="$HOME/.claude/tools/session_watch.py"
# session_watch runs `claude -p`; a session started without nvm in its PATH has no claude here: take it from nvm's node
command -v claude >/dev/null || for b in "$HOME"/.nvm/versions/node/*/bin; do [ -x "$b/claude" ] && { export PATH="$b:$PATH"; break; }; done
# ALWAYS synchronous: compaction waits until the note is finished and starts right after it.
# There are no periodic checkpoints any more — operator decision 2026-08-13: one checkpoint per
# compaction, not "every N tokens". It costs ~40 seconds, exactly once per compact
if [ -f "$watch" ]; then
  python3 "$watch" --deadline 170 --session "$sess" --force --quiet >/dev/null 2>&1
fi

note=""
[ -s "$cp_file" ] && note="The full note of this session is in \`$cp_file\`: after compaction the SessionStart hook puts it back, no need to repeat its text in the summary."

cat <<EOF
Compaction triggered by: ${trg:-auto}. Keep in the summary first of all what cannot be restored from files:
1. The user's TASK and REAL INTENT, not a list of actions performed.
2. Decisions made TOGETHER WITH THEIR REASONS: otherwise they get rediscovered after compaction.
3. What was VERIFIED by measurement and what is only assumed: do not turn a hypothesis into a fact.
4. The exact next step and uncommitted paths.
5. Open questions to the user still unanswered.
Do not drop file paths, identifiers, measured numbers and command names: work continues from them.
$note
EOF
exit 0
