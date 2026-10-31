#!/usr/bin/env bash
# SessionEnd: insurance for when a session ended without ever compacting —
# then PreCompact was never called and there would be no note at all. We write only for sessions
# that grew to a noticeable window: nothing to lose on short ones, and the call is not free.
input="$(cat)"
q() { printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null; }
tp="$(q .transcript_path)"; sid="$(q .session_id)"; reason="$(q .reason)"
[ -n "$sid" ] || sid="$(basename "${tp:-}" .jsonl)"
sess="${sid:0:8}"
[ "$reason" = clear ] && exit 0

read -r cur _ _ < <(bash "$(dirname "$0")/context-fill.sh" "$tp" 2>/dev/null)
case "${cur:-0}" in ''|*[!0-9]*) cur=0;; esac
[ "$cur" -ge "${SESSIONEND_MIN:-200000}" ] || exit 0

# session_watch runs `claude -p`; a session started without nvm in its PATH has no claude here: take it from nvm's node
command -v claude >/dev/null || for b in "$HOME"/.nvm/versions/node/*/bin; do [ -x "$b/claude" ] && { export PATH="$b:$PATH"; break; }; done
python3 "$HOME/.claude/tools/session_watch.py" --detach --deadline 200 --session "$sess" --force --quiet >/dev/null 2>&1 &
exit 0
