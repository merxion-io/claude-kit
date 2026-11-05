#!/usr/bin/env python3
# The Stop of a role session with leftovers and the wake of a stop with background: python3 tools/test_leftovers.py.
# A dummy claude (a script named claude) runs the real hooks/role-state.py as claude does and keeps the children the
# test asks for, in Bash-tool shells as the harness makes them (a background task's shell writes to its tasks/<id>.output);
# a tmux that only logs keeps the hook off every real server.
import importlib.machinery, importlib.util, json, os, re, shutil, signal, subprocess, sys, tempfile, time, unittest

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(KIT, 'tools'))
sys.dont_write_bytecode = True
os.environ['CLAUDE_ROLES_STATE_DIR'] = tempfile.mkdtemp()
import roles

loader = importlib.machinery.SourceFileLoader('observer_wait', os.path.join(KIT, 'hooks/observer-wait.py'))
waiter = importlib.util.module_from_spec(importlib.util.spec_from_loader('observer_wait', loader))
loader.exec_module(waiter)

SESSION = 's'
# argv: hook path. Sets its own role PID mark, starts each command of LAB_KIDS in a Bash-tool shell and each [id, command]
# of LAB_TASKS in a Bash-tool shell writing to $TMPDIR/claude-<uid>/<project>/<session>/tasks/<id>.output, each command
# of LAB_MONITORS in a Bash-tool shell writing to a pipe with the command quoted in its argv, prints the shell PIDs; then each stdin line is a hook input: the hook runs through sh -c (as claude runs hooks), its stdout is printed.
DUMMY = r"""#!/usr/bin/env python3
import json, os, shlex, subprocess, sys
os.environ['CLAUDE_ROLE_PID'] = str(os.getpid())
snapshot = f'source {os.environ["LAB_SNAPSHOT"]} 2>/dev/null'
shells = [subprocess.Popen(['bash', '-c', f'{snapshot}; {cmd} & wait'],
                           stdin = subprocess.DEVNULL, stdout = subprocess.DEVNULL) for cmd in json.loads(os.environ.get('LAB_KIDS', '[]'))]
tasks = os.environ['LAB_TASK_DIR']
os.makedirs(tasks, exist_ok = True)
for task, cmd in json.loads(os.environ.get('LAB_TASKS', '[]')):
    with open(os.path.join(tasks, f'{task}.output'), 'w') as out:
        shells.append(subprocess.Popen(['bash', '-c', f'{snapshot}; {cmd}; status=$?'], stdin = subprocess.DEVNULL, stdout = out,
                                       stderr = out))
for cmd in json.loads(os.environ.get('LAB_MONITORS', '[]')):  # a Monitor's shell: stdout a pipe, the command in its argv
    shells.append(subprocess.Popen(['bash', '-c', f'{snapshot}; eval {shlex.quote(cmd)} < /dev/null && pwd -P >| /dev/null'],
                                   stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.PIPE))
servers = [subprocess.Popen(['bash', '-c', f'{c} & wait'], stdout = subprocess.DEVNULL) for c in json.loads(os.environ.get('LAB_MCP', '[]'))]
print(json.dumps([s.pid for s in shells]), flush = True)
for line in sys.stdin:
    out = subprocess.run(['sh', '-c', f'"{sys.executable}" "{sys.argv[1]}"'], input = line, capture_output = True, text = True)
    print(json.dumps({'out': out.stdout, 'err': out.stderr}), flush = True)
"""

LOG_TMUX = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$LAB_TMUX_LOG"\nexit 0\n'
AGE = r'\d\d:\d\d:\d\d'


