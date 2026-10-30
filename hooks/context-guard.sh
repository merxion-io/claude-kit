#!/usr/bin/env bash
# Stop hook: context fill SENSOR. No longer blocks the turn and does not ask for a checkpoint.
# The note is written by the `precompact.sh` hook exactly at the moment of compaction. The earlier conclusion "the compaction line floats 606k…806k" is false:
# manual /compact runs got into the sample (in 26b00260 «700k» — manual); auto — 104 of 104 at 800–805k at 82 % of 1M (2026-09-18)
here="$(cd "$(dirname "$0")" && pwd)"
input="$(cat)"
q() { printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null; }
tp="$(q .transcript_path)"

read -r cur pct k < <(bash "$here/context-fill.sh" "$tp")
[ "${cur:-0}" -gt 0 ] 2>/dev/null || exit 0

# window — from CLAUDE_CODE_AUTO_COMPACT_WINDOW; auto-compaction fires a bit below the window, we warn from 3/4
win=${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-1000000}; WARN_AT=$(( win * 3 / 4 ))
msg="🧭 Context: ${k}k/$(( win / 1000 ))k · ${pct}%"
[ "$cur" -ge "$WARN_AT" ] && msg="$msg · compaction zone, the checkpoint is kept automatically"
jq -cn --arg m "$msg" '{systemMessage:$m}'
exit 0
