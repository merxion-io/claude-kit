# One source of the kinds of work and the operations: the table of skills/orchestration/references/routing.md and the
# classifier of a tool call into an operation. Used by tools/task-kinds.py --ops and hooks/agent-guard.py — no second copy.
import os, re

TABLE = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                     'skills', 'orchestration', 'references', 'routing.md')


def kinds(path = None):
    """Rows of the table: {names, kind, model, effort, ceiling, series, steps}; names — the cell, its part before
    the brackets and the name in brackets (how task-kinds prints it), lower case."""
    rows, head = [], None
    for line in open(path or TABLE, encoding = 'utf-8'):
        if not line.startswith('|'):
            head = None if rows else head
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if head is None:
            head = [c.lower() for c in cells]
            continue
        if set(cells[0]) <= set('-: '):
            continue
        row = dict(zip(head, cells))
        name = row.get('kind', '')
        inner = re.search(r'\(([^()]*)\)\s*$', name)
        short = name[:inner.start()].strip() if inner else name
        row['names'] = {n.lower() for n in (name, short, inner and inner.group(1)) if n}
        row['steps'] = [s.strip() for s in row.get('steps', '').split('/') if s.strip() not in ('', '—', '-')]
        rows.append(row)
    return rows


def kind_row(name, rows):
    name = (name or '').strip().lower()
    return next((r for r in rows if name in r['names']), None)


def role_row(role, rows):
    """The row a call without a «Kind:» line is found by: the only row with this role (subagent_type)."""
    found = [r for r in rows if r.get('role', '—') not in ('', '—') and r['role'] == role]
    return found[0] if len(found) == 1 else None


def number(cell):
    m = re.match(r'\s*(\d+)', cell or '')
    return int(m.group(1)) if m else None


# A Bash line → the first word of each of its commands: only a command in command position counts, not a word
# in an argument, a pattern or a heredoc body; `ssh host 'cmd'` — the remote command
SEGMENT = re.compile(r'&&|\|\||[;|\n]|\$\(|`|\(')
PREFIX = re.compile(r'^\s*((sudo|time|nohup|exec|env|do|then|else|elif|if|while|until|!)\s+|timeout\s+\S+\s+|[A-Za-z_]\w*=("[^"]*"|\'[^\']*\'|\S*)\s+)+')


def first_words(command):
    command = re.sub(r'<<-?\s*[\'"]?(\w+)[\'"]?.*?(\n\1\s*(\n|$)|$)', ' ', command, flags = re.S)  # heredoc bodies
    command = re.sub(r'\bssh(\s+-\S+(\s+[^\s\'"-]\S*)?)*?\s+[^\s\'"-]\S*\s+([\'"])(.*?)\3', r'; \4', command, flags = re.S)  # remote command
    command = re.sub(r"'[^']*'", "''", command)  # quoted arguments and patterns are not commands,
    command = re.sub(r'"[^"$`]*"', '""', command)  # except "$(…)" substitutions
    words = set()
    for part in SEGMENT.split(command):
        part = PREFIX.sub('', part).split()
        word = part[0].rsplit('/', 1)[-1] if part else ''
        if re.match(r'python[\d.]*$', word) and part[1:2] == ['-m'] and len(part) > 2:
            word = part[2]  # python -m pytest — the module is the command
        if word == 'ssh':
            rest = [w for w in part[1:] if not w.startswith('-')]
            word = rest[1] if len(rest) > 1 else ''
        if word.strip('\'"'):
            words.add(word)
    return words


# Operations: first match by tool name, then by the first words of the Bash commands; order matters.
# Names of the operations that are rows of the table are the names in brackets there.
OPS = [
    ('board', lambda n, w, p: n.startswith('mcp__task-manager__')),
    ('watch background', lambda n, w, p: n in ('Monitor', 'TaskOutput', 'BashOutput', 'ScheduleWakeup', 'ReadNotifications', 'TaskStop')),
    ('agents', lambda n, w, p: n in ('Agent', 'Task', 'SendMessage', 'Workflow', 'ListAgents')),
    ('executors and panes', lambda n, w, p: w & {'tmux', 'claude-role', 'pult'}),
    ('git', lambda n, w, p: 'git' in w),
    ('build and test run', lambda n, w, p: w & {'pytest', 'vitest', 'jest', 'playwright', 'npm', 'npx', 'pnpm', 'yarn', 'make', 'go', 'cargo', 'tsc', 'ruff', 'mypy', 'eslint'}),
    ('containers', lambda n, w, p: w & {'docker', 'podman', 'docker-compose', 'podman-compose', 'kubectl', 'systemctl'}),
    ('watch background', lambda n, w, p: 'sleep' in w),
    ('remote', lambda n, w, p: w & {'ssh', 'scp', 'rsync', 'curl', 'wget'}),
    ('files and cleanup', lambda n, w, p: w & {'rm', 'mv', 'cp', 'mkdir', 'chmod', 'chown', 'ln', 'du', 'df', 'tar', 'unzip'}),
    ('config files', lambda n, w, p: n in ('Edit', 'Write') and re.search(r'\.(json|ya?ml|toml|env|ini)$|settings', p)),
    ('edit', lambda n, w, p: n in ('Edit', 'Write', 'NotebookEdit')),
    ('read and search', lambda n, w, p: n in ('Read', 'Grep', 'Glob') or w & {'cat', 'head', 'tail', 'sed', 'grep', 'rg', 'ls', 'find', 'wc'}),
    ('other shell', lambda n, w, p: n == 'Bash'),
]


def op_of(name, inp):
    words = first_words(inp.get('command') or '') if name == 'Bash' else set()
    for op, test in OPS:
        if test(name, words, inp.get('file_path') or ''):
            return op
    return 'other tools'