class Dummy:
    """A dummy claude of a role with its children; stop() runs the real Stop hook as that session."""
    def __init__(self, case, role, name, kids = (), hook = os.path.join(KIT, 'hooks/role-state.py'), mcp = (), tasks = (),
                 monitors = (), expect = None):
        self.name = name
        env = {k: v for k, v in os.environ.items() if not k.startswith(('TMUX', 'CLAUDE_'))}
        env.update(CLAUDE_ROLE = role, CLAUDE_ROLE_NAME = name, TMUX_PANE = '%1', CLAUDE_ROLES_STATE_DIR = case.home,
                   PATH = f'{case.bin}:{env["PATH"]}', LAB_TMUX_LOG = case.tmux_log, LAB_KIDS = json.dumps(list(kids)),
                   LAB_SNAPSHOT = case.snapshot, LAB_MCP = json.dumps(list(mcp)), TMPDIR = case.tmp,
                   LAB_TASK_DIR = case.task_dir, LAB_TASKS = json.dumps([list(t) for t in tasks]),
                   LAB_MONITORS = json.dumps(list(monitors)))
        self.proc = subprocess.Popen([os.path.join(case.bin, 'claude'), hook], env = env,
                                     stdin = subprocess.PIPE, stdout = subprocess.PIPE, text = True)
        case.addCleanup(self.close)
        self.shells = json.loads(self.proc.stdout.readline())
        self.kids, self.orphans = self.wait_kids(kids, len(kids) if expect is None else expect)

    def wait_kids(self, kids, expect):
        """Once all are up: PIDs of the commands under the shells, and of the "(setsid <command> &)" ones that left the
        tree (by their argv, out of the dummy's tree)."""
        gone = [k[len('(setsid '):-len(' &)')].split() for k in kids if k.startswith('(setsid ')]
        deadline = time.time() + 5
        while time.time() < deadline:
            procs = roles.processes()
            under = [p for p in procs if procs[p][0] in self.shells]
            out = [p for p, (_, argv) in procs.items() if argv in gone and not roles.descends(p, self.proc.pid, procs)]
            if len(under) + len(out) >= expect:
                return under, out
            time.sleep(0.05)
        raise AssertionError(f'children did not come up: {under} {out}')

    def stop(self, **ev):
        """Runs the Stop hook → its stdout (a decision would be there) and the whole run."""
        self.proc.stdin.write(json.dumps({'hook_event_name': 'Stop', 'session_id': SESSION, 'cwd': '/',
                                          'stop_hook_active': False, 'last_assistant_message': 'done', **ev}) + '\n')
        self.proc.stdin.flush()
        out = json.loads(self.proc.stdout.readline())
        return out['out'], out

    def close(self):
        procs = roles.processes()
        mine = [p for p in procs if p != self.proc.pid and roles.descends(p, self.proc.pid, procs)]
        for p in mine + self.orphans:
            with_gone(os.kill, p, signal.SIGKILL)
        self.proc.kill()
        self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()


def with_gone(call, *args):
    try:
        call(*args)
    except ProcessLookupError:
        pass


class Case(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix = 'lg')
        self.addCleanup(shutil.rmtree, self.home, True)
        self.bin, self.tmux_log = os.path.join(self.home, 'bin'), os.path.join(self.home, 'tmux.log')
        self.snapshot = os.path.join(self.home, 'shell-snapshots', 'snapshot-bash-1.sh')
        self.tmp = os.path.join(self.home, 'tmp')
        self.task_dir = os.path.join(self.tmp, f'claude-{os.getuid()}', '-project', SESSION, 'tasks')
        os.makedirs(self.bin)
        os.makedirs(os.path.dirname(self.snapshot))
        open(self.snapshot, 'w').close()
        for name, body in (('claude', DUMMY), ('tmux', LOG_TMUX)):
            with open(os.path.join(self.bin, name), 'w') as f:
                f.write(body)
            os.chmod(os.path.join(self.bin, name), 0o755)

    def labels(self):
        """State labels the hook wrote, in order."""
        try:
            with open(self.tmux_log) as f:
                lines = f.read().splitlines()
        except OSError:
            return []
        return [line.split(f' {roles.STATE} ', 1)[1] for line in lines
                if line.startswith('set-option') and f' {roles.STATE} ' in line]

    def passed(self, dummy, **ev):
        """A Stop that writes no decision → the wake lines of its label ("stopped with background"), [] for "stopped"."""
        said, out = dummy.stop(**ev)
        self.assertEqual(said, '', out)
        kind, _, text = roles.parse_state(self.labels()[-1])
        if kind == roles.STOPPED:
            return []
        self.assertEqual(kind, roles.STOPPED_BACKGROUND, self.labels())
        return text.split('; ')


