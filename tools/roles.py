# Observer/executor roles: shared by the launcher bin/claude-role and the kit hooks — tmux panes, processes (Linux —
# /proc, macOS — ps), "a claude of this role is really running in the pane", the state label, the revive list and the revive.
# The list is state/roles.json in the kit root (or in $CLAUDE_ROLES_STATE_DIR), the only thing that survives a reboot:
# {observer: {observer: entry, executors: {executor: entry}}},
# entry = {session, pane, cwd, flags, project, conversation, transcript, since, closed, seen}; project — the pult project of the
# session; transcript — the conversation file (from SessionStart); since — when a live pane last
# confirmed it; closed — the session was closed normally (SessionEnd not from a kill); seen — the waiter already woke for its death
# without a pane.
import contextlib, fcntl, glob, json, os, re, shlex, shutil, subprocess, sys, time

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # kit root: tools/..
SILENCER = os.path.join(KIT, 'no-mobile-push')
STATE_DIR_VAR = 'CLAUDE_ROLES_STATE_DIR'  # own place of the list and locks — for probes; by default the kit's state/
STATE_DIR = os.environ.get(STATE_DIR_VAR) or os.path.join(KIT, 'state')
ROSTER = os.path.join(STATE_DIR, 'roles.json')
REVIVE_LOCK = os.path.join(STATE_DIR, 'revive.lock')
LAUNCHER = os.path.join(KIT, 'bin', 'claude-role')
PID_LABEL = '@claude_pid'  # PID of the role's claude in the pane — written by its hook
PANE_FIELDS = ('pane_id', 'session_name', 'pane_pid', 'pane_current_command', '@claude_role', '@claude_name',
               '@claude_observer', '@claude_state', '@claude_seen', '@claude_flags', PID_LABEL)
FLAGS = '@claude_flags'
REMOTE_CONTROL = ('--remote-control', '--rc')
NO_REMOTE_CONTROL = '--no-remote-control'  # the observer's opt-out of the default remote control (a kit flag)
PULT = 'pult'  # journal of operator sessions; the kit does not depend on it: no pult — nothing to hand over
PULT_SESSION = 28  # pult ls: session line — three spaces, name 24 wide, space, then the session id
SHELLS = ('bash', 'zsh', 'sh', 'dash', 'fish', 'ksh')
STARTUP_LIMIT = 30  # s — how long to wait for the started claude to come up

# Executor state label @claude_state: "<state> · <time> · <text>", one current
WORKING = 'working'
RUNNING = 'running a command'
ASKING = 'asking'
PERMISSION = 'waiting for permission'
BACKGROUND = 'waiting for its background'
TELLING = 'telling the observer'  # claude-role tell: a fact or a question without a choice — an action, not prose in an answer
STOPPED = 'stopped'
BROKEN = 'broke'
OPENED = 'open'  # session is open and waits for input — does not wake and is not "hung"
WAKES = (ASKING, PERMISSION, STOPPED, BROKEN, TELLING)  # states for which the waiter wakes the observer
SEEN = '@claude_seen'  # on the executor pane: the state label the waiter already woke the observer on
STATE = '@claude_state'
KILLED = 'other'  # reason in SessionEnd when claude is killed (kill-session, signal); /exit, Ctrl+C — prompt_input_exit
ROLE_NAMES = {'observer': 'observer', 'executor': 'executor'}
ROLE_PID = 'CLAUDE_ROLE_PID'  # PID of the claude started by claude-role: the launcher does exec, the PID is the same
ROLE_OBSERVER = 'CLAUDE_ROLE_OBSERVER'  # next — what the launcher passes to SessionStart: the executor's observer,
ROLE_FLAGS = 'CLAUDE_ROLE_FLAGS'  # launch flags (shlex) and the pult project
ROLE_PROJECT = 'CLAUDE_ROLE_PROJECT'
BUILDER = 'builder: '  # start of the "waiting for permission" text when the executor's builder asks
CHOSEN, NEXT = 'chosen: ', ' · next: '  # a window still open after a press: its "asking" text, written and read by claude-role
SEP = ' · '
TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
TEXT_LIMIT = 300
# claude-role tell: the full text goes to the observer in the wake line; above this the executor puts the long part in a
# file and tells its path — a bound without a model call, about a screen of the observer's context
TELL_LIMIT = 1500
TELL_AGE = 7 * 24 * 3600  # tell files nobody delivered (the pane closed first) live at most this long


