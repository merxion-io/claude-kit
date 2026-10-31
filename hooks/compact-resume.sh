#!/usr/bin/env bash
# SessionStart(compact): after the window is compacted, puts the checkpoint of EXACTLY THIS
# session into the context — whole, as text. Before, the hook only asked to "read the freshest file in
# .claude/checkpoints/", and the freshest there could belong to a completely different task from a week
# ago — and the session came back to not its own work. A hook's output over 10000 UTF-16 units (roles.CONTEXT_LIMIT; an emoji is two) arrives as a 2KB
# preview, so a longer checkpoint is cut to fit, with a last line naming the file.
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

base='The context was just compacted. Treat the summary as incomplete: restore the working state from durable sources and continue the interrupted task (git status --short: uncommitted; the spec of the project (its CLAUDE.md names where): the truth about behaviour). The checkpoint is written by another model from a digest: check each "done" in it against the files and git before relying on it.'
[ -n "$sess" ] && [ -n "$manual" ] && base="$base Manual notes of this session, read them: $manual"
if [ -n "$cp_file" ] && [ -s "$cp_file" ]; then
  jq -rn --arg base "$base" --arg file "$cp_file" --rawfile body "$cp_file" '
    def output($c): {hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}} | tojson;
    ($base + "\n\n--- CHECKPOINT OF THIS SESSION (" + $file + ") ---\n") as $head
    | ("\n--- checkpoint cut here, the rest is in " + $file + " ---") as $cut
    | def cut_at($n): output($head + $body[:$n] + $cut);
      def units: explode | map(if . > 65535 then 2 else 1 end) | add;
      def fits: units < 9999;  # UTF-16 units, as the harness counts; jq -r adds a newline
      def fit($low; $high): if $high - $low <= 1 then cut_at($low)
        else ((($low + $high) / 2) | floor) as $mid | if (cut_at($mid) | fits) then fit($mid; $high) else fit($low; $mid) end end;
    output($head + $body + "\n--- end of checkpoint ---") as $whole
    | if ($whole | fits) then $whole else fit(0; $body | length) end'
else
  jq -cn --arg c "$base This session has no checkpoint. Do NOT take other files from .claude/checkpoints/: they belong to other tasks." '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
fi
