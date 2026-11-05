#!/usr/bin/env python3
# The Stop guard on leftovers and the wake of a stop with background: python3 tools/test_leftovers.py. A dummy claude
# (a script named claude) runs the real hooks/role-state.py as claude does and keeps the children the test asks for, in
# a Bash-tool shell as the harness makes them; a tmux that only logs keeps the hook off every real server.
import importlib.machinery, importlib.util, json, os, shutil, signal, subprocess, sys, tempfile, time, unittest

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(KIT, 'tools'))
sys.dont_write_bytecode = True
os.environ['CLAUDE_ROLES_STATE_DIR'] = tempfile.mkdtemp()
import roles

loader = importlib.machinery.SourceFileLoader('observer_wait', os.path.join(KIT, 'hooks/observer-wait.py'))
waiter = importlib.util.module_from_spec(importlib.util.spec_from_loader('observer_wait', loader))
loader.exec_module(waiter)

# argv: hook path. Sets its own role PID mark, starts each command of LAB_KIDS in a Bash-tool shell, prints the shell
# PIDs; then each stdin line is a hook input: the hook runs through sh -c (as claude runs hooks), its stdout is printed.
DUMMY = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
os.environ['CLAUDE_ROLE_PID'] = str(os.getpid())
shells = [subprocess.Popen(['bash', '-c', f'source {os.environ["LAB_SNAPSHOT"]} 2>/dev/null; {cmd} & wait'],
                           stdin = subprocess.DEVNULL, stdout = subprocess.DEVNULL) for cmd in json.loads(os.environ.get('LAB_KIDS', '[]'))]
servers = [subprocess.Popen(['bash', '-c', f'{c} & wait'], stdout = subprocess.DEVNULL) for c in json.loads(os.environ.get('LAB_MCP', '[]'))]
print(json.dumps([s.pid for s in shells]), flush = True)
for line in sys.stdin:
    out = subprocess.run(['sh', '-c', f'"{sys.executable}" "{sys.argv[1]}"'], input = line, capture_output = True, text = True)
    print(json.dumps({'out': out.stdout, 'err': out.stderr}), flush = True)
