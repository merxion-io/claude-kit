# An executor's main session does not change project files: a builder does. Held by hooks (hooks/role-state.py), in any
# project, with no configuration. The boundary is the git repository holding the TARGET path, not the session's cwd.
#  - layer 1, PreToolUse: a write into a repository (Edit/Write or what the Bash parser sees) is denied unless it is OPEN;
#  - layer 2, after Bash: what the parser cannot see (`python script.py`) shows in `git status` plus content hashes before
#    and after the call: the executor is told to restore it. Nothing is ever reverted. Skipped while a subagent runs.
# Subagents (payload agent_id) are never touched. A git failure here means open: the guard must not block work.
import contextlib, fnmatch, glob, hashlib, json, os, re, shlex, shutil, subprocess
from collections import namedtuple

import roles

OPEN = ('*.md', '.claude/checkpoints/')  # documents (tasks.md is *.md); folders at any depth; the project adds its own in the table, key "open"
PROJECT_GATES = os.path.join('.claude', 'kit-gates.json')
GIT_TIMEOUT = 5  # seconds per git call, then open
NON_GIT_ENV = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE')  # set inside git's own hooks: they would move the boundary
OPERATORS = re.compile(r'&>>|&>|>>|>\||>&|<<<|<<|<&|<>|<|>|&&|\|\||;;|[;&|()]')
WRITE_REDIRECTS = ('>', '>>', '>|', '&>', '&>>', '<>', '>&')
READ_REDIRECTS = ('<', '<<', '<<<', '<&')
SHLEX_PUNCTUATION = set('();<>|&')
MASK = str.maketrans({c: chr(0xE000 + i) for i, c in enumerate(sorted(SHLEX_PUNCTUATION | set('[]')))})  # '[' too: quoted text opens no [[ ]]
QUOTE_OPEN, QUOTE_CLOSE = '\uE100', '\uE101'  # around the body of quoted text while the line is lexed: it survives inside the word
UNMASK = {**{v: chr(k) for k, v in MASK.items()}, QUOTE_OPEN: '', QUOTE_CLOSE: ''}
QUOTED = re.compile(f'{QUOTE_OPEN}[^{QUOTE_CLOSE}]*(?:{QUOTE_CLOSE}|$)')
TEXT_OR_COMMENT = re.compile(r"""\\.|'[^']*'|"(?:[^"\\]|\\.)*"|(?:^|(?<=\s))#[^\n]*""", re.S | re.M)
_ONE_DEEP = r'(?:[^()]|\([^()]*\))*'  # deeper parens match nothing: read as shell, they hide no command
COMPARISON = re.compile(rf'\(\({_ONE_DEEP}\)\)|\[\[\s{_ONE_DEEP}?\s\]\]')  # (( x > 3 )), $(( 3 > 2 )), [[ a > b ]]: a '>' here redirects nothing
INNER_SUBSTITUTION = re.compile(r'\$\(([^()]*)\)')  # the $( ) of a comparison stays a command
HEREDOC = re.compile(r"""(?<!<)<<-?\s*['"]?(\w+)['"]?([^\n]*)\n(.*?)(?:^\t*\1[ \t]*$|\Z)""", re.S | re.M)
PREFIXES = ('sudo', 'env', 'time', 'do', 'then', 'else', 'elif', 'if', 'while', 'until', '{', '!', 'xargs', 'command',
            'nohup', 'exec')
ASSIGNMENT = re.compile(r'[A-Za-z_]\w*=.*')
IN_PLACE = {'sed': re.compile(r'-[a-zA-Z]*[iI]\S*|--in-place\S*'),  # BSD's -I edits in place too
            'perl': re.compile(r'-(?![IMm])[a-zA-Z0-9]*i\S*')}  # -0pi; perl's -I, -M, -m take the rest of the word: -Mstrict
