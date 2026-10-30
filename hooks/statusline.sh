#!/usr/bin/env bash
# Status bar: context fill against the auto-compact threshold, not the model window.
# From stdin (code.claude.com/docs/en/statusline): .context_window.total_input_tokens (input + cache
# write + cache read of the last response), .context_window_size, .used_percentage — without reading the
# transcript, to work the same in the terminal and in the VSCode extension.
# Threshold — CLAUDE_CODE_AUTO_COMPACT_WINDOW; unset — the window size: used_percentage is of the window,
# so at a 400k threshold it showed 14 % with compaction at 40 %.
input="$(cat)"
JQ="$(command -v jq || echo /usr/bin/jq)"

read -r tok size <<<"$("$JQ" -r '.context_window as $c | ($c.context_window_size // 1000000) as $w
  | (if ($c.total_input_tokens // 0) > 0 then $c.total_input_tokens else (($c.used_percentage // 0) * $w / 100) end) as $t
  | "\($t | floor) \($w | floor)"' 2>/dev/null <<<"$input")"
case "$tok" in ''|*[!0-9]*) tok=0;; esac
case "$size" in ''|*[!0-9]*) size=1000000;; esac
limit=${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-$size}
case "$limit" in ''|*[!0-9]*|0) limit=$size;; esac
pct=$(( tok*100/limit ))
model="$("$JQ" -r '.model.display_name // "Claude"' 2>/dev/null <<<"$input")"
[ -n "$model" ] || model="Claude"

esc=$'\033'; rst="${esc}[0m"; dim="${esc}[2m"
if   [ "$pct" -ge 85 ]; then c="${esc}[31m"
elif [ "$pct" -ge 70 ]; then c="${esc}[33m"
else                        c="${esc}[32m"; fi

fill=$(( pct/10 )); [ "$fill" -gt 10 ] && fill=10; [ "$fill" -lt 0 ] && fill=0
bar=""; i=0
while [ "$i" -lt 10 ]; do
  if [ "$i" -lt "$fill" ]; then bar="${bar}█"; else bar="${bar}░"; fi; i=$((i+1))
done

br="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
seg_br=""; [ -n "$br" ] && seg_br="${dim}⎇ ${br}${rst}  "

printf '%s%s  %s[%s] %dk/%dk · %d%%%s %scontext%s' \
  "$seg_br" "${dim}${model}${rst}" "$c" "$bar" $(( tok/1000 )) $(( limit/1000 )) "$pct" "$rst" "$dim" "$rst"