@unittest.skipUnless(sys.platform.startswith('linux'), 'task shells and orphans are found in /proc: Linux')
class StopNeverBlocks(Case):
    def test_tasks_and_an_orphan_are_listed_with_ages_and_folded_processes(self):
        executor = Dummy(self, 'executor', 'e', ['(setsid sleep 7401 &)'],
                         tasks = [('bsh1', 'sleep 7402 & sleep 7403 & sleep 7404 & wait')], expect = 4)
        orphan, = executor.orphans
        subagent = os.path.join(self.task_dir, 'a1.output')
        os.symlink(os.path.join(self.home, 'agent-a1.jsonl'), subagent)  # a subagent's file is a link, its target aside
        lines = self.passed(executor, background_tasks = [
            {'id': 'bsh1', 'type': 'shell', 'status': 'running', 'description': 'three sleeps'},
            {'id': 'a1', 'type': 'subagent', 'status': 'running', 'description': 'Build X'},
            {'id': 'm1', 'type': 'monitor', 'status': 'running', 'description': 'live updates (auto-armed on publish)'}])
        self.assertRegex(lines[0], rf'^bsh1 · shell · three sleeps · {AGE} \(\+3 processes\)$')
        self.assertRegex(lines[1], rf'^a1 · subagent · Build X · {AGE}$')
        self.assertEqual(lines[2], 'm1 · monitor · live updates (auto-armed on publish)', 'no output file: no age')
        self.assertRegex(lines[3], rf'^orphan {orphan} · {AGE} · sleep 7401$')
        self.assertEqual(len(lines), 4, lines)

    def test_a_task_age_is_its_output_file_birth_not_its_shell_start(self):
        os.makedirs(self.task_dir)
        open(os.path.join(self.task_dir, 'bsh2.output'), 'w').close()  # the dummy reopens it: the birth stays
        time.sleep(2.1)
        executor = Dummy(self, 'executor', 'e', tasks = [('bsh2', 'sleep 7405')], expect = 1)
        line, = self.passed(executor, background_tasks = [{'id': 'bsh2', 'type': 'shell', 'description': 'one'}])
        seconds = int(re.fullmatch(rf'bsh2 · shell · one · 00:00:(\d\d) \(\+1 processes\)', line).group(1))
        self.assertGreaterEqual(seconds, 2, line)

    def test_a_churning_child_of_a_task_shell_is_folded_never_a_line(self):
        executor = Dummy(self, 'executor', 'e', tasks = [('bmon', 'while true; do sleep 0.3; done')], expect = 1)
        task = [{'id': 'bmon', 'type': 'shell', 'description': 'watch'}]
        first = executor.kids
        for _ in range(2):
            lines = self.passed(executor, background_tasks = task)
            self.assertEqual(len(lines), 1, lines)
            self.assertRegex(lines[0], rf'^bmon · shell · watch · {AGE}( \(\+1 processes\))?$')
            time.sleep(0.5)
        procs = roles.processes()
        self.assertNotEqual([p for p in procs if procs[p][0] in executor.shells], first, 'the child was replaced')

    def test_a_monitor_shell_with_no_output_file_is_tied_by_its_command_and_its_churning_child_folded(self):
        watch = "while true; do sleep 0.3; done # it's quoted"
        executor = Dummy(self, 'executor', 'e', monitors = [watch, watch], expect = 2)
        for shell in executor.shells:
            self.assertTrue(os.readlink(f'/proc/{shell}/fd/1').startswith('pipe:'), 'no output file to link by')
        task = {'type': 'shell', 'description': 'watch', 'command': watch}
        first = executor.kids
        for _ in range(2):
            lines = self.passed(executor, background_tasks = [{'id': 'bm1', **task}, {'id': 'bm2', **task}])
            self.assertEqual(len(lines), 2, lines)
            for i, line in enumerate(lines):  # each shell once; the age is the shell's start
                self.assertRegex(line, rf'^bm{i + 1} · shell · watch · {AGE}( \(\+1 processes\))?$')
            time.sleep(0.5)
        procs = roles.processes()
        self.assertNotEqual([p for p in procs if procs[p][0] in executor.shells], first, 'the children were replaced')

    def test_a_monitor_task_without_a_command_leaves_its_child_an_orphan(self):
        executor = Dummy(self, 'executor', 'e', monitors = ['sleep 7407'], expect = 1)
        lines = self.passed(executor, background_tasks = [{'id': 'bm3', 'type': 'shell', 'description': 'quiet'}])
        self.assertEqual(lines[0], 'bm3 · shell · quiet', 'no link, no command: no shell, no age')
        self.assertRegex(lines[1], rf'^orphan {executor.kids[0]} · {AGE} · sleep 7407$')

    def test_a_shell_of_a_task_not_in_the_input_leaves_orphans(self):
        executor = Dummy(self, 'executor', 'e', tasks = [('bold', 'sleep 7406')], expect = 1)
        line, = self.passed(executor)
        self.assertRegex(line, rf'^orphan {executor.kids[0]} · {AGE} · sleep 7406$')

    def test_a_child_of_a_foreground_shell_is_an_orphan_line(self):
        executor = Dummy(self, 'executor', 'e', ['sleep 7301'])
        line, = self.passed(executor)
        self.assertRegex(line, rf'^orphan {executor.kids[0]} · {AGE} · sleep 7301$')

    def test_a_user_wide_daemon_it_started_and_its_subtree_are_not_listed(self):
        # the rootless podman pause process shows as "catatonit -P": every rootless container of the user runs under it
        executor = Dummy(self, 'executor', 'e', ['exec -a catatonit bash -c "sleep 7313 & wait"', 'sleep 7314'])
        deadline, found = time.time() + 5, []
        while time.time() < deadline and not found:  # the subshell execs it, then it starts its child
            procs = roles.processes()
            found = [(k, p) for k in executor.kids if procs.get(k, (0, ['']))[1][0] == 'catatonit'
                     for p, (ppid, argv) in procs.items() if ppid == k and argv == ['sleep', '7313']]
        self.assertTrue(found)
        line, = self.passed(executor)
        self.assertTrue(line.endswith(' · sleep 7314'), line)

    def test_a_host_of_another_claude_it_started_is_not_listed_its_other_orphan_is(self):
        # a tmux server the executor started with setsid that now holds another session's pane: here a setsid bash with
        # a child named claude
        host = os.path.join(self.home, 'host.sh')
        with open(host, 'w') as f:
            f.write('bash -c "exec -a claude sleep 7317" & wait\n')
        executor = Dummy(self, 'executor', 'e', [f'(setsid bash {host} &)', '(setsid sleep 7318 &)'])
        deadline, hosted = time.time() + 5, []
        while time.time() < deadline and not hosted:  # the host starts its child, then the child execs
            procs = roles.processes()
            hosted = [p for p, (ppid, argv) in procs.items() if ppid in executor.orphans and argv == ['claude', '7317']]
        claude, = hosted
        self.addCleanup(with_gone, os.kill, claude, signal.SIGKILL)
        server, = [p for p in executor.orphans if procs[p][1] == ['bash', host]]
        orphan, = [p for p in executor.orphans if p != server]
        line, = self.passed(executor)
        self.assertTrue(line.startswith(f'orphan {orphan} · '), line)

    def test_a_container_monitor_it_started_and_its_subtree_are_listed_once_as_its_container(self):
        under = os.path.join(self.home, 'under-monitor.sh')
        with open(under, 'w') as f:
            f.write('sleep 7315 & wait\n')
        executor = Dummy(self, 'executor', 'e', [f'exec -a conmon bash {under} -c cid7315 -n box7315', 'sleep 7316'])
        deadline, found = time.time() + 5, []
        while time.time() < deadline and not found:  # the subshell execs it, then it starts its child
            procs = roles.processes()
            found = [(k, p) for k in executor.kids if procs.get(k, (0, ['']))[1][:1] == ['conmon']
                     for p, (ppid, argv) in procs.items() if ppid == k and argv == ['sleep', '7315']]
        (monitor, child), = found
        lines = self.passed(executor)
        self.assertEqual(len(lines), 2, lines)
        self.assertIn(f'orphan {monitor} · ', lines[0] + lines[1])
        self.assertEqual(';'.join(lines).count(f'container box7315 (conmon {monitor})'), 1, lines)
        self.assertIn('sleep 7316', lines[0] + lines[1])

    def test_background_tasks_alone_stop_with_background(self):
        executor = Dummy(self, 'executor', 'e')
        self.assertEqual(self.passed(executor, background_tasks = [{'id': 'bash7', 'type': 'shell', 'description': 'npm run dev'}]),
                         ['bash7 · shell · npm run dev'])

    def test_an_observer_counts_only_its_own_tree(self):
        observer = Dummy(self, 'observer', 'o')  # first: its executor's processes are younger, only their marks are not its
        Dummy(self, 'executor', 'e', ['sleep 7304', '(setsid sleep 7305 &)'])
        said, out = observer.stop()
        self.assertEqual(said, '', out)
        self.assertEqual(roles.background([], SESSION, observer.proc.pid, 'o'), [])
        own = Dummy(self, 'observer', 'o2', ['sleep 7306'])
        line, = roles.background([], SESSION, own.proc.pid, 'o2')
        self.assertTrue(line.startswith(f'orphan {own.kids[0]} · '), line)

    def test_harness_children_and_a_clean_tree_stop_clean(self):
        executor = Dummy(self, 'executor', 'e', mcp = ['sleep 7307'])  # a direct child, not a Bash-tool shell: an MCP server
        deadline, procs = time.time() + 5, {}
        while time.time() < deadline and ['sleep', '7307'] not in [argv for _, argv in procs.values()]:
            time.sleep(0.05)
            procs = roles.processes()
        server, = [p for p, (ppid, argv) in procs.items() if argv == ['sleep', '7307']]
        self.assertTrue(roles.descends(server, executor.proc.pid, procs) and procs[server][0] != executor.proc.pid,
                        'the server has a child of its own')
        self.assertEqual(self.passed(executor), [])

    def test_a_process_with_its_marks_older_than_its_claude_is_not_its(self):
        # a reused PID: the marks name this claude's PID, the process started before it
        forged = subprocess.Popen(['sh', '-c', 'read p; exec env CLAUDE_ROLE_PID=$p CLAUDE_ROLE_NAME=e sleep 7312'],
                                  stdin = subprocess.PIPE, text = True)
        self.addCleanup(forged.wait)
        self.addCleanup(with_gone, forged.kill)
        time.sleep(0.05)
        executor = Dummy(self, 'executor', 'e')
        forged.stdin.write(f'{executor.proc.pid}\n')
        forged.stdin.close()
        deadline = time.time() + 5
        while time.time() < deadline and roles.role_mark(forged.pid) != (str(executor.proc.pid), 'e'):
            time.sleep(0.05)
        self.assertEqual(roles.role_mark(forged.pid), (str(executor.proc.pid), 'e'))
        self.assertEqual(self.passed(executor), [])

    def test_a_subagent_stop_is_untouched(self):
        executor = Dummy(self, 'executor', 'e', ['sleep 7308'])
        said, out = executor.stop(hook_event_name = 'SubagentStop', agent_id = 'a1')
        self.assertEqual(said, '', out)
        self.assertEqual(self.labels(), [])

    def test_a_failing_scan_lists_the_tasks_and_logs_its_trace(self):
        hook, broken = os.path.join(KIT, 'hooks/role-state.py'), os.path.join(self.home, 'broken.py')
        with open(broken, 'w') as f:  # the real hook with a process scan that raises
            f.write(f'import sys; sys.path.insert(0, {os.path.join(KIT, "tools")!r}); import roles\n'
                    'def boom(*a): raise RuntimeError("scan broke")\nroles.leftovers = boom\n'
                    f'exec(compile(open({hook!r}).read(), {hook!r}, "exec"))\n')
        executor = Dummy(self, 'executor', 'e', ['sleep 7309'], hook = broken)
        self.assertEqual(self.passed(executor, background_tasks = [{'id': 'b2', 'type': 'shell', 'description': 'x'}]),
                         ['b2 · shell · x'])
        with open(os.path.join(self.home, 'logs', 'leftover-guard.log')) as f:
            self.assertIn('scan broke', f.read())

    def test_the_scan_is_cheap(self):
        executor = Dummy(self, 'executor', 'e', ['sleep 7311'])
        began = time.time()
        executor.stop()
        took = time.time() - began
        print(f'\nStop hook with the scan: {took * 1000:.0f} ms', file = sys.stderr)
        self.assertLess(took, 1.0)