SCRIPT_FLAG = re.compile(r'-[a-zA-Z]*e|--expression|-f|--file')
GIT_READ_ONLY_APPLY = ('--check', '--stat', '--numstat', '--summary')
PATCH_READ_ONLY = ('--dry-run', '--check', '-C')
NO_FILE_CHANGE = ('cd', 'echo', 'head', 'tail', 'grep', 'wc', 'true', 'cat', 'ls', 'pwd', 'cut', 'printf', 'sleep', 'date')  # may sit next to git in a «git command»
SUBSTITUTION = re.compile(r'(?:\$\(|`)([^()`]*)')  # the body of a $( ) or ` `, quoted or not
_TEXT = r"""[rbuf]*(?P<q>['"])(?P<path>[^'"\n{}]+)(?P=q)"""
_ANY_ARG = r"""[^,()]+,\s*"""
CODE_WRITES = [re.compile(p) for p in (  # the real target of a write call, not every quoted string of the code
    rf"""\bopen\(\s*{_TEXT}\s*,\s*(?:mode\s*=\s*)?[rbuf]*['"][^'"]*[wax+]""",
    rf"""\bPath\(\s*{_TEXT}\s*\)\s*\.(?:write_text|write_bytes)\(""",
    rf"""\bPath\(\s*{_TEXT}\s*\)\s*\.open\(\s*(?:mode\s*=\s*)?['"][^'"]*[wax+]""",
    rf"""\bshutil\.(?:copy\w*|move)\(\s*{_ANY_ARG}{_TEXT}""",
    rf"""\bos\.(?:replace|rename)\(\s*{_ANY_ARG}{_TEXT}""",
    rf"""\bfs['")]*\.(?:writeFile|appendFile)(?:Sync)?\(\s*{_TEXT}""",
    rf"""\bfs['")]*\.(?:copyFile|rename)(?:Sync)?\(\s*{_ANY_ARG}{_TEXT}""",
    rf"""\bFile\.write\(\s*{_TEXT}""",
)]

Segment = namedtuple('Segment', 'args outs bare')  # bare: args, word for word, with quoted text as ""
Target = namedtuple('Target', 'shown path whole_tree')  # path None: not known from the text; whole_tree: git apply, patch


def session_key(observer, name):
    return re.sub(r'[^\w.-]', '_', f'{observer}-{name}')


def split_shell(command):
    """Bash line → (commands: Segment, '(' or ')'; heredoc bodies)."""
    bodies = []

    def cut(m):
        bodies.append(m.group(3))
        return m.group(2) + ' ; '

    def mask(m):
        text = m.group()
        if text.startswith('#'):
            return ''
        if text[0] in '\'"' and len(text) > 2:
            text = f'{text[0]}{QUOTE_OPEN}{text[1:-1]}{QUOTE_CLOSE}{text[-1]}'
        return text.translate(MASK)
    shell = HEREDOC.sub(cut, command)

    def comparison(m):
        return ' true ' + ''.join(f' ; ({body})' for body in INNER_SUBSTITUTION.findall(m.group()))
    masked = COMPARISON.sub(comparison, TEXT_OR_COMMENT.sub(mask, shell.replace('\\\n', ' ')).replace('\n', ' ; '))
    try:
        lex = shlex.shlex(masked, posix = True, punctuation_chars = True)
        lex.whitespace_split, lex.commenters = True, ''
        words = list(lex)
    except ValueError:
        words = masked.split()
    def plain(word):
        return ''.join(UNMASK.get(c, c) for c in word)
    items, args, outs, bare, redirect = [], [], [], [], None
    for word in words + [';']:
        for part in OPERATORS.findall(word) if set(word) <= SHLEX_PUNCTUATION else [word]:
            if part in WRITE_REDIRECTS or part in READ_REDIRECTS:
                if args and args[-1].isdigit():
                    args.pop()  # the descriptor of 2> or 2>&1
                    bare.pop()
                redirect = part
            elif set(part) <= SHLEX_PUNCTUATION:
                items.append(Segment(args, outs, bare))
                args, outs, bare, redirect = [], [], [], None
                if part in '()':
                    items.append(part)
            else:
                text = plain(part)
                if redirect is None:
                    args.append(text)
                    bare.append(plain(QUOTED.sub('""', part)))
                elif redirect in WRITE_REDIRECTS and not (redirect == '>&' and re.fullmatch(r'\d+|-', text)):
                    outs.append(text)
                redirect = None
    return items, bodies


