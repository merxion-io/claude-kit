#!/usr/bin/env bash
# SessionStart: brings up the observer daemon if it is not alive. So it heals itself
# on any session start — there is no systemd --user on this host, and keeping it started
# by hand is dishonest: it falls after a reboot and nobody notices.
pidf="$HOME/.claude/checkpoints/.watch/daemon.pid"
log="$HOME/.claude/checkpoints/.watch/daemon.log"
mkdir -p "$(dirname "$pidf")"
if [ -f "$pidf" ] && kill -0 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null; then exit 0; fi
export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH"
nohup python3 "$HOME/.claude/tools/session_watch.py" --detach >>"$log" 2>&1 &
echo $! > "$pidf"
exit 0