class Fold(unittest.TestCase):
    """roles.fold, pure: what runs under a listed task's shell is the task's."""
    PROCS = {10: (1, ['claude']), 20: (10, ['bash']), 21: (20, ['sleep']), 22: (21, ['sleep']), 30: (10, ['bash']),
             31: (30, ['sleep']), 40: (1, ['sleep'])}

    def test_children_under_a_listed_shell_fold_the_rest_stay(self):
        tasks = [{'id': 't1'}, {'id': 't2'}]
        rest = [(21, 5, 'sleep'), (22, 5, 'sleep'), (31, 5, 'sleep'), (40, 5, 'sleep')]
        self.assertEqual(roles.fold(tasks, {'t1': 20, 'gone': 30}, rest, self.PROCS),
                         ([(tasks[0], 2), (tasks[1], 0)], [(31, 5, 'sleep'), (40, 5, 'sleep')]))


class StopWakes(Case):
    """The label a stop writes, read by the real waiter scan."""
    def wakes(self, label):
        pane = {'pane_id': '%7', 'session_name': 's', 'pane_pid': '90', 'pane_current_command': 'claude',
                '@claude_role': 'executor', '@claude_name': 'e', '@claude_observer': 'me', '@claude_state': label,
                '@claude_seen': '', '@claude_flags': '', roles.PID_LABEL: '100'}
        return waiter.attention('me', [pane], {100: (90, ['claude']), 90: (1, ['zsh'])}, time.time(), {}, 0)

    def test_a_stop_with_background_does_not_wake_the_observer(self):
        executor = Dummy(self, 'executor', 'e')
        executor.stop(background_tasks = [{'id': 'b1', 'type': 'subagent', 'description': 'Build X'}])
        self.assertTrue(self.labels()[-1].startswith(roles.STOPPED_BACKGROUND + roles.SEP), self.labels())
        self.assertEqual(self.wakes(self.labels()[-1]), [])

    def test_a_stop_without_background_wakes_as_before(self):
        executor = Dummy(self, 'executor', 'e')
        executor.stop(last_assistant_message = 'all done')
        found = self.wakes(self.labels()[-1])
        self.assertEqual(len(found), 1, self.labels())
        self.assertIn('stopped · ', found[0][3])
        self.assertIn('all done', found[0][3])


if __name__ == '__main__':
    unittest.main()