def command_words(args):
    """The words of a command without what only runs it: assignments, sudo, env, timeout 30, then…"""
    args = list(args)
    while args:
        if ASSIGNMENT.fullmatch(args[0]) or args[0] in PREFIXES:
            args = args[1:]
        elif args[0] == 'timeout':
            args = args[1:]
            while args and args[0].startswith('-'):
                args = args[1:]
            args = args[1:]  # the duration
        else:
            break
    return args


def at(here, word):
    """A shell word → absolute path; None if the text alone cannot tell (a variable, a substitution, an unknown cd)."""
    word = os.path.expandvars(os.path.expanduser(word))
    if '$' in word or '`' in word or not word:
        return None
    if not os.path.isabs(word) and here is None:
        return None
    return os.path.normpath(os.path.join(here or '', word))


def moved(here, args):
    """The directory after `cd args`, followed only while literal."""
    args = [a for a in args if a not in ('-L', '-P', '--')]
    if not args:
        return os.path.expanduser('~')
    return None if args[0] == '-' else at(here, args[0])


def non_options(args):
    return [a for a in args if not a.startswith('-')]


def dest_of_copy(head, args, here):
    """cp/mv/install/rsync: the destination; rsync's host:path is not local."""
    for i, a in enumerate(args):
        if a == '-t' and i + 1 < len(args):
            return [Target(args[i + 1], at(here, args[i + 1]), False)]
        if a.startswith('--target-directory='):
            dest = a.split('=', 1)[1]
            return [Target(dest, at(here, dest), False)]
    files = non_options(args)
    if not files or head == 'rsync' and re.match(r'[^/]*:', files[-1]):
        return []
    dest, sources = files[-1], files[:-1]
    place = at(here, dest)
    if place and sources and (dest.endswith('/') or os.path.isdir(place)):  # into a folder: each file lands under its own name
        return [Target(dest, at(here, os.path.join(dest, os.path.basename(s.rstrip('/')))) or place, False) for s in sources]
    return [Target(dest, place, False)]


def in_place_files(args):
    """sed -i / perl -i: the files, not the script (first free word unless -e or -f gave it), not BSD's -i ''."""
    files, scripted, skip = [], False, False
    for a in args:
        if skip:
            skip = False
        elif SCRIPT_FLAG.fullmatch(a):
            scripted = skip = True
        elif a and not a.startswith('-'):
            files.append(a)
    return files if scripted else files[1:]


def git_call(args, here):
    """git's words → those after its global options, and the directory its -C leaves."""
    rest = args[1:]
    while rest and rest[0].startswith('-'):
        if rest[0] == '-C' and len(rest) > 1:
            here = at(here, rest[1])
        rest = rest[2:] if rest[0] in ('-C', '-c') else rest[1:]
    return rest, here


def git_targets(args, here):
    """git itself stays open; only `git [-C dir] apply` writes."""
    rest, here = git_call(args, here)
    if rest[:1] == ['apply'] and not set(rest) & set(GIT_READ_ONLY_APPLY):
        return [Target('git apply', here, True)]
    return []


def patch_targets(args, here):
    """patch writes where -d points; a dry run writes nothing."""
    if set(args) & set(PATCH_READ_ONLY):
        return []
    for i, a in enumerate(args):
        if a in ('-d', '--directory') and i + 1 < len(args):
            here = at(here, args[i + 1])
        elif a.startswith('--directory='):
            here = at(here, a.split('=', 1)[1])
        elif a.startswith('-d'):
            here = at(here, a[2:])
    return [Target('patch', here, True)]


def code_targets(args, here, bodies):
    """python/node/ruby -c or -e, or a script on stdin: the targets of the write calls in the code."""
    flag = next((i for i, a in enumerate(args[:-1]) if a in ('-c', '-e')), None)
    if flag is not None:
        codes = [args[flag + 1]]
    elif non_options(args[1:]):
        codes = []  # a script file: layer 2 sees what it does
    else:
        codes = bodies
    found = (m.group('path') for code in codes for pattern in CODE_WRITES for m in pattern.finditer(code))
    return [Target(p, at(here, p), False) for p in found]


