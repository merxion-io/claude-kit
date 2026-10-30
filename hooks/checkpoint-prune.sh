#!/usr/bin/env bash
# SessionStart: weeding .claude/checkpoints/ — a checkpoint is ephemeral, the folder is not a journal.
# A live note is safe: the session rewrites ITS OWN file in place, its mtime
# is always fresh and it never falls under the age threshold. We also clean service labels.
# We print nothing — the hook is silent. DRYRUN=1 → only show what would be deleted.
DAYS=${CHECKPOINT_KEEP_DAYS:-7}
input="$(cat 2>/dev/null)"
cwd="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)"; [ -n "$cwd" ] || cwd="$PWD"
for dir in "$cwd/.claude/checkpoints" "$HOME/.claude/checkpoints"; do
  [ -d "$dir" ] || continue
  if [ -n "$DRYRUN" ]; then
    find "$dir" -maxdepth 1 -type f \( -name '*.md' -o -name '.*.at' \) -mtime "+$DAYS" -print
  else
    find "$dir" -maxdepth 1 -type f \( -name '*.md' -o -name '.*.at' \) -mtime "+$DAYS" -delete 2>/dev/null
  fi
done
exit 0
