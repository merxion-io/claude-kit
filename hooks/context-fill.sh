#!/usr/bin/env bash
# Prints "<tokens> <pct> <k>" — the current context window fill by the transcript.
# $1 = transcript path; if empty/missing — take the freshest .jsonl of the current project.
# $2 = "fast" → short tail (for statusline, rendered constantly); otherwise long.
#
# Measurements 2026-08-05, why it is this way:
#  · we read the TAIL by bytes, not `cat` whole — a transcript grows up to 160 MB, jq -s
#    on it took 19 s and gigabytes of RAM (the Stop hook silently dropped out by timeout);
#  · since 2026-07 the API puts the breakdown in usage.iterations[] and ZEROES the top level —
#    we count by the last iteration, otherwise we get 0;
#  · we take the last NON-zero value, not just the last: a zero entry
#    (stop_sequence / api_error) dropped the sensor to 0 and the hook exited with no output at all.
WINDOW=${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-1000000}
tp="${1:-}"; mode="${2:-}"
if [ -z "$tp" ] || [ ! -f "$tp" ]; then
  dir="$HOME/.claude/projects/$(printf '%s' "$PWD" | sed 's#[/.]#-#g')"
  tp="$(ls -t "$dir"/*.jsonl 2>/dev/null | head -1)"
fi
[ -f "$tp" ] || { echo "0 0 0"; exit 0; }
if [ "$mode" = fast ]; then bytes=400000; else bytes=8000000; fi
# We cut the truncated first line ONLY if the file is really larger than the read window,
# otherwise on a short transcript we would throw away the only valid line.
size=$(wc -c < "$tp" 2>/dev/null | tr -d ' '); size=${size:-0}  # wc, not stat -c: stat has different flags on macOS
if [ "$size" -gt "$bytes" ]; then src="$(tail -c "$bytes" "$tp" 2>/dev/null | tail -n +2)"
else src="$(cat "$tp" 2>/dev/null)"; fi
cur="$(printf '%s' "$src" | jq -s '
  def s: (.input_tokens//0)+(.cache_read_input_tokens//0)+(.cache_creation_input_tokens//0)+(.output_tokens//0);
  [ .[] | .message.usage | select(type=="object")
    | (s) as $top
    | (if (.iterations|type)=="array" and (.iterations|length)>0 then (.iterations|last|s) else 0 end) as $it
    | (if $top>0 then $top else $it end) ]
  | map(select(.>0)) | last // 0' 2>/dev/null)"
case "$cur" in ''|*[!0-9]*) cur=0;; esac
echo "$cur $(( cur*100/WINDOW )) $(( cur/1000 ))"