def segment_targets(args, here, bodies):
    """A command's words → what it writes. Everything not named here (ssh among them) writes nothing locally."""
    head = os.path.basename(args[0])
    if head == 'git':
        return git_targets(args, here)
    if head == 'patch':
        return patch_targets(args[1:], here)
    if head in ('cp', 'mv', 'install', 'rsync'):
        return dest_of_copy(head, args[1:], here)
    if head == 'tee':
        return [Target(a, at(here, a), False) for a in non_options(args[1:])]
    if head in IN_PLACE and any(IN_PLACE[head].fullmatch(a) for a in args[1:]):
        return [Target(a, at(here, a), False) for a in in_place_files(args[1:])]
    if re.fullmatch(r'python[\d.]*|node|ruby', head):
        return code_targets(args, here, bodies)
    if head in ('sh', 'bash', 'zsh'):
        flag = next((i for i, a in enumerate(args[:-1]) if re.fullmatch(r'-[a-z]*c', a)), None)
        return [] if flag is None else bash_targets(args[flag + 1], here)
    return []


def placed_segments(items, cwd):
    """The segments of a split line, each with the directory it starts in: a literal `cd` followed across segments and subshells."""
    here, outer, dirs = cwd, [], []
    for item in items:
        if item == '(':
            outer.append((here, list(dirs)))
        elif item == ')':
            here, dirs = outer.pop() if outer else (here, dirs)
        else:
            yield item, here
            args = command_words(item.args)
            if args[:1] == ['cd']:
                here = moved(here, args[1:])
            elif args[:1] == ['pushd']:
                dirs.append(here)
                here = moved(here, args[1:])
            elif args[:1] == ['popd']:
                here = dirs.pop() if dirs else here  # an empty stack: popd fails, the directory stays


def bash_targets(command, cwd):
    """All a Bash line writes, as far as the text tells."""
    items, bodies = split_shell(command)
    found = []
    for item, here in placed_segments(items, cwd):
        found += [Target(out, at(here, out), False) for out in item.outs]
        args = command_words(item.args)
        if args and args[0] not in ('cd', 'pushd', 'popd'):
            found += segment_targets(args, here, bodies)
    return found


def acting_commands(command, cwd):
    """A Bash line → (the directory each command acts in, its words without quoted text and git's global options).
    An unknowable directory is cwd."""
    for item, here in placed_segments(split_shell(command)[0], cwd):
        args, bare = command_words(item.args), item.bare
        if args and os.path.basename(args[0]) == 'git':
            rest, here = git_call(args, here)
            bare = bare[:len(item.args) - len(args) + 1] + bare[len(item.args) - len(rest):]
        if bare:
            yield here or cwd, ' '.join(bare)


def write_targets(ev):
    """What this tool call writes: Edit/Write/NotebookEdit/MultiEdit or Bash → list of Target."""
    tool, inp, cwd = ev.get('tool_name'), ev.get('tool_input') or {}, ev.get('cwd') or os.getcwd()
    if tool in ('Edit', 'Write', 'NotebookEdit', 'MultiEdit'):
        path = inp.get('file_path') or inp.get('notebook_path')
        return [Target(path, os.path.join(cwd, path), False)] if path else []
    if tool == 'Bash':
        return bash_targets(inp.get('command') or '', cwd)
    return []


def command_heads(command):
    """The names of the commands of a Bash line."""
    items = [i for i in split_shell(command)[0] if isinstance(i, Segment)]
    return [os.path.basename(words[0]) for words in map(lambda i: command_words(i.args), items) if words]


def is_git_command(command):
    """Only git, with `cd` and output filters beside it (`git merge x | tail`); `git add x && python s.py` is not."""
    heads = command_heads(command) + [h for body in SUBSTITUTION.findall(command) for h in command_heads(body)]
    return 'git' in heads and all(h == 'git' or h in NO_FILE_CHANGE for h in heads)


