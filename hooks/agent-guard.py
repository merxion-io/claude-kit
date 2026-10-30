#!/usr/bin/env python3
# Guard of the orchestration rules for claude-role sessions only. The one source is the table of kinds of work in
# skills/orchestration/references/routing.md (read by tools/routing.py): a row edited there changes the decision here.
# PreToolUse Agent/Task — a call that breaks a rule is denied with the reason, the model rewrites it itself;
# PreToolUse Bash of the observer — typing into an executor's pane with tmux send-keys/paste-buffer is denied: claude-role send
# checks the window and the box first, press answers a window. The target is told by its @claude_role, not by names.
# PostToolUse of the executor's main session (any tool) — an operation run longer than its Series gets a reminder.
# Measured 2026-10-29: as advice in a skill the rules did not hold (14 of 16 builders without a map,
# a rollout by one builder for 140 turns, containers by the main session for 170 turns).
import json, os, re, shlex, subprocess, sys

if os.environ.get('CLAUDE_ROLE') not in ('observer', 'executor'):
    sys.exit(0)  # bare claude: silent, before any import
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'tools'))
import roles, routing

FORBIDDEN_TYPES = ('general-purpose', 'claude', '')


def brief_files(prompt):
    """Texts of the brief files the prompt points to: a long brief goes as a file (orchestration §4)."""
    texts = []
    for path in re.findall(r'(/[^\s`\'"]+\.md)', prompt)[:3]:
        try:
            with open(os.path.expanduser(path), errors = 'ignore') as f:
                texts.append(f.read(200_000))
        except OSError:
            pass
    return texts


def field(text, name):
    """Values of the brief lines «<name>: …»."""
    return [m.group(1).strip() for m in re.finditer(rf'(?m)^\s*{name}\s*:\s*(.*)$', text)]


def head_kind(text):
    """The brief starts with «Kind: …»: the first non-empty line."""
    first = next((line for line in text.splitlines() if line.strip()), '')
    return field(first, 'Kind')[:1]


def agent_problem(inp, rows):
    kind = (inp.get('subagent_type') or '').strip()
    if kind == 'fork':
        return None  # a fork inherits the model and effort of the session
    if kind in FORBIDDEN_TYPES:
        return (f'subagent_type "{kind or "empty"}" forbidden: kit or project roles only '
                '(builder, scout, code-reviewer, verifier, spec-reviewer, spec-auditor) — orchestration §2.')
    missing = [k for k in ('model', 'effort') if not inp.get(k)]
    if missing:
        return f'no {" and ".join(missing)}: model and effort in every call (orchestration §2, references/routing.md).'
    prompt = inp.get('prompt') or ''
    files = brief_files(prompt)
    text = '\n'.join([prompt] + files)
    named = head_kind(prompt) or next((k for k in map(head_kind, files) if k), [])
    row = routing.kind_row(named[0], rows) if named else routing.role_row(kind, rows)
    if not row:
        names = ', '.join(sorted(min(r['names'], key = len) for r in rows))
        return (f'the brief starts with "Kind: <kind from references/routing.md>"'
                f'{f" — no kind \"{named[0]}\" in the table" if named else ""}; kinds: {names}.')
    differ = [f'{k} {inp[k]} instead of {row[k]}' for k in ('model', 'effort')
              if row.get(k) in ('haiku', 'sonnet', 'opus', 'fable', 'low', 'medium', 'high', 'xhigh', 'max')
              and inp[k].lower() != row[k]]
    if differ and not any(field(text, 'Why')):
        return f'"{row["kind"]}": {", ".join(differ)} per references/routing.md — follow it or add a "Why: …" line.'
    if row['steps']:
        steps = [s.lower() for s in field(text, 'Step')]
        if len(steps) != 1 or steps[0] not in row['steps']:
            return (f'"{row["kind"]}": one step per builder — exactly one "Step: {"|".join(row["steps"])}" line '
                    f'(found: {", ".join(steps) or "none"}) — references/routing.md.')
    if kind == 'builder' and not any(field(text, 'Map')):
        return ('builder without a map: scout first, then a "Map: <map file path or slice>" line '
                '(orchestration §3.1).')
    return None


