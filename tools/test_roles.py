#!/usr/bin/env python3
# Waiter scan, screen footer rule, close and revive of closed entries: python3 tools/test_roles.py. The real waiter scan (hooks/observer-wait.py attention)
# reads the state labels; screen.dialog reads a captured pane.
import contextlib, importlib.machinery, importlib.util, io, itertools, json, os, re, shutil, signal, subprocess, sys, tempfile, time, types, unittest
from unittest import mock

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(KIT, 'tools'))
sys.dont_write_bytecode = True
os.environ['CLAUDE_ROLES_STATE_DIR'] = tempfile.mkdtemp()
import roles
import screen


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, os.path.join(KIT, path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(module)
    return module


waiter = load('observer_wait', 'hooks/observer-wait.py')
launcher = load('claude_role', 'bin/claude-role')
PROCS = {100: (90, ['claude']), 90: (1, ['zsh'])}
STAMP = '2026-10-30 12:00:00'


def label(kind, text = 'x', stamp = STAMP):
    return roles.SEP.join((kind, stamp, text))


def executor_pane(state, seen = ''):
    return {'pane_id': '%7', 'session_name': 's', 'pane_pid': '90', 'pane_current_command': 'claude',
            '@claude_role': 'executor', '@claude_name': 'e', '@claude_observer': 'me', '@claude_state': state,
            '@claude_seen': seen, '@claude_flags': '', roles.PID_LABEL: '100'}


def scan(state, seen = '', now = None):
    """The real scan over one live executor pane → the (pane, name, key, line) it wakes the observer on."""
    return waiter.attention('me', [executor_pane(state, seen)], PROCS, now or time.mktime(time.strptime(STAMP, roles.TIME_FORMAT)) + 1, {}, 0)


class NewLabels(unittest.TestCase):
    def test_new_stopped_label_wakes_and_seen_does_not(self):
        new = label(roles.STOPPED)
        self.assertEqual(len(scan(new)), 1)
        self.assertEqual(scan(new, seen = new), [])

    def test_working_label_does_not_wake(self):
        self.assertEqual(scan(label(roles.WORKING)), [])


class Footer(unittest.TestCase):
    def pane(self, line):
        return '\n'.join(('some output', line)) + '\n'

    def test_real_footers_are_dialogs(self):
        for line in ('Enter to confirm · Esc to cancel', 'Esc to cancel · Tab to amend · ctrl+e to explain',
                     'Do you want to proceed? (y/n)', '  \u2191/\u2193 to navigate \u00b7 Enter to select \u00b7 Esc to go back'):
            self.assertIsNotNone(screen.dialog(self.pane(line)), line)

    def test_prose_quoting_a_footer_is_not_a_dialog(self):
        for line in ('Pour annuler, appuyez sur esc to cancel (r\u00e9ponse)',  # Latin script, non-ASCII letters
                     'esc to cancel \u03c0\u03b1\u03c1\u03b1\u03ba\u03b1\u03bb\u03ce',  # Greek
                     'esc to cancel \u65e5\u672c\u8a9e'):  # CJK
            self.assertIsNone(screen.dialog(self.pane(line)), line)


def captured(*lines):
    raw = '\n'.join(lines) + '\n'
    return types.SimpleNamespace(raw = raw, plain = raw)


BOX = ('\u2500' * 20, '\u276f ', '\u2500' * 20)
WINDOW = ('Do you want to proceed?', '\u276f 1. Yes', '  2. No')


class CloseRefusal(unittest.TestCase):
    def reason(self, state = '', session = None, screen = None, force = False):
        return launcher.close_refusal({'@claude_state': state}, session, screen or captured(*BOX), force)

    def test_idle_executor_closes(self):
        self.assertIsNone(self.reason(label(roles.STOPPED), {'status': 'idle'}))
        self.assertIsNone(self.reason(label(roles.OPENED)))

    def test_window_refuses_even_with_force(self):
        for force in (False, True):
            why = self.reason(screen = captured(*WINDOW), force = force)
            self.assertIn('press or press Escape', why)
            self.assertNotIn('--force', why)

    def test_each_working_or_asking_state_refuses_without_force_only(self):
        for kind in (roles.WORKING, roles.RUNNING, roles.BACKGROUND, roles.STOPPED_BACKGROUND, roles.ASKING, roles.PERMISSION,
                     roles.TELLING):
            self.assertIn(kind, self.reason(label(kind)))
            self.assertIn('--force', self.reason(label(kind)))
            self.assertIsNone(self.reason(label(kind), force = True), kind)

    def test_busy_session_refuses_without_force_only(self):
        self.assertIn('busy', self.reason(label(roles.STOPPED), {'status': 'busy'}))
        self.assertIsNone(self.reason(label(roles.STOPPED), {'status': 'busy'}, force = True))

    def test_screen_that_takes_no_message_refuses_without_force_only(self):
        for lines, word in ((('Enter to confirm \u00b7 Esc to cancel',), 'dialog'), (('plain text',), 'no input box'),
                            ((BOX[0], '\u276f someone typed', BOX[2]), 'not ours')):
            self.assertIn(word, self.reason(screen = captured(*lines)))
            self.assertIsNone(self.reason(screen = captured(*lines), force = True), word)


class ClosedEntries(unittest.TestCase):
    def test_waiter_gives_nothing_for_a_closed_entry_with_no_pane(self):
        entry = {'pane': '%9', 'session': 's', 'since': 10, 'closed': True}
        self.assertEqual(waiter.attention('me', [], {}, time.time(), {'e': entry}, 0), [])
        self.assertEqual(len(waiter.attention('me', [], {}, time.time(), {'e': {**entry, 'closed': False}}, 0)), 1)

    def test_revive_skips_a_closed_entry_and_brings_up_an_open_one(self):
        with open(roles.ROSTER, 'w') as f:
            json.dump({'me': {'executors': {'done': {'session': 'a', 'closed': True}, 'gone': {'session': 'b'}}}}, f)
        self.addCleanup(os.remove, roles.ROSTER)
        with mock.patch.dict(os.environ, {'CLAUDE_ROLE': 'observer', 'CLAUDE_ROLE_NAME': 'me'}), \
                mock.patch.object(launcher, 'panes', return_value = []), \
                mock.patch.object(launcher, 'processes', return_value = {}), \
                mock.patch.object(roles, 'pult_journal', return_value = None), \
                mock.patch.object(roles, 'wait_live', return_value = True), \
                mock.patch.object(roles, 'relaunch', return_value = '%1') as relaunch, \
                mock.patch('builtins.print'):
            launcher.revive([])
        self.assertEqual([call.args[1] for call in relaunch.call_args_list], ['gone'])


# close end to end: the real launcher and role-state hook, a fake claude with an input box, a private tmux server.
# claude-role in-process with its race forced for real: the signal comes only after claude is gone (late-signal), the
# session goes just before the n-th tmux call on it (vanish n).
RACE = """
import importlib.machinery, importlib.util, os, signal, sys, time
kit, race, argv = sys.argv[1], sys.argv[2], sys.argv[3:]
loader = importlib.machinery.SourceFileLoader('claude_role', f'{kit}/bin/claude-role')
launcher = importlib.util.module_from_spec(importlib.util.spec_from_loader('claude_role', loader))
loader.exec_module(launcher)
roles = launcher.roles
if race == 'late-signal':
    kill = os.kill
    def late(pid, sign):
        if sign == signal.SIGTERM:
            kill(pid, signal.SIGKILL)
            while launcher.processes().get(pid):
                time.sleep(0.05)
        kill(pid, sign)
    os.kill = late
else:
    tmux, left = roles.tmux, int(race)
    def vanishing(*args):
        global left
        if args[0] in ('set-option', 'kill-session') or args[:2] == ('list-panes', '-s'):
            left -= 1
            if left == 0:
                tmux('kill-session', '-t', '=e')
        return tmux(*args)
    roles.tmux = vanishing
launcher.main(argv)
"""

FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, shutil, signal, subprocess, sys, tty
def terminated(*_):
    state = os.environ['CLAUDE_ROLES_STATE_DIR']
    shutil.copy(f'{state}/roles.json', f'{state}/at-term.json')
    sys.exit(1)
signal.signal(signal.SIGTERM, terminated)
def hook(event, **fields):
    subprocess.run([sys.executable, os.environ['LAB_HOOK']], capture_output = True, text = True, input = json.dumps(
        {'hook_event_name': event, 'session_id': f'c{os.getpid()}', 'cwd': os.getcwd(), **fields}))
hook('SessionStart', source = 'startup')
if os.environ.get('LAB_KIDS'):
    subprocess.Popen(['bash', '-c', os.environ['LAB_KIDS']], stdin = subprocess.DEVNULL, stdout = subprocess.DEVNULL)
tty.setraw(0)
text = ''
while True:
    sys.stdout.write('\\x1b[2J\\x1b[H' + '\\u2500' * 30 + '\\r\\n\\u276f ' + text + '\\r\\n' + '\\u2500' * 30 + '\\r\\n')
    sys.stdout.flush()
    for c in os.read(0, 1024).decode():
        if c in '\\r\\n':
            if text == '/exit':
                hook('SessionEnd', reason = 'prompt_input_exit')
                if os.environ.get('LAB_END'):  # a shell hook of SessionEnd, run as claude runs hooks: its environment
                    subprocess.run(['bash', os.environ['LAB_END']], input = '{}', text = True, capture_output = True,
                                   env = {**os.environ, 'HOME': os.environ['LAB_HOME']})
                sys.exit(0)
            text = ''
        else:
            text += c
"""


@unittest.skipUnless(shutil.which('tmux'), 'no tmux')
class CloseLive(unittest.TestCase):
    def setUp(self):
        root = tempfile.mkdtemp(dir = '/tmp', prefix = 'cr')
        self.addCleanup(shutil.rmtree, root, True)
        bin_dir, self.state, self.at_kill = f'{root}/bin', f'{root}/state', f'{root}/at-kill.json'
        os.makedirs(bin_dir)
        os.makedirs(self.state)
        tmux = shutil.which('tmux')
        for name, body in (('claude', FAKE_CLAUDE), ('tmux.conf', 'set -g default-command "bash --norc --noprofile"\n'), ('tmux', (
                f'#!/bin/bash\ncase " $* " in *" kill-session "*) cp {self.state}/roles.json {self.at_kill};; esac\n'
                f'exec "{tmux}" -S {root}/s -f {bin_dir}/tmux.conf "$@"\n'))):
            with open(f'{bin_dir}/{name}', 'w') as f:
                f.write(body)
            os.chmod(f'{bin_dir}/{name}', 0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('TMUX', 'CLAUDE_'))}
        # The python running the tests goes first: /usr/bin/python3 on macOS is 3.9, below the kit's 3.11
        self.env = {**env, 'PATH': f'{bin_dir}:{os.path.dirname(sys.executable)}:/usr/bin:/bin','SHELL': '/bin/bash', 'CLAUDE_ROLES_STATE_DIR': self.state,
                    'XDG_STATE_HOME': f'{root}/xdg', 'CLAUDE_CONFIG_DIR': f'{root}/cfg',
                    'LAB_HOOK': os.path.join(KIT, 'hooks/role-state.py')}
        self.observer = {**self.env, 'CLAUDE_ROLE': 'observer', 'CLAUDE_ROLE_NAME': 'obs', 'TMUX': f'{root}/s,0,0'}
        self.tmux('new-session', '-d', '-s', 'boot')
        self.addCleanup(self.tmux, 'kill-server')
        self.start('obs', 'observer obs --no-remote-control')

    def tmux(self, *args):
        return subprocess.run(['tmux', *args], env = self.env, capture_output = True, text = True).stdout

    def role(self, *args):
        out = subprocess.run([sys.executable, os.path.join(KIT, 'bin/claude-role'), *args], env = self.observer,
                             capture_output = True, text = True)
        return out.returncode, out.stdout + out.stderr

    def panes(self):
        rows = self.tmux('list-panes', '-a', '-F', '#{session_name}\t#{@claude_name}\t#{@claude_pid}').splitlines()
        return [row.split('\t') for row in rows]

    def team(self, observer = 'obs'):
        with open(f'{self.state}/roles.json') as f:
            return json.load(f).get(observer, {}).get('executors', {})

    def start(self, session, role):
        """claude-role <role> in the shell of a new session, up to its input box."""
        self.tmux('new-session', '-d', '-s', session)
        self.tmux('send-keys', '-t', f'={session}:', f'python3 {KIT}/bin/claude-role {role}', 'Enter')
        deadline = time.time() + 15
        while time.time() < deadline:
            if any(s == session and pid for s, _, pid in self.panes()) \
                    and '\u276f' in self.tmux('capture-pane', '-p', '-t', f'={session}:'):
                return
            time.sleep(0.1)
        self.fail(f'{session} did not come up: {self.panes()}')

    def test_brief_prints_the_one_path_refuses_bad_names_and_sweeps_only_stale_files(self):
        self.start('e', 'executor e --to obs')
        code, out = self.role('brief', 'e')
        path = f'{self.state}/briefs/obs/e.md'
        self.assertEqual((code, out.strip()), (0, path), out)
        self.assertTrue(os.path.isdir(os.path.dirname(path)))
        for bad in ('a/b', '.hidden', '../x', ' '):
            code, out = self.role('brief', bad)
            self.assertEqual(code, 1, (bad, out))
        mine = {name: f'{self.state}/briefs/obs/{name}.md' for name in ('e', 'gone', 'next')}
        other = f'{self.state}/briefs/other/gone.md'
        os.makedirs(os.path.dirname(other))
        for file in (*mine.values(), other):
            with open(file, 'w') as f:
                f.write('task')
        os.utime(mine['gone'], (1, 1))
        os.utime(other, (1, 1))
        self.assertEqual(self.role('brief', 'next')[0], 0)
        self.assertEqual({n: os.path.exists(f) for n, f in mine.items()}, {'e': True, 'gone': False, 'next': True})
        self.assertTrue(os.path.exists(other))

    def test_brief_keeps_the_fresh_file_of_a_name_not_launched_yet(self):
        code, out = self.role('brief', 'first')
        with open(out.strip(), 'w') as f:
            f.write('task')
        self.assertEqual(self.role('brief', 'second')[0], 0)
        self.assertTrue(os.path.exists(out.strip()))

    def test_brief_refuses_an_observer_name_that_leaves_the_briefs_folder(self):
        precious = f'{self.state}/precious.md'
        with open(precious, 'w') as f:
            f.write('keep')
        out = subprocess.run([sys.executable, os.path.join(KIT, 'bin/claude-role'), 'brief', 'e'],
                             env = {**self.observer, 'CLAUDE_ROLE_NAME': '..'}, capture_output = True, text = True)
        self.assertEqual((out.returncode, os.path.exists(precious)), (1, True), out.stdout + out.stderr)

    def test_brief_is_for_an_observer_only(self):
        out = subprocess.run([sys.executable, os.path.join(KIT, 'bin/claude-role'), 'brief', 'e'], env = self.env,
                             capture_output = True, text = True)
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)

    def test_close_deletes_the_brief_on_both_paths_and_a_missing_file_is_fine(self):
        self.start('e', 'executor e --to obs')
        path = self.role('brief', 'e')[1].strip()
        with open(path, 'w') as f:
            f.write('task')
        self.assertEqual(self.role('close', 'e')[0], 0)
        self.assertFalse(os.path.exists(path))

    def test_close_of_an_entry_with_no_pane_deletes_the_brief_too(self):
        self.start('e', 'executor e --to obs')
        path = self.role('brief', 'e')[1].strip()
        with open(path, 'w') as f:
            f.write('task')
        self.tmux('kill-session', '-t', '=e')
        code, out = self.role('close', 'e')
        self.assertEqual((code, 'no pane' in out, os.path.exists(path)), (0, True, False), out)

    def test_normal_close_marks_closed_before_the_session_goes_and_leaves_nothing(self):
        self.start('e', 'executor e --to obs')
        code, out = self.role('close', 'e')
        self.assertEqual((code, 'session e removed' in out), (0, True), out)
        with open(self.at_kill) as f:
            self.assertTrue(json.load(f)['obs']['executors']['e']['closed'])
        self.assertNotIn('e', [s for s, *_ in self.panes()])
        self.assertEqual(self.team(), {})

    def test_a_view_of_the_session_goes_with_it(self):
        self.start('e', 'executor e --to obs')
        self.tmux('new-session', '-d', '-t', 'e', '-s', 'e~1')
        code, out = self.role('close', 'e')
        self.assertEqual(code, 0, out)
        self.assertEqual([s for s, name, _ in self.panes() if s.startswith('e') or name == 'e'], [])
        self.assertEqual(self.team(), {})

    def test_of_two_with_one_name_the_live_one_is_closed_then_the_stale_one_leaving_no_entry(self):
        self.start('a', 'executor e --to obs')
        os.kill(int(next(pid for s, _, pid in self.panes() if s == 'a')), signal.SIGKILL)
        time.sleep(0.3)
        self.start('e', 'executor e --to obs')
        code, out = self.role('close', 'e')
        self.assertEqual(code, 0, out)
        self.assertEqual([s for s, name, _ in self.panes() if name == 'e'], ['a'])
        self.assertEqual(self.team(), {})
        self.role('close', 'e')
        self.assertEqual([s for s, name, _ in self.panes() if name == 'e'], [])
        self.assertEqual(self.team(), {})

    def test_a_dead_one_has_no_session_end_close_itself_marks_it_before_the_session_goes(self):
        self.start('e', 'executor e --to obs')
        os.kill(int(next(pid for s, _, pid in self.panes() if s == 'e')), signal.SIGKILL)
        time.sleep(0.3)
        self.assertEqual(self.role('close', 'e')[0], 0)
        with open(self.at_kill) as f:
            self.assertTrue(json.load(f)['obs']['executors']['e']['closed'])
        self.assertEqual(self.team(), {})

    def test_force_signals_only_its_own_and_another_observers_executor_is_refused(self):
        self.start('e', 'executor e --to obs')
        self.start('obs2', 'observer obs2 --no-remote-control')
        self.start('f', 'executor f --to obs2')
        self.assertEqual(self.role('close', 'f', '--force')[0], 1)
        self.assertIn('f', [s for s, *_ in self.panes()])
        code, out = self.role('close', 'e', '--force')
        self.assertEqual(code, 0, out)
        self.assertEqual({s for s, *_ in self.panes()}, {'boot', 'obs', 'obs2', 'f'})
        with open(f'{self.state}/at-term.json') as f:
            self.assertTrue(json.load(f)['obs']['executors']['e']['closed'])

    def test_close_ends_what_the_executor_left_running_and_only_that(self):
        for force in ((), ('--force',)):
            with self.subTest(force = force):
                pids = os.path.join(self.state, 'kids')
                with contextlib.suppress(OSError):
                    os.remove(pids)
                # a child, and one that left the tree at once (setsid in a subshell); twins with the same command outside
                self.tmux('set-environment', '-g', 'LAB_KIDS', f'sleep 7351 & echo $! >> {pids}; '
                          f'(setsid sleep 7352 & echo $! >> {pids}); wait')
                twins = [subprocess.Popen(['sleep', n], env = self.env) for n in ('7351', '7352')]
                for twin in twins:
                    self.addCleanup(twin.wait)
                    self.addCleanup(twin.kill)
                self.start('e', 'executor e --to obs')
                deadline, kids = time.time() + 5, []
                while time.time() < deadline and len(kids) < 2:
                    time.sleep(0.05)
                    with contextlib.suppress(OSError), open(pids) as f:
                        kids = [int(p) for p in f.read().split()]
                self.assertEqual(len(kids), 2)
                for kid, born in [(k, roles.started(k)) for k in kids]:  # a red run leaves nothing behind either
                    self.addCleanup(lambda k, t: roles.started(k) == t and os.kill(k, signal.SIGKILL), kid, born)
                code, out = self.role('close', 'e', *force)
                self.assertEqual(code, 0, out)
                self.assertIn('ended what it left running', out)
                procs = roles.processes()
                self.assertEqual([k for k in kids if k in procs and procs[k][1][:1] == ['sleep']], [], out)
                self.assertEqual([t.poll() for t in twins], [None, None], 'the same command outside the tree lives')
                self.tmux('set-environment', '-g', '-u', 'LAB_KIDS')

    def started_kids(self, script, count):
        """An executor whose claude runs the bash script (it appends PIDs to $LAB_PIDS) → [(pid, start)] once all are up;
        teardown kills each that is still the same process."""
        pids = os.path.join(self.state, 'kids')
        self.tmux('set-environment', '-g', 'LAB_KIDS', f'export LAB_PIDS={pids}; {script}')
        self.start('e', 'executor e --to obs')
        deadline, kids = time.time() + 5, []
        while time.time() < deadline and len(kids) < count:
            time.sleep(0.05)
            with contextlib.suppress(OSError), open(pids) as f:
                kids = [int(p) for p in f.read().split()]
        self.assertEqual(len(kids), count)
        time.sleep(0.2)  # the execs after the echo are done
        kids = [(k, roles.started(k)) for k in kids]
        for kid, born in kids:
            self.addCleanup(lambda k, t: roles.started(k) == t and os.kill(k, signal.SIGKILL), kid, born)
        return kids

    def test_close_spares_a_user_wide_daemon_the_executor_started_and_its_subtree(self):
        # the rootless podman pause process shows as "catatonit -P" and leaves the tree: here a setsid one of that name
        under = f'{self.state}/under-daemon.sh'
        with open(under, 'w') as f:
            f.write('sleep 7357 & echo $! >> $LAB_PIDS; wait\n')
        started = dict(self.started_kids('sleep 7353 & echo $! >> $LAB_PIDS; (setsid bash -c "exec -a catatonit bash '
                                         f'{under}" & echo $! >> $LAB_PIDS); wait', 3))
        procs = roles.processes()
        by_argv = {procs[p][1][0] if procs[p][1][0] == 'catatonit' else ' '.join(procs[p][1]): p for p in started}
        kid, daemon, child = by_argv['sleep 7353'], by_argv['catatonit'], by_argv['sleep 7357']
        self.assertEqual(procs[child][0], daemon)
        self.assertFalse(roles.descends(daemon, int(next(p for s, _, p in self.panes() if s == 'e')), procs))
        code, out = self.role('close', 'e')
        self.assertEqual(code, 0, out)
        procs = roles.processes()
        self.assertEqual(procs.get(kid, (0, []))[1], [], out)  # gone or a zombie
        for spared, argv in ((daemon, ['catatonit', under]), (child, ['sleep', '7357'])):
            self.assertEqual((roles.started(spared), procs.get(spared, (0, []))[1]), (started[spared], argv), out)
            self.assertNotIn(f'{spared} {" ".join(argv)}', out)

    def test_close_spares_a_host_of_another_claude_and_its_subtree_and_ends_its_other_orphan(self):
        # a tmux server the executor started with setsid that now holds another session's pane: here a setsid bash with
        # a child named claude; a plain setsid orphan of the same executor beside it
        host = f'{self.state}/host.sh'
        with open(host, 'w') as f:
            f.write('bash -c "exec -a claude sleep 7363" & echo $! >> $LAB_PIDS; wait\n')
        started = dict(self.started_kids(f'(setsid bash {host} & echo $! >> $LAB_PIDS); '
                                         '(setsid sleep 7362 & echo $! >> $LAB_PIDS); wait', 3))
        procs = roles.processes()
        by_argv = {' '.join(procs[p][1]): p for p in started}
        server, claude, orphan = by_argv[f'bash {host}'], by_argv['claude 7363'], by_argv['sleep 7362']
        self.assertEqual(procs[claude][0], server)
        code, out = self.role('close', 'e')
        self.assertEqual(code, 0, out)
        procs = roles.processes()
        self.assertEqual(procs.get(orphan, (0, []))[1], [], out)  # gone or a zombie
        self.assertIn(f'{orphan} sleep 7362', out)
        for spared, argv in ((server, f'bash {host}'), (claude, 'claude 7363')):
            self.assertEqual(roles.started(spared), started[spared], out)
            self.assertNotIn(f'{spared} {argv}', out)

    def test_close_spares_a_container_monitor_and_its_subtree_and_reports_its_container(self):
        # podman's conmon leaves the tree with the executor's marks; here a setsid one of that name, with a child
        under = f'{self.state}/under-monitor.sh'
        with open(under, 'w') as f:
            f.write('sleep 7358 & echo $! >> $LAB_PIDS; wait\n')
        started = dict(self.started_kids('sleep 7359 & echo $! >> $LAB_PIDS; (setsid bash -c "exec -a conmon bash '
                                         f'{under} -c cid7358" & echo $! >> $LAB_PIDS); wait', 3))
        procs = roles.processes()
        by_argv = {' '.join(procs[p][1]): p for p in started}
        kid, monitor, child = by_argv['sleep 7359'], by_argv[f'conmon {under} -c cid7358'], by_argv['sleep 7358']
        self.assertEqual(procs[child][0], monitor)
        code, out = self.role('close', 'e')
        self.assertEqual(code, 0, out)
        procs = roles.processes()
        self.assertEqual(procs.get(kid, (0, []))[1], [], out)  # gone or a zombie
        for spared in (monitor, child):
            self.assertEqual(roles.started(spared), started[spared], out)
        self.assertIn(f'"e": its containers still run, not removed: container cid7358 (conmon {monitor})', out)
        self.assertNotIn(f'{child} sleep 7358', out)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'the ignored signal is read from /proc')
    def test_close_kills_a_leftover_that_ignores_sigterm(self):
        (kid, _), = self.started_kids('bash -c \'trap "" TERM; exec sleep 7355\' & echo $! >> $LAB_PIDS; wait', 1)
        with open(f'/proc/{kid}/status') as f:  # the fixture really ignores SIGTERM (bit 15 of SigIgn)
            self.assertTrue(int(next(l.split()[1] for l in f if l.startswith('SigIgn:')), 16) & 1 << signal.SIGTERM - 1)
        code, out = self.role('close', 'e')
        self.assertEqual(code, 0, out)
        self.assertIn('sleep 7355', out)
        self.assertEqual(roles.processes().get(kid, (0, []))[1], [], out)  # gone or a zombie

    def test_close_spares_the_checkpoint_the_session_end_hook_detaches(self):
        home, pid_file = f'{self.state}/home', f'{self.state}/watch.pid'
        os.makedirs(f'{home}/.claude/tools')
        with open(f'{home}/.claude/tools/session_watch.py', 'w') as f:  # stands for the checkpoint writer it detaches
            f.write(f'import os, time\nos.setsid()\nopen({pid_file!r}, "w").write(str(os.getpid()))\ntime.sleep(20)\n')
        for var, value in (('LAB_END', os.path.join(KIT, 'hooks/sessionend.sh')), ('LAB_HOME', home), ('SESSIONEND_MIN', '0')):
            self.tmux('set-environment', '-g', var, value)
        self.start('e', 'executor e --to obs')
        code, out = self.role('close', 'e')
        deadline = time.time() + 5
        while time.time() < deadline and not os.path.exists(pid_file):
            time.sleep(0.05)
        time.sleep(0.2)
        with open(pid_file) as f:
            watch = int(f.read())
        born = roles.started(watch)
        self.addCleanup(lambda: born is not None and roles.started(watch) == born and os.kill(watch, signal.SIGKILL))
        self.assertEqual(code, 0, out)
        self.assertIsNotNone(born, f'the session-end checkpoint was ended: {out}')

    def raced(self, race, *args):
        out = subprocess.run([sys.executable, '-c', RACE, KIT, race, *args], env = self.observer, capture_output = True, text = True)
        return out.returncode, out.stdout + out.stderr

    def test_claude_gone_before_the_signal_is_no_failure_cleanup_goes_on(self):
        self.start('e', 'executor e --to obs')
        code, out = self.raced('late-signal', 'close', 'e', '--force')
        self.assertEqual((code, 'closed by force' in out), (0, True), out)
        self.assertEqual(self.team(), {})

    def test_pane_gone_before_the_first_label_of_a_forced_close_is_no_failure(self):
        self.start('e', 'executor e --to obs')
        code, out = self.raced('1', 'close', 'e', '--force')
        self.assertEqual((code, 'closed by force' in out), (0, True), out)
        self.assertEqual(self.team(), {})

    def test_pane_gone_at_any_tmux_step_of_a_repeat_close_is_no_failure(self):
        for step in ('1', '2', '3', '4'):
            with self.subTest(step = step):
                self.start('e', 'executor e --to obs')
                os.kill(int(next(pid for s, _, pid in self.panes() if s == 'e')), signal.SIGKILL)
                time.sleep(0.3)
                code, out = self.raced(step, 'close', 'e')
                self.assertEqual((code, '"e": closed' in out), (0, True), out)
                self.assertEqual(self.team(), {})
                self.assertNotIn('e', [s for s, *_ in self.panes()])


class EndLeftovers(unittest.TestCase):
    def test_a_pid_whose_start_differs_from_the_snapshot_is_another_process_and_lives(self):
        # what close took before /exit ended and its PID went to another process: a start time other than the snapshot
        other = subprocess.Popen(['sleep', '7356'])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        born = roles.started(other.pid)
        self.assertEqual(launcher.end_leftovers('e', None, None, {other.pid: born - 5}), ([], []))
        self.assertIsNone(other.poll())
        self.assertEqual(launcher.end_leftovers('e', None, None, {other.pid: born}), ([f'{other.pid} sleep 7356'], []))
        self.assertEqual(other.wait(5), -signal.SIGTERM)


LIVE, DEAD = PROCS, {90: PROCS[90]}
OPEN, CLOSED = {'pane': '%7', 'session': 's', 'since': 1}, {'pane': '%7', 'session': 's', 'since': 1, 'closed': True}


def moment(tree, state, entry):
    """What a read sees at one moment of a close; state None: the pane is gone; entry None: dropped from the list."""
    return {'processes': tree, 'panes': [] if state is None else [executor_pane(state)],
            'read_roster': {'me': {'executors': {'e': entry} if entry else {}}}}


class ScanDuringClose(unittest.TestCase):
    """The moments of a close, in their order; the real waiter main reads each of its three reads at any later or same moment."""
    RUNNING = label(roles.RUNNING)  # no hang clock, unlike working
    NORMAL = [moment(LIVE, RUNNING, OPEN), moment(LIVE, '', OPEN), moment(DEAD, '', OPEN), moment(DEAD, '', CLOSED),
              moment(DEAD, None, CLOSED), moment(DEAD, None, None)]
    FORCED = [moment(LIVE, RUNNING, OPEN), moment(LIVE, '', OPEN), moment(LIVE, '', CLOSED), moment(DEAD, '', CLOSED),
              moment(DEAD, None, CLOSED), moment(DEAD, None, None)]
    RACED = [moment(LIVE, '', CLOSED), moment(LIVE, RUNNING, CLOSED), moment(DEAD, RUNNING, CLOSED), moment(DEAD, '', CLOSED)]  # a hook in flight wrote the label again

    def main(self, worlds):
        """→ exit code of the waiter main whose k-th read of one scan sees worlds[k]."""
        reads = iter(worlds)
        def reader(what):
            return lambda: next(reads)[what]
        pid = str(os.getpid())
        with mock.patch.multiple(roles, role_session = lambda: 'observer', own_claude = os.getpid, server_start = lambda: 0,
                                 pane_option = mock.Mock(side_effect = [pid, pid, '']), set_pane_option = mock.DEFAULT,
                                 unset_pane_option = mock.DEFAULT, update_roster = mock.DEFAULT, forget_tell = mock.DEFAULT,
                                 processes = reader('processes'), panes = reader('panes'), read_roster = reader('read_roster')), \
                mock.patch.dict(os.environ, {'TMUX_PANE': '%1', 'CLAUDE_ROLE_NAME': 'me'}), \
                mock.patch('sys.stdin', io.StringIO()), mock.patch('sys.stderr', io.StringIO()), mock.patch('time.sleep'):
            return waiter.main()

    def test_no_order_of_a_close_and_the_reads_wakes_the_observer(self):
        for close in (self.NORMAL, self.FORCED, self.RACED):
            for moments in itertools.combinations_with_replacement(close, 3):
                self.assertEqual(self.main(moments), 0, moments)

    def test_a_real_death_still_wakes_it(self):
        self.assertEqual(self.main([moment(DEAD, None, OPEN)] * 3), 2)
        self.assertEqual(self.main([moment(DEAD, self.RUNNING, OPEN)] * 3), 2)


def role_env(role, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('TMUX', 'CLAUDE_'))}
    env.update(CLAUDE_ROLE = role, CLAUDE_ROLE_NAME = 'n', TMUX_PANE = '%1', **extra)
    return env


class RoleIntro(unittest.TestCase):
    def line(self, role, kit = KIT, source = 'startup', **env):
        out = subprocess.run([sys.executable, os.path.join(kit, 'hooks/role-intro.py')], env = {**role_env(role), **env},
                             input = json.dumps({'source': source}), capture_output = True, text = True, check = True).stdout
        return json.loads(out)['hookSpecificOutput']['additionalContext'] if out else ''

    def test_every_source_gets_who_and_the_whole_text_of_the_role(self):
        for role in ('observer', 'executor'):
            with open(os.path.join(KIT, 'roles', f'{role}.md'), encoding = 'utf-8') as f:
                text = f.read()
            for source in ('startup', 'resume', 'clear', 'compact'):
                with self.subTest(role = role, source = source):
                    line = self.line(role, source = source)
                    self.assertIn(f'You are the {role} "n"', line)
                    self.assertTrue(line.endswith(text.splitlines()[-1] + '\n'), line[-200:])
                    self.assertIn(text, line)
                    self.assertNotIn('Skill', line.split('\n')[0])

    def test_the_observer_gets_the_push_reminder_and_no_role_is_silent(self):
        self.assertIn(' And load the push tool right away: ToolSearch("select:PushNotification").', self.line('observer'))
        self.assertNotIn('ToolSearch("select', self.line('executor'))
        self.assertEqual(self.line('none'), '')

    def test_a_stdout_not_in_utf8_still_gets_the_whole_text(self):
        with open(os.path.join(KIT, 'roles', 'observer.md'), encoding = 'utf-8') as f:
            self.assertIn(f.read(), self.line('observer', PYTHONIOENCODING = 'ascii'))

    def test_a_name_not_in_utf8_still_gets_the_text(self):
        self.assertIn('# Executor', self.line('executor', CLAUDE_ROLE_NAME = 'a\udcff'))

    def test_a_missing_file_says_who_and_the_path(self):
        kit = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, kit, True)
        for rel in ('hooks/role-intro.py', 'tools/roles.py'):
            os.makedirs(os.path.dirname(os.path.join(kit, rel)), exist_ok = True)
            shutil.copy(os.path.join(KIT, rel), os.path.join(kit, rel))
        line = self.line('executor', kit)
        self.assertIn('You are the executor "n"', line)
        self.assertIn(os.path.join(os.path.realpath(kit), 'roles', 'executor.md'), line)


class ObserverSkills(unittest.TestCase):
    """The real role-state hook; a tmux that answers nothing keeps the hook off every real server."""
    DENY = 'this skill is not for the observer, give it to a subagent or an executor\n' + roles.OPERATOR_LANGUAGE

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        tmux = os.path.join(self.home, 'tmux')
        with open(tmux, 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        os.chmod(tmux, 0o755)

    def run_hook(self, role, payload):
        env = role_env(role, CLAUDE_ROLES_STATE_DIR = self.home)
        env['PATH'] = f'{self.home}:{env["PATH"]}'
        return subprocess.run([sys.executable, os.path.join(KIT, 'hooks/role-state.py')], input = payload, env = env,
                              cwd = self.home, capture_output = True, text = True)

    def decision(self, role, skill, **ev):
        done = self.run_hook(role, json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'Skill', 'session_id': 's', 'cwd': self.home,
                                               'tool_input': {'skill': skill}, **ev}))
        self.assertEqual(done.returncode, 0, done.stderr)
        said = [json.loads(line)['hookSpecificOutput'] for line in done.stdout.splitlines()]
        return next((s for s in said if s.get('permissionDecision')), None)

    def test_a_foreign_skill_is_denied(self):
        for skill in ('engineering', '/engineering', 'plugin:orchestration'):
            with self.subTest(skill = skill):
                self.assertEqual(self.decision('observer', skill),
                                 {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': self.DENY})

    def test_a_table_skill_is_allowed(self):
        for skill in (*roles.OBSERVER_SKILLS, '/orchestration'):
            with self.subTest(skill = skill):
                self.assertIsNone(self.decision('observer', skill))

    def test_a_subagent_of_the_observer_is_untouched(self):
        self.assertIsNone(self.decision('observer', 'engineering', agent_id = 'a1'))

    def test_an_executor_and_no_role_are_untouched(self):
        for role in ('executor', 'none'):
            with self.subTest(role = role):
                self.assertIsNone(self.decision(role, 'engineering'))

    def test_another_tool_of_the_observer_is_untouched(self):
        done = self.run_hook('observer', json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'Read', 'session_id': 's', 'cwd': self.home, 'tool_input': {}}))
        self.assertNotIn('deny', done.stdout)

    def test_a_malformed_payload_fails_open(self):
        base = {'hook_event_name': 'PreToolUse', 'tool_name': 'Skill', 'session_id': 's', 'cwd': self.home}
        for payload in ('{', '[]', json.dumps(base), json.dumps({**base, 'tool_input': 'x'}), json.dumps({**base, 'tool_input': {'skill': 1}})):
            with self.subTest(payload = payload):
                done = self.run_hook('observer', payload)
                self.assertNotEqual(done.returncode, 2)  # exit 2 is the one failing exit that blocks
                self.assertNotIn('deny', done.stdout)


class CompactResume(unittest.TestCase):
    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.cwd = os.path.join(self.home, 'project')
        self.file = os.path.join(self.cwd, '.claude', 'checkpoints', 'abcdefgh-session.md')
        os.makedirs(os.path.dirname(self.file))

    def output(self, text, role = None):
        """The hook's stdout with this checkpoint (None: none) in a session of this role (None: no role)."""
        if text is None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.file)
        else:
            with open(self.file, 'w', encoding = 'utf-8') as f:
                f.write(text)
        env = role_env(role) if role else {k: v for k, v in os.environ.items() if not k.startswith(('TMUX', 'CLAUDE_'))}
        env.update(HOME = self.home, PATH = f'{os.path.dirname(sys.executable)}:{os.environ["PATH"]}')  # the kit's python
        return subprocess.run(['bash', os.path.join(KIT, 'hooks/compact-resume.sh')], input = json.dumps({'session_id': 'abcdefgh-1', 'cwd': self.cwd}),
                              env = env, capture_output = True, text = True, check = True).stdout

    def context(self, out):
        return json.loads(out)['hookSpecificOutput']['additionalContext']

    def test_a_long_checkpoint_is_cut_under_the_limit_and_names_its_file(self):
        for filler in ('x' * 20000, 'a "quoted" line\n' * 1250, chr(0x436) * 20000, chr(0x1F600) * 20000):  # escapes count in the output; a character is one unit, an emoji two
            with self.subTest(filler = filler[:16]):
                out = self.output(filler)
                units = lambda text: len(text.encode('utf-16-le')) // 2
                self.assertLess(units(out), roles.CONTEXT_LIMIT)
                self.assertGreater(units(out), roles.CONTEXT_LIMIT - 100)
                self.assertLessEqual(units(self.context(out)), roles.CONTEXT_LIMIT)
                self.assertEqual(self.context(out).splitlines()[-1], f'--- checkpoint cut here, the rest is in {self.file} ---')

    def test_an_observer_text_ends_with_the_language_line_within_the_limit(self):
        units = lambda text: len(text.encode('utf-16-le')) // 2
        for filler in ('short', 'x' * 20000, None):
            for role, ends in (('observer', True), ('executor', False)):
                with self.subTest(filler = (filler or '')[:8], role = role):
                    out = self.output(filler, role)
                    self.assertEqual(self.context(out).endswith('\n' + roles.OPERATOR_LANGUAGE), ends)
                    self.assertLess(units(out), roles.CONTEXT_LIMIT)

    def test_a_short_checkpoint_arrives_whole(self):
        context = self.context(self.output('line one\nline two'))
        self.assertIn('line one\nline two\n--- end of checkpoint ---', context)
        self.assertNotIn('cut here', context)


class ObserverTable(unittest.TestCase):
    def test_every_command_of_the_usage_is_in_the_observer_table(self):
        with open(os.path.join(KIT, 'roles/observer.md'), encoding = 'utf-8') as f:
            table = ' '.join(line for line in f if line.startswith('|'))
        commands = set(re.findall(r'claude-role (\w+)', launcher.USAGE))
        self.assertIn('close', commands)
        self.assertEqual({c for c in commands if f'claude-role {c}' not in table}, set())


if __name__ == '__main__':
    unittest.main()