def git(cwd, *args):
    """git's stdout in bytes; any failure or timeout → None. GIT_OPTIONAL_LOCKS=0: a read takes no lock in a shared tree."""
    env = {k: v for k, v in os.environ.items() if k not in NON_GIT_ENV}
    try:
        done = subprocess.run(['git', '-C', cwd, *args], capture_output = True, timeout = GIT_TIMEOUT,
                              env = {**env, 'GIT_OPTIONAL_LOCKS': '0'})
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def repo_of(path):
    """The top of the git repository holding the path, resolved from its nearest existing parent; None outside any."""
    here = path
    while not os.path.isdir(here):
        if os.path.dirname(here) == here:
            return None
        here = os.path.dirname(here)
    top = git(here, 'rev-parse', '--show-toplevel')
    return os.path.realpath(os.fsdecode(top).rstrip('\n')) if top else None


def project_table_path(cwd):
    """The path of the project's table: <project>/.claude/kit-gates.json up from cwd; none → None."""
    here = os.path.abspath(cwd)
    while True:
        path = os.path.join(here, PROJECT_GATES)
        if os.path.exists(path):
            return path
        if os.path.dirname(here) == here:
            return None
        here = os.path.dirname(here)


def project_table(cwd):
    """The project's table up from cwd; none or broken → {}."""
    path = project_table_path(cwd)
    if not path:
        return {}
    try:
        with open(path, encoding = 'utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def open_entries(top):
    """The default open list and the table's "open" strings; a broken table adds nothing."""
    table = project_table(top)
    extra = table.get('open') if isinstance(table, dict) else None
    return OPEN + (tuple(extra) if isinstance(extra, list) and all(isinstance(e, str) for e in extra) else ())


def is_open(rel, top):
    """A path relative to its repository is on the open list."""
    for entry in open_entries(top):
        if entry.endswith('/'):
            if f'/{entry}' in f'/{rel}/':
                return True
        elif fnmatch.fnmatch(os.path.basename(rel), entry):
            return True
    return False


def closed(target):
    """The target lies inside a repository and off the open list."""
    if target.path is None or target.path.startswith('/dev/'):
        return False
    real = os.path.realpath(target.path)
    top = repo_of(real)
    return bool(top) and not is_open(os.path.relpath(real, top), top)


def deny_reason(shown):
    return (f'{shown}: a builder writes this — you are the main session of an executor, changing files inside a git '
            'repository yourself is denied (hand it over: Kind, Map, Step). Load `orchestration` (Skill tool) if it is '
            'not loaded. Open: paths outside a repository, *.md, .claude/checkpoints/, the project\'s "open" paths, git itself, ssh.')


def status_files(top):
    """Files `git status` calls changed → {path: content hash}; git failed → None."""
    out = git(top, 'status', '--porcelain', '-z', '-uall')
    if out is None:
        return None
    words = os.fsdecode(out).split('\0')
    return {path: content_hash(top, path) for path in status_paths(words)}


def status_paths(words):
    """-z output: `XY path`, a rename or copy adds its source as the next word."""
    paths, i = [], 0
    while i < len(words) and words[i]:
        paths.append(words[i][3:])
        if words[i][0] in 'RC' or words[i][1] in 'RC':
            i += 1
            paths.append(words[i])
        i += 1
    return paths


def content_hash(top, path):
    digest = hashlib.sha1()
    try:
        with open(os.path.join(top, path), 'rb') as f:
            while chunk := f.read(1 << 20):
                digest.update(chunk)
    except OSError:
        return None  # deleted, or a directory (a nested repository)
    return digest.hexdigest()


def changed_files(top, before):
    """Non-open files whose content moved since the snapshot; git failed → nothing."""
    after = status_files(top)
    if after is None:
        return []
    moved_files = [p for p in after if p not in before or before[p] != after[p]]
    moved_files += [p for p in before if p not in after and before[p] != content_hash(top, p)]
    return sorted(p for p in moved_files if not is_open(p, top))


def guard_dir(observer, name):
    return os.path.join(roles.STATE_DIR, f'write-guard-{session_key(observer, name)}')


def snapshot_path(place, tool_id):
    return os.path.join(place, f'before-{re.sub(r"[^\w.-]", "_", tool_id)}.json')


def drop_snapshots(place):
    for path in glob.glob(os.path.join(glob.escape(place), 'before-*.json')):
        with contextlib.suppress(OSError):
            os.remove(path)


def forget_subagents(place):
    shutil.rmtree(os.path.join(place, 'running'), ignore_errors = True)


def subagent_running(place):
    with contextlib.suppress(OSError):
        return bool(os.listdir(os.path.join(place, 'running')))
    return False


def note_subagent(ev, place):
    """Any event of a subagent marks it running, SubagentStop unmarks it (one file per agent: hooks run in parallel).
    Every such event also drops the snapshots in flight: a change during them may be the subagent's."""
    drop_snapshots(place)
    mark = os.path.join(place, 'running', re.sub(r'[^\w.-]', '_', str(ev['agent_id'])))
    with contextlib.suppress(OSError):
        if ev['hook_event_name'] == 'SubagentStop':
            os.remove(mark)
        else:
            os.makedirs(os.path.dirname(mark), exist_ok = True)
            open(mark, 'w').close()


def remember_before(ev, place):
    """PreToolUse of Bash: the snapshot of the session's repository under tool_use_id (calls run in parallel). Not taken
    for a git command, a background command (its end is not this call's end), a running subagent or outside a repo."""
    inp, tool_id = ev.get('tool_input') or {}, ev.get('tool_use_id')
    if not tool_id or inp.get('run_in_background') or subagent_running(place) or is_git_command(inp.get('command') or ''):
        return
    top = repo_of(os.path.realpath(ev.get('cwd') or os.getcwd()))
    files = status_files(top) if top else None
    if files is None:
        return
    with contextlib.suppress(OSError):
        os.makedirs(place, exist_ok = True)
        with open(snapshot_path(place, tool_id), 'w') as f:
            json.dump({'top': top, 'files': files}, f)


def report_after(ev, place):
    """After Bash, succeeded or failed: the snapshot is dropped either way; changes → the feedback text, else None."""
    if not ev.get('tool_use_id'):
        return None
    path = snapshot_path(place, ev['tool_use_id'])
    try:
        with open(path) as f:
            before = json.load(f)
        os.remove(path)
    except (OSError, ValueError):
        return None
    if subagent_running(place):
        return None
    changed = changed_files(before['top'], before['files'])
    if not changed:
        return None
    return (f'This Bash command changed files in the repository {before["top"]}: {", ".join(changed)}. You are the main '
            'session of an executor: restore that change and hand it to a builder. The guard reverted nothing. '
            'If another session shares this tree, the change may be its: check before restoring.')


def hold(ev, observer, name):
    """The hooks of an executor's main session → hookSpecificOutput dict or None."""
    event, place = ev['hook_event_name'], guard_dir(observer, name)
    if ev.get('agent_id'):
        note_subagent(ev, place)  # a builder or scout of this executor: never touched
        return None
    if event in ('SessionStart', 'SessionEnd', 'Stop'):
        drop_snapshots(place)  # no call is in flight; a denied call leaves its snapshot behind
        if event == 'Stop':
            alive = any(t.get('type') != 'shell' for t in ev.get('background_tasks') or [])
        else:
            alive = ev.get('source') == 'compact'
        if not alive:
            forget_subagents(place)
        return None
    if event == 'PreToolUse':
        hit = next((t for t in write_targets(ev) if closed(t)), None)
        if hit:
            return {'hookEventName': event, 'permissionDecision': 'deny', 'permissionDecisionReason': deny_reason(hit.shown)}
        if ev.get('tool_name') == 'Bash':
            remember_before(ev, place)
    elif event in ('PostToolUse', 'PostToolUseFailure') and ev.get('tool_name') == 'Bash':
        said = report_after(ev, place)
        return said and {'hookEventName': event, 'additionalContext': said}
    return None