TYPING = ('send-keys', 'send', 'paste-buffer', 'pasteb')
TMUX_VALUED = ('-L', '-S', '-f', '-c', '-T')  # tmux options before the command that take a value


def typing_targets(command):
    """tmux send-keys/paste-buffer in the Bash line → [(tmux server options, -t target or None)]."""
    try:
        lex = shlex.shlex(command, posix = True, punctuation_chars = True)
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        return []
    found, i = [], 0
    while i < len(words):
        head = i == 0 or set(words[i - 1]) <= set(';&|()')
        if not (head and os.path.basename(words[i]) == 'tmux'):
            i += 1
            continue
        j, server = i + 1, []
        while j < len(words) and words[j].startswith('-'):
            if words[j] in TMUX_VALUED and j + 1 < len(words):
                server += words[j:j + 2]
                j += 1
            j += 1
        if j < len(words) and words[j] in TYPING:
            target = None
            k = j + 1
            while k < len(words) and not set(words[k]) <= set(';&|()'):
                if words[k] == '-t' and k + 1 < len(words):
                    target = words[k + 1]
                elif words[k].startswith('-t') and len(words[k]) > 2:
                    target = words[k][2:]
                k += 1
            found.append((server, target))
        i = j + 1
    return found


def typing_problem(command):
    """Typing into a live executor's pane → the reason; the observer's own pane, others, a pane whose claude exited
    and unresolvable targets pass."""
    for server, target in typing_targets(command):
        if not target or '$' in target:
            continue
        r = subprocess.run(['tmux', *server, 'display-message', '-p', '-t', target,
                            '\t'.join('#{%s}' % f for f in roles.PANE_FIELDS)], capture_output = True, text = True)
        pane = dict(zip(roles.PANE_FIELDS, r.stdout.rstrip('\n').split('\t')))
        name = pane.get('@claude_name', '')
        # a claude that exited leaves its labels on a bare shell: typing the launch command there is fine
        if r.returncode == 0 and len(pane) == len(roles.PANE_FIELDS) and roles.live(pane, 'executor', roles.processes()):
            return (f'tmux typing into executor "{name}" ({target}) is denied: use claude-role send "{name}" "<text>" — it '
                    'refuses on an open window or foreign text in the box and presses Enter only while the text is there; '
                    f'a choice window: claude-role press "{name}" <digit|Escape>.')
    return None


def run_nudge(tool, ev, rows):
    """Series of one operation in a row of this session's tool calls: another operation ends it; past the row's
    Series — a reminder, then every Series + 1 turns."""
    op = routing.op_of(tool, ev.get('tool_input') or {})
    row = routing.kind_row(op, rows)
    series = routing.number(row.get('series')) if row else None
    path = os.path.join(roles.STATE_DIR, f'guard-{ev.get("session_id", "x")}.json')
    try:
        with open(path) as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = {}
    run = last.get('run', 0) + 1 if last.get('op') == op else 1
    os.makedirs(roles.STATE_DIR, exist_ok = True)
    with open(path, 'w') as f:
        json.dump({'op': op, 'run': run}, f)
    if series is None or run <= series or run % (series + 1):
        return None
    return (f'{run} turns of "{row["kind"]}" in a row in the main session (Series {series}): hand it to a short agent '
            f'(builder, model {row["model"]}, effort {row["effort"]}, "Kind: {row["kind"]}"), 5–10 line result; '
            'the decision stays yours (references/routing.md).')


def main():
    role = roles.role_session()
    if not role:
        return
    ev = json.load(sys.stdin)
    event, tool = ev.get('hook_event_name'), ev.get('tool_name')
    if event == 'PreToolUse' and tool in ('Agent', 'Task'):
        why = agent_problem(ev.get('tool_input') or {}, routing.kinds())
        if why:
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                     'permissionDecisionReason': why}}, ensure_ascii = False))
    elif event == 'PreToolUse' and tool == 'Bash' and role == 'observer':
        why = typing_problem((ev.get('tool_input') or {}).get('command') or '')
        if why:
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                     'permissionDecisionReason': why}}, ensure_ascii = False))
    elif event == 'PostToolUse' and role == 'executor' and not ev.get('agent_id'):
        note = run_nudge(tool or '', ev, routing.kinds())
        if note:
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': note}},
                             ensure_ascii = False))


if __name__ == '__main__':
    main()