def tmux(*args):
    return subprocess.run(['tmux', *args], check = True, capture_output = True, text = True).stdout


def panes():
    """All panes of the server, each once. A twin session (tmux new-session -t <session>) shows the same panes, and
    list-panes -a returns a pane once per session of the group; the pane's session is the original one: the one the
    group is named after (none such: the first found)."""
    fields = (*PANE_FIELDS, 'session_group')
    by_id = {}
    for line in tmux('list-panes', '-a', '-F', '\t'.join('#{%s}' % f for f in fields)).splitlines():
        p = dict(zip(fields, line.split('\t')))
        group = p.pop('session_group')
        if p['pane_id'] not in by_id or p['session_name'] == group:
            by_id[p['pane_id']] = p
    return list(by_id.values())


def find_pane(pane_id):
    return next((p for p in panes() if p['pane_id'] == pane_id), None)


def server_start():
    """When the tmux server started: entries confirmed earlier wait for the revive after a reboot."""
    return int(tmux('display-message', '-p', '#{start_time}').strip())


def pane_option(pane, name):
    return tmux('show-options', '-p', '-q', '-v', '-t', pane, name).rstrip('\n')


def set_pane_option(pane, name, value):
    tmux('set-option', '-p', '-t', pane, name, value)


def unset_pane_option(pane, name):
    tmux('set-option', '-p', '-u', '-t', pane, name)


def label_pane(pane, role, name, observer, flags):
    """Labels of a role pane: written by SessionStart of the claude that claude-role started."""
    set_pane_option(pane, '@claude_role', role)
    set_pane_option(pane, '@claude_name', name)
    set_pane_option(pane, FLAGS, shlex.join(flags))
    if observer:
        set_pane_option(pane, '@claude_observer', observer)
    else:
        unset_pane_option(pane, '@claude_observer')
    if role != 'executor':
        unset_pane_option(pane, STATE)  # the observer has no state label; for the executor the same hook writes it


def short(text):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT - 1] + '…'


def write_state(pane, kind, text, stamp = None):
    set_pane_option(pane, STATE, SEP.join((kind, stamp or time.strftime(TIME_FORMAT), short(text))))


def tell_path(pane, stamp):
    """File with the full tell text: by the pane and the label's timestamp."""
    return os.path.join(STATE_DIR, f'tell-{pane.lstrip("%")}-{re.sub(r"[^0-9]", "", stamp)}.txt')


def write_tell(pane, text):
    """The full text goes to a file (atomically), earlier files of this pane and old ones of others are removed; → the timestamp for the label."""
    stamp = time.strftime(TIME_FORMAT)
    path = tell_path(pane, stamp)
    mine = os.path.join(STATE_DIR, f'tell-{pane.lstrip("%")}-')
    os.makedirs(STATE_DIR, exist_ok = True)
    for old in glob.glob(os.path.join(STATE_DIR, 'tell-*.txt')):
        try:
            if old != path and (old.startswith(mine) or
                                time.time() - os.path.getmtime(old) > TELL_AGE):
                os.remove(old)
        except OSError:
            pass
    with open(path + '.tmp', 'w', encoding = 'utf-8') as f:
        f.write(text)
    os.replace(path + '.tmp', path)
    return stamp


def told(pane, label):
    """A "telling the observer" label → the full text from the tell file; no file → None (then the label's text)."""
    kind, stamp = fields(label)[:2]
    if kind != TELLING:
        return None
    try:
        with open(tell_path(pane, stamp), encoding = 'utf-8') as f:
            return f.read()
    except OSError:
        return None


def forget_tell(pane, label):
    """The waiter delivered the text: the file is no longer needed."""
    kind, stamp = fields(label)[:2]
    if kind == TELLING:
        try:
            os.remove(tell_path(pane, stamp))
        except OSError:
            pass


def fields(label):
    """A label → (state, timestamp as written, text)."""
    kind, stamp, text = (label.split(SEP, 2) + ['', ''])[:3]
    return kind, stamp, text


def parse_state(label):
    """A label → (state, epoch time, text); an empty label → (None, None, '')."""
    if not label:
        return None, None, ''
    kind, stamp, text = fields(label)
    return kind, time.mktime(time.strptime(stamp, TIME_FORMAT)), text