"""

LOG_TMUX = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$LAB_TMUX_LOG"\nexit 0\n'


class Dummy:
    """A dummy claude of a role with its children; stop() runs the real Stop hook as that session."""
    def __init__(self, case, role, name, kids = (), hook = os.path.join(KIT, 'hooks/role-state.py'), mcp = ()):
        self.name = name
        env = {k: v for k, v in os.environ.items() if not k.startswith(('TMUX', 'CLAUDE_'))}
        env.update(CLAUDE_ROLE = role, CLAUDE_ROLE_NAME = name, TMUX_PANE = '%1', CLAUDE_ROLES_STATE_DIR = case.home,
                   PATH = f'{case.bin}:{env["PATH"]}', LAB_TMUX_LOG = case.tmux_log, LAB_KIDS = json.dumps(list(kids)),
                   LAB_SNAPSHOT = case.snapshot, LAB_MCP = json.dumps(list(mcp)))
        self.proc = subprocess.Popen([os.path.join(case.bin, 'claude'), hook], env = env,
                                     stdin = subprocess.PIPE, stdout = subprocess.PIPE, text = True)
        case.addCleanup(self.close)
        self.shells = json.loads(self.proc.stdout.readline())
        self.kids, self.orphans = self.wait_kids(kids)

    def wait_kids(self, kids):
        """Once all are up: PIDs of the commands under the shells, and of the "(setsid <command> &)" ones that left the
        tree (by their argv, out of the dummy's tree)."""
        gone = [k[len('(setsid '):-len(' &)')].split() for k in kids if k.startswith('(setsid ')]
        deadline = time.time() + 5
        while time.time() < deadline:
            procs = roles.processes()
            under = [p for p in procs if procs[p][0] in self.shells]
            out = [p for p, (_, argv) in procs.items() if argv in gone and not roles.descends(p, self.proc.pid, procs)]
            if len(under) + len(out) >= len(kids):
                return under, out
            time.sleep(0.05)
        raise AssertionError(f'children did not come up: {under} {out}')

    def stop(self, **ev):
        self.proc.stdin.write(json.dumps({'hook_event_name': 'Stop', 'session_id': 's', 'cwd': '/', 'stop_hook_active': False,
                                          'last_assistant_message': 'done', **ev}) + '\n')
        self.proc.stdin.flush()
        out = json.loads(self.proc.stdout.readline())
        return json.loads(out['out']) if out['out'].strip().startswith('{"decision"') else None, out

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


@unittest.skipUnless(sys.platform.startswith('linux'), 'orphans are found by /proc marks: Linux')
class StopGuard(Case):
    def test_an_executor_with_a_live_child_is_held_once_then_passes_when_it_is_gone(self):
        executor = Dummy(self, 'executor', 'e', ['sleep 7301'])
        block, out = executor.stop()
        self.assertIsNotNone(block, out)
        self.assertIn(f'{executor.kids[0]} · ', block['reason'])
        self.assertIn('sleep 7301', block['reason'])
        self.assertTrue(block['reason'].startswith('Leftovers still running:\n'), block)
        self.assertTrue(block['reason'].endswith('\nClose them, or say why each must outlive you.'), 'an executor text has no language line')
        self.assertEqual(self.labels(), [], 'a held stop writes no label and wakes no one')
        os.kill(executor.kids[0], signal.SIGKILL)
        time.sleep(0.2)
        self.assertEqual(executor.stop()[0], None)
        self.assertTrue(self.labels()[-1].startswith(roles.STOPPED + roles.SEP), self.labels())

    def test_a_reparented_child_with_its_marks_holds_the_stop(self):
        executor = Dummy(self, 'executor', 'e', ['(setsid sleep 7302 &)'])
        orphan, = executor.orphans
        block, out = executor.stop()
        self.assertIsNotNone(block, out)
        self.assertIn(f'{orphan} · ', block['reason'])

    def test_a_user_wide_daemon_it_started_does_not_hold_the_stop(self):
        # the rootless podman pause process shows as "catatonit -P": every rootless container of the user runs under it
        executor = Dummy(self, 'executor', 'e', ['exec -a catatonit sleep 7313', 'sleep 7314'])
        deadline, daemon = time.time() + 5, []
        while time.time() < deadline and not daemon:  # the subshell execs it a moment after it is up
            procs = roles.processes()
            daemon = [k for k in executor.kids if procs.get(k, (0, []))[1] == ['catatonit', '7313']]
        daemon, = daemon
        block, out = executor.stop()
        self.assertIsNotNone(block, out)
        self.assertIn('sleep 7314', block['reason'])
        self.assertNotIn(f'{daemon} · ', block['reason'])

    def test_stop_hook_active_passes_and_the_executor_wakes_with_the_list(self):
        executor = Dummy(self, 'executor', 'e', ['sleep 7303'])
        block, out = executor.stop(stop_hook_active = True, background_tasks = [{'type': 'subagent', 'description': 'Build X'}])
        self.assertIsNone(block, out)
        label = self.labels()[-1]
        self.assertTrue(label.startswith(roles.STOPPED_BACKGROUND + roles.SEP), label)
        self.assertIn('subagent · Build X', label)
        self.assertIn(f'{executor.kids[0]} · ', label)

    def test_background_tasks_alone_hold_the_stop(self):
        executor = Dummy(self, 'executor', 'e')
        block, out = executor.stop(background_tasks = [{'type': 'shell', 'description': 'npm run dev'}])
        self.assertIn('shell · npm run dev', (block or {}).get('reason', ''), out)

    def test_an_observer_is_held_by_its_own_child_not_by_its_executors(self):
        observer = Dummy(self, 'observer', 'o')  # first: its executor's processes are younger, only their marks are not its
        executor = Dummy(self, 'executor', 'e', ['sleep 7304', '(setsid sleep 7305 &)'])
        self.assertIsNotNone(executor.stop()[0])
        block, out = observer.stop()
        self.assertIsNone(block, out)
        own = Dummy(self, 'observer', 'o2', ['sleep 7306'])
        block, out = own.stop()
        self.assertIn(f'{own.kids[0]} · ', (block or {}).get('reason', ''), out)
        self.assertNotIn('7304', block['reason'])
        self.assertTrue(block['reason'].endswith('\n' + roles.OPERATOR_LANGUAGE), 'an observer text ends with the language line')

    def test_harness_children_and_a_clean_tree_do_not_hold(self):
        executor = Dummy(self, 'executor', 'e', mcp = ['sleep 7307'])  # a direct child, not a Bash-tool shell: an MCP server
        deadline, procs = time.time() + 5, {}
        while time.time() < deadline and ['sleep', '7307'] not in [argv for _, argv in procs.values()]:
            time.sleep(0.05)
            procs = roles.processes()
        server, = [p for p, (ppid, argv) in procs.items() if argv == ['sleep', '7307']]
        self.assertTrue(roles.descends(server, executor.proc.pid, procs) and procs[server][0] != executor.proc.pid,
                        'the server has a child of its own')
        self.assertIsNone(executor.stop()[0])

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
        block, out = executor.stop()
        self.assertIsNone(block, out)

    def test_a_subagent_stop_is_untouched(self):
        executor = Dummy(self, 'executor', 'e', ['sleep 7308'])
        block, out = executor.stop(hook_event_name = 'SubagentStop', agent_id = 'a1')
        self.assertIsNone(block, out)

    def test_a_failing_scan_lets_the_stop_pass_and_logs_its_trace(self):
        hook, broken = os.path.join(KIT, 'hooks/role-state.py'), os.path.join(self.home, 'broken.py')
        with open(broken, 'w') as f:  # the real hook with a process scan that raises
            f.write(f'import sys; sys.path.insert(0, {os.path.join(KIT, "tools")!r}); import roles\n'
                    'def boom(*a): raise RuntimeError("scan broke")\nroles.leftovers = boom\n'
                    f'exec(compile(open({hook!r}).read(), {hook!r}, "exec"))\n')
        executor = Dummy(self, 'executor', 'e', ['sleep 7309'], hook = broken)
        block, out = executor.stop()
        self.assertIsNone(block, out)
        with open(os.path.join(self.home, 'logs', 'leftover-guard.log')) as f:
            self.assertIn('scan broke', f.read())

    def test_the_scan_is_cheap(self):
        executor = Dummy(self, 'executor', 'e', ['sleep 7311'])
        began = time.time()
        executor.stop()
        took = time.time() - began
        print(f'\nStop hook with the guard: {took * 1000:.0f} ms', file = sys.stderr)
        self.assertLess(took, 1.0)


class StopWakes(Case):
    """The label a passed stop writes, read by the real waiter scan."""
    def wakes(self, label):
        pane = {'pane_id': '%7', 'session_name': 's', 'pane_pid': '90', 'pane_current_command': 'claude',
                '@claude_role': 'executor', '@claude_name': 'e', '@claude_observer': 'me', '@claude_state': label,
                '@claude_seen': '', '@claude_flags': '', roles.PID_LABEL: '100'}
        return waiter.attention('me', [pane], {100: (90, ['claude']), 90: (1, ['zsh'])}, time.time(), {}, 0)

    def test_a_stop_with_background_wakes_the_observer_and_names_it(self):
        executor = Dummy(self, 'executor', 'e')
        executor.stop(stop_hook_active = True, background_tasks = [{'type': 'subagent', 'description': 'Build X'}])
        found = self.wakes(self.labels()[-1])
        self.assertEqual(len(found), 1, self.labels())
        self.assertIn('subagent · Build X', found[0][3])

    def test_a_stop_without_background_wakes_as_before(self):
        executor = Dummy(self, 'executor', 'e')
        executor.stop(last_assistant_message = 'all done')
        found = self.wakes(self.labels()[-1])
        self.assertEqual(len(found), 1, self.labels())
        self.assertIn('stopped · ', found[0][3])
        self.assertIn('all done', found[0][3])


if __name__ == '__main__':
    unittest.main()
