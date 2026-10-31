#!/usr/bin/env bash
# Installs the agent kit into ~/.claude on a new machine: rules, skills, roles, hooks, tools.
# Run from a clone of the kit: ./install.sh   (a repeat run is safe — updates the kit files, does not touch foreign ones)
set -euo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${CLAUDE_HOME:-$HOME/.claude}"
mkdir -p "$TARGET"

# The kit is cloned right into ~/.claude — the files are already in place
if [ "$KIT" != "$(cd "$TARGET" && pwd)" ]; then
  for item in CLAUDE.md settings.base.json agents bin hooks tools skills roles; do
    [ -e "$KIT/$item" ] || continue
    if [ -d "$KIT/$item" ]; then mkdir -p "$TARGET/$item"; cp -R "$KIT/$item/." "$TARGET/$item/"; else cp "$KIT/$item" "$TARGET/$item"; fi
  done
fi

# Settings: if there are none, the base ones are taken; if there are, only missing keys and kit hooks are added, own values are not touched
python3 - "$KIT/settings.base.json" "$TARGET/settings.json" <<'PY'
import json, sys, os
base, path = json.load(open(sys.argv[1])), sys.argv[2]
mine = json.load(open(path)) if os.path.exists(path) else {}
added = [k for k in base if k not in mine]
for k in added: mine[k] = base[k]
# The kit's hooks: for each event, a command not yet running for the kit's matcher is appended with it; foreign hooks stay as they are, a malformed part too
def runs(have, command, matcher):
  entries = [e for e in have if isinstance(e, dict) and isinstance(e.get('hooks'), list)]
  return any(e.get('matcher') in (matcher, None, '', '*') and any(isinstance(h, dict) and h.get('command') == command for h in e['hooks']) for e in entries)
hooked, malformed = [], []
kit_hooks = base.get('hooks', {})
if not isinstance(mine['hooks'], dict):
  malformed, kit_hooks = ['hooks'], {}
for event, entries in kit_hooks.items():
  have = mine['hooks'].setdefault(event, [])
  if not isinstance(have, list):
    malformed.append(f'hooks.{event}')
    continue
  for entry in entries:
    missing = [h for h in entry['hooks'] if not runs(have, h['command'], entry.get('matcher'))]
    if missing:
      have.append({**entry, 'hooks': missing})
      hooked.append(event)
if added or hooked or not os.path.exists(path):
  with open(path, 'w') as f: json.dump(mine, f, ensure_ascii = False, indent = 2)
said = ([f'keys added: {", ".join(added)}'] if added else []) + ([f'hooks added: {", ".join(dict.fromkeys(hooked))}'] if hooked else [])
print('settings.json: ' + ('; '.join(said) or 'all keys and hooks already present, left untouched'))
if malformed: print(f'settings.json: {", ".join(malformed)} - wrong format, left untouched, kit hooks not added there: fix it and run again')
PY

chmod +x "$TARGET"/bin/* "$TARGET"/hooks/*.sh 2>/dev/null || true
# Only the scripts run directly (a shebang) get +x; an imported module (polyglot.py) keeps its mode, or the clone shows it modified
for tool in "$TARGET"/tools/quality/*.py; do
  if [ "$(head -c 2 "$tool" 2>/dev/null)" = '#!' ]; then chmod +x "$tool"; fi
done

# Kit commands (bin/) — as links into the personal PATH: a kit update picks them up at once
BIN="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN"
for cmd in "$TARGET"/bin/*; do if [ -f "$cmd" ] && [ -x "$cmd" ]; then ln -sfn "$cmd" "$BIN/$(basename "$cmd")"; fi; done
case ":$PATH:" in *":$BIN:"*) ;; *) echo "add $BIN to PATH - the kit commands (claude-role) are there";; esac
# Private-words guard: git hooks of the kit root (only when it is a git repo); a foreign hook is never overwritten
if [ -d "$TARGET/.git" ]; then
  for pair in commit-msg:'--message "$1"' pre-push:'--pre-push "$1"'; do
    name="${pair%%:*}"; args="${pair#*:}"; hook="$TARGET/.git/hooks/$name"
    if { [ -e "$hook" ] || [ -L "$hook" ]; } && ! grep -qs '^# claude-kit private-words guard' "$hook"; then
      echo "git hook $name: a foreign hook is there, left untouched - the private-words guard is not installed in it"
    else
      mkdir -p "$TARGET/.git/hooks"
      printf '#!/usr/bin/env bash\n# claude-kit private-words guard\nexec python3 "$(git rev-parse --show-toplevel)/tools/private_words.py" %s\n' "$args" > "$hook"
      chmod +x "$hook"
    fi
  done
  if hooks_path="$(git -C "$TARGET" config core.hooksPath)"; then
    echo "git core.hooksPath is $hooks_path: git does not run .git/hooks here - the private-words guard is not active"
  fi
fi
command -v git >/dev/null || echo 'git is required'
# macOS: for what is missing — the install command (Homebrew); installs nothing itself
if [ "$(uname -s)" = Darwin ]; then
  py_hint=' — brew install python'
  command -v tmux >/dev/null || echo 'tmux is required (roles live in its panes): brew install tmux'
  command -v jq >/dev/null || echo 'jq is required (kit hooks): brew install jq'
  command -v brew >/dev/null || echo 'brew is the macOS package manager: https://brew.sh'
fi
python3 -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null || echo "python3 >= 3.11 is required (tomllib for the ratchets)${py_hint:-}"
echo "done: kit installed in $TARGET. Check the machine: claude-role doctor. Quality checks, once: python3 $TARGET/tools/quality/gate.py setup. Next: README.md, section \"Installation\"."