def _from_proc():
    """Linux: processes from /proc."""
    procs = {}
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            with open(f'/proc/{entry}/stat') as f:
                ppid = int(f.read().rsplit(')', 1)[1].split()[1])
            with open(f'/proc/{entry}/cmdline', 'rb') as f:
                argv = [a.decode(errors = 'replace') for a in f.read().split(b'\0') if a]
        except (OSError, IndexError, ValueError):
            continue
        procs[int(entry)] = (ppid, argv)
    return procs


def _from_ps():
    """macOS and others without /proc: ps in the standard format. Arguments split by spaces: only the first two are needed."""
    out = subprocess.run(['ps', '-ww', '-A', '-o', 'pid=,ppid=,command='], check = True, capture_output = True,
                         text = True, errors = 'replace').stdout
    procs = {}
    for line in out.splitlines():
        fields = line.split(None, 2)
        if len(fields) >= 2 and fields[0].isdigit() and fields[1].isdigit():
            procs[int(fields[0])] = (int(fields[1]), fields[2].split() if len(fields) > 2 else [])
    return procs


# Process layer: pid → (parent, argv). The environment of a foreign process is not needed: the role's claude is the PID in the pane label
processes = _from_proc if sys.platform.startswith('linux') else _from_ps


def is_claude(argv):
    return any(os.path.basename(a) == 'claude' for a in argv[:2])


def own_claude(procs = None):
    """PID of the nearest claude ancestor, the one that started this hook; none → None."""
    procs = processes() if procs is None else procs
    pid = os.getppid()
    while pid > 1 and pid in procs:
        if is_claude(procs[pid][1]):
            return pid
        pid = procs[pid][0]
    return None


def role_session():
    """The role this hook runs in, only if its claude is the one claude-role started. A nested claude
    (claude -p from a tool or a daemon with the executor's environment) → None: role hooks are silent in it."""
    role = os.environ.get('CLAUDE_ROLE')
    if role not in ROLE_NAMES or not os.environ.get('TMUX_PANE'):
        return None
    mark = os.environ.get(ROLE_PID)
    if mark is None:
        return role  # started before the PID label — the old behaviour until restart via claude-role
    return role if str(own_claude()) == mark else None


def role_pid():
    """PID of the role's claude of this hook, for the pane label @claude_pid (after role_session)."""
    return os.environ.get(ROLE_PID) or str(own_claude())


def descends(pid, root, procs):
    while pid > 1 and pid in procs:
        if pid == root:
            return True
        pid = procs[pid][0]
    return False


def live(pane, role, procs):
    """A claude of this role really runs in the pane; the role label alone proves nothing: the PID from @claude_pid is
    a live claude in the pane's process tree."""
    if pane['@claude_role'] != role:
        return False
    pid = pane[PID_LABEL]
    if pid.isdigit():
        return int(pid) in procs and is_claude(procs[int(pid)][1]) and descends(int(pid), int(pane['pane_pid']), procs)
    return _live_before_pid_label(pane, role, procs)


def _live_before_pid_label(pane, role, procs):
    """A session started before the @claude_pid label (the first hook writes it): by the environment of a claude in the
    pane's tree; a foreign process's environment is readable only from /proc (Linux), macOS has no such sessions."""
    for pid, (ppid, argv) in procs.items():
        if not is_claude(argv) or not descends(pid, int(pane['pane_pid']), procs):
            continue
        try:
            with open(f'/proc/{pid}/environ', 'rb') as f:
                env = f.read().split(b'\0')
        except OSError:
            continue
        mark = next((kv.split(b'=', 1)[1] for kv in env if kv.startswith(ROLE_PID.encode() + b'=')), None)
        if f'CLAUDE_ROLE={role}'.encode() in env and (mark is None or mark == str(pid).encode()):
            return True
    return False


def state_lock(pane):
    """Lock of the pane's state label: hooks of parallel events and claude-role tell."""
    return locked(os.path.join(STATE_DIR, f'state{pane}.lock'))


@contextlib.contextmanager
def locked(path):
    os.makedirs(os.path.dirname(path), exist_ok = True)
    with open(path, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read_roster():
    try:
        with open(ROSTER) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _still_there(entry, role, observer, name, by_pane, started):
    """An entry stays while its pane carries this role and name. One confirmed before the tmux server started waits for
    the revive after a reboot: nobody has panes then, and that is not a closing. No pane and the session was not closed
    normally: it died with the pane or session, the entry waits for the revive (claude-role revive)."""
    if entry.get('since', 0) < started:
        return True
    p = by_pane.get(entry.get('pane'))
    if not p:
        return not entry.get('closed')
    return p['@claude_role'] == role and p['@claude_name'] == name \
        and (role == 'observer' or p['@claude_observer'] == observer)


def update_roster(observer = None, role = None, name = None, fields = None):
    """Rewrites the whole list: closed entries go, fields are added to the entry (observer, role, name)."""
    with locked(ROSTER + '.lock'):
        roster = read_roster()
        started = server_start()
        by_pane = {p['pane_id']: p for p in panes()}
        if fields:
            team = roster.setdefault(observer, {})
            if role == 'observer':
                team['observer'] = {**team.get('observer', {}), **fields}
            else:
                executors = team.setdefault('executors', {})
                executors[name] = {**executors.get(name, {}), **fields}
        for obs in list(roster):
            team = roster[obs]
            if 'observer' in team and not _still_there(team['observer'], 'observer', obs, obs, by_pane, started):
                del team['observer']
            team['executors'] = {n: e for n, e in team.get('executors', {}).items()
                                 if _still_there(e, 'executor', obs, n, by_pane, started)}
            if not team['executors']:
                del team['executors']
            if not team:
                del roster[obs]
        tmp = ROSTER + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(roster, f, ensure_ascii = False, indent = 2)
        os.replace(tmp, ROSTER)


def resume_args(flags, conversation):
    """Launch flags without earlier -r/-c/--session-id and the prompt after "--", plus -r <conversation>."""
    out, i = [], 0
    while i < len(flags):
        f = flags[i]
        if f == '--':
            break
        if f in ('-c', '--continue') or f.startswith(('--resume=', '--session-id=')):
            i += 1
        elif f in ('-r', '--resume', '--session-id'):
            has_value = f == '--session-id' or i + 1 < len(flags) and not flags[i + 1].startswith('-')
            i += 2 if has_value else 1
        else:
            out.append(f)
            i += 1
    return out + (['-r', conversation] if conversation else [])


def resumable(entry):
    """The entry's conversation if there is something to resume, else None: the revive starts a new one with the same
    name and flags. Claude writes the conversation file only with the first message: dead before it, claude -r answers
    "No conversation found". The file path comes from SessionStart; for an entry without a path (before it) the
    conversation is taken as is."""
    path = entry.get('transcript')
    return None if path and not os.path.exists(path) else entry.get('conversation')


def has_remote_control(flags):
    return any(f in REMOTE_CONTROL or f.startswith(tuple(r + '=' for r in REMOTE_CONTROL)) for f in flags)


def sync_remote_control(pane, observer, role, name):
    """Remote control turned on mid-run (/remote-control): for the observer it goes into the flags (instead of the opt-out
    --no-remote-control) and survives a revive; for the executor it holds for this run only, the flags stay. The sign is
    CLAUDE_CODE_BRIDGE_SESSION_ID: Claude Code sets it for subprocesses while the connection is active."""
    if role != 'observer' or not os.environ.get('CLAUDE_CODE_BRIDGE_SESSION_ID'):
        return
    flags = shlex.split(pane_option(pane, FLAGS))
    if has_remote_control(flags):
        return
    flags = [f for f in flags if f != NO_REMOTE_CONTROL] + ['--remote-control', name]
    set_pane_option(pane, FLAGS, shlex.join(flags))
    update_roster(observer, role, name, {'flags': flags})


def idle_shell(pane):
    """Only a shell in the pane (no claude and nothing else running): it can be reused."""
    return pane['pane_current_command'].lstrip('-') in SHELLS  # "-zsh" — a login shell


def pult_journal():
    """pult ls → ({project: folder or None}, {session id: project}); no pult → None."""
    if not shutil.which(PULT):
        return None
    projects, sessions, project = {}, {}, None
    for line in subprocess.run([PULT, 'ls'], check = True, capture_output = True, text = True).stdout.splitlines():
        if not line.strip():
            continue
        if not line.startswith(' '):
            project, _, workdir = line.rpartition('  ')
            projects[project] = None if workdir == '~' else workdir  # without a folder pult takes home — not by folder
        elif project is not None and line[PULT_SESSION:].split():
            sessions[line[PULT_SESSION:].split()[0]] = project
    return projects, sessions


def pult_project(journal, session, cwd, chosen = None):
    """The pult project for a session → (project, None) or (None, why not chosen). A session already in the journal: its
    project; else chosen, and without it the project with the longest folder containing cwd; two such or none: not
    guessed."""
    projects, sessions = journal
    if session in sessions:
        return sessions[session], None
    if chosen is not None:
        return (chosen, None) if chosen in projects else (None, f'no project "{chosen}" in pult')
    path = os.path.realpath(cwd)
    fits = {name: os.path.realpath(wd) for name, wd in projects.items()
            if wd and (path + '/').startswith(os.path.realpath(wd).rstrip('/') + '/')}
    longest = max(map(len, fits.values()), default = 0)
    best = sorted(name for name, wd in fits.items() if len(wd) == longest)
    if len(best) == 1:
        return best[0], None
    why = f'folder {cwd} is in several pult projects: {", ".join(best)}' if best \
        else f'folder {cwd} is in no pult project'
    return None, f'{why}; choose with --project "<project>"'


def pult_adopt(session, project, name):
    """Hands a session to a pult project (pult adopt), only one not yet in the journal. → None or pult's answer."""
    out = subprocess.run([PULT, 'adopt', session, '--project', project, '--name', name], capture_output = True,
                         text = True)
    return None if out.returncode == 0 else (out.stdout + out.stderr).strip()


def relaunch(role, name, observer, entry, pane = None, prompt = None):
    """Starts claude-role of the role with the same conversation and flags: in pane (its shell is replaced) or, no pane,
    as a window in session entry['session'], and with no session as a new session. After claude exits a shell stays in the pane."""
    args = [LAUNCHER, role, name] + (['--to', observer] if role == 'executor' else []) \
        + (['--project', entry['project']] if entry.get('project') else []) \
        + resume_args(entry.get('flags', []), resumable(entry)) + (['--', prompt] if prompt else [])
    shell = os.environ.get('SHELL') or '/bin/sh'
    line = f'{shlex.join(args)}; exec {shlex.quote(shell)} -l'
    where = ['-c', entry.get('cwd') or os.path.expanduser('~'), '-e', f'PATH={os.environ["PATH"]}']
    if os.environ.get(STATE_DIR_VAR):  # tmux starts from its own environment — the list's place is passed explicitly
        where += ['-e', f'{STATE_DIR_VAR}={os.environ[STATE_DIR_VAR]}']
    if pane:
        tmux('respawn-pane', '-k', '-t', pane, *where, shell, '-c', line)
        return pane
    session = entry.get('session') or name
    has_session = subprocess.run(['tmux', 'has-session', '-t', f'={session}'], capture_output = True).returncode == 0
    if has_session:
        return tmux('new-window', '-P', '-F', '#{pane_id}', '-t', f'={session}:', *where, shell, '-c', line).strip()
    return tmux('new-session', '-d', '-P', '-F', '#{pane_id}', '-s', session, *where, shell, '-c', line).strip()


def wait_live(pane, role):
    deadline = time.time() + STARTUP_LIMIT
    while time.time() < deadline:
        p = find_pane(pane)
        if p and live(p, role, processes()):
            return True
        time.sleep(0.5)
    return False


def revive_observer(observer, caller):
    """An executor brings its crashed observer back up with the same conversation and flags: in the SAME pane, and with
    no pane (claude ran in a pane without a shell, the pane closed with it) as a window in its session or a new session.
    One closed normally is not brought up. A lock and a recheck under it: two executors at once do not start two.
    → what was done or None."""
    with locked(REVIVE_LOCK):
        p = next((p for p in panes() if p['@claude_role'] == 'observer' and p['@claude_name'] == observer), None)
        entry = read_roster().get(observer, {}).get('observer', {})
        if p and live(p, 'observer', processes()) or entry.get('closed') or not (p or entry):
            return None
        if p and not idle_shell(p):
            return f'{p["pane_current_command"]} runs in the observer pane, leaving it alone'
        if p:
            entry = {**entry, 'flags': shlex.split(p['@claude_flags'])}
        where = relaunch('observer', observer, None, entry, pane = p['pane_id'] if p else None,
                         prompt = f'You were brought back up after a crash (by executor "{caller}"): act by skill roles.')
        return 'revived' if wait_live(where, 'observer') else f'did not start in {STARTUP_LIMIT} s'
