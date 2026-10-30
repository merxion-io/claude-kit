#!/usr/bin/env python3
# The write guard and the skill gates: python3 tools/test_write_guard.py. Events go through the real hook, hooks/role-state.py
# main(), in-process; tmux and the roster are stubbed, git and the temp repositories are real.
import contextlib, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(KIT, 'tools'))
sys.dont_write_bytecode = True
os.environ['CLAUDE_ROLES_STATE_DIR'] = tempfile.mkdtemp()
import roles

spec = importlib.util.spec_from_file_location('role_state', os.path.join(KIT, 'hooks', 'role-state.py'))
role_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(role_state)

STUBS = ('set_pane_option', 'unset_pane_option', 'label_pane', 'write_state', 'state_lock', 'revive_observer',
         'update_roster', 'find_pane', 'sync_remote_control', 'pult_journal', 'role_pid')


def git(cwd, *args):
    subprocess.run(['git', '-C', cwd, '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check = True, capture_output = True)


def temp_repo():
    top = os.path.realpath(tempfile.mkdtemp())
    git(top, 'init', '-q')
    with open(os.path.join(top, '.gitignore'), 'w') as f:
        f.write('build/\n')
    os.makedirs(os.path.join(top, 'tui', 'scripts'))
    for path in ('install.sh', 'tui/scripts/vps.sh', 'notes.md'):
        with open(os.path.join(top, path), 'w') as f:
            f.write('old\n')
    git(top, 'add', '.')
    git(top, 'commit', '-qm', 'init')
    return top


class Session:
    """One executor (or other role) in a folder, driven through the hook."""
    count = 0

    def __init__(self, cwd, role = 'executor'):
        Session.count += 1
        self.cwd, self.role, self.name, self.ids = cwd, role, f's{Session.count}', 0

    def hook(self, **ev):
        out = io.TextIOWrapper(io.BytesIO(), encoding = 'utf-8')  # strict, as the real stdout of the hook
        env = {'CLAUDE_ROLE_NAME': self.name, 'TMUX_PANE': '%1'}
        with mock.patch.dict(os.environ, env), mock.patch.object(roles, 'role_session', lambda: self.role), \
                mock.patch.object(roles, 'pane_option', lambda *a: ''), \
                mock.patch.multiple(roles, **{s: mock.MagicMock() for s in STUBS}), \
                mock.patch.object(sys, 'stdin', io.StringIO(json.dumps({'cwd': self.cwd, 'session_id': 'x', **ev}))), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            for launched in (roles.ROLE_OBSERVER, roles.ROLE_FLAGS, roles.ROLE_PROJECT, roles.ROLE_PID):
                os.environ.pop(launched, None)  # the run may itself sit inside a role session: no real pult, no foreign state dir
            role_state.main()
        out.flush()
        lines = [json.loads(line)['hookSpecificOutput'] for line in out.buffer.getvalue().decode().splitlines()]
        return lines[0] if lines else None

    def start(self, source = 'startup'):
        return self.hook(hook_event_name = 'SessionStart', source = source)

    def load(self, skill):
        return self.hook(hook_event_name = 'PostToolUse', tool_name = 'Skill', tool_input = {'skill': skill})

    def write(self, path, tool = 'Write', **ev):
        return self.hook(hook_event_name = 'PreToolUse', tool_name = tool, tool_input = {'file_path': path}, **ev)

    def pre_bash(self, command, tool_id = 't', **inp):
        return self.hook(hook_event_name = 'PreToolUse', tool_name = 'Bash', tool_use_id = tool_id,
                         tool_input = {'command': command, **inp})

    def post_bash(self, command, tool_id = 't', event = 'PostToolUse'):
        return self.hook(hook_event_name = event, tool_name = 'Bash', tool_use_id = tool_id, tool_input = {'command': command})

    def bash(self, command, cwd = None):
        """The whole call: PreToolUse; if not denied the command really runs; then Post or Failure by its exit code."""
        self.ids += 1
        tool_id = f'toolu_{self.ids}'
        said = self.pre_bash(command, tool_id)
        if said:
            return said
        done = subprocess.run(['bash', '-c', command], cwd = cwd or self.cwd, capture_output = True)
        return self.post_bash(command, tool_id, 'PostToolUse' if done.returncode == 0 else 'PostToolUseFailure')


class Base(unittest.TestCase):
    def setUp(self):
        self.top = temp_repo()
        self.e = Session(self.top)
        self.e.start()

    def path(self, rel):
        return os.path.join(self.top, rel)

    def read(self, rel):
        with open(self.path(rel)) as f:
            return f.read()

    def assertDenied(self, said, names = None):
        self.assertEqual((said or {}).get('permissionDecision'), 'deny', said)
        if names:
            self.assertIn(names, said['permissionDecisionReason'])

    def assertReported(self, said, name):
        self.assertIn(name, (said or {}).get('additionalContext', ''), said)
        self.assertIn('builder', said['additionalContext'])


class Layer1(Base):
    def test_case_a_write_tool_from_the_repo_root(self):
        said = self.e.write(self.path('tui/scripts/vps.sh'))
        self.assertDenied(said, 'vps.sh')
        self.assertIn('builder', said['permissionDecisionReason'])
        self.assertIn('`orchestration`', said['permissionDecisionReason'])

    def test_case_a_bash_from_the_repo_root_writes_nothing(self):
        self.assertDenied(self.e.bash('echo x > tui/scripts/vps.sh'), 'tui/scripts/vps.sh')
        self.assertEqual(self.read('tui/scripts/vps.sh'), 'old\n')

    def test_root_install_sh(self):
        self.assertDenied(self.e.write(self.path('install.sh'), tool = 'Edit'), 'install.sh')
        self.assertDenied(self.e.bash('echo x >> install.sh'))

    def test_notebook_and_new_file_in_a_new_folder(self):
        self.assertDenied(self.e.hook(hook_event_name = 'PreToolUse', tool_name = 'NotebookEdit',
                                      tool_input = {'notebook_path': self.path('new/deep/a.ipynb')}))
        self.assertDenied(self.e.write(self.path('new/deep/a.py')))

    def test_open_list(self):
        for rel in ('notes.md', 'new/deep/tasks.md', '.claude/checkpoints/c.json'):
            with self.subTest(rel = rel):
                self.assertIsNone(self.e.write(self.path(rel)))
                self.assertIsNone(self.e.pre_bash(f'echo x > {rel}'))

    def test_the_project_table_adds_open_paths(self):
        rel = 'specs-folder/a.yaml'
        self.assertDenied(self.e.write(self.path(rel)))
        os.makedirs(self.path('.claude'))
        with open(self.path('.claude/kit-gates.json'), 'w') as f:
            json.dump({'open': ['specs-folder/']}, f)
        for place in (rel, 'x/y/specs-folder/b.yaml'):
            with self.subTest(place = place):
                self.assertIsNone(self.e.write(self.path(place)))
                self.assertIsNone(self.e.pre_bash(f'mkdir -p {os.path.dirname(place)}; echo x > {place}'))
        self.assertDenied(self.e.write(self.path('install.sh')))
        self.assertIsNone(self.e.bash('mkdir -p specs-folder; echo y > specs-folder/c.yaml'))

    def test_outside_a_repo_open(self):
        out = os.path.realpath(tempfile.mkdtemp())
        self.assertIsNone(self.e.write(os.path.join(out, 'a.py')))
        self.assertIsNone(self.e.bash(f'echo x > {out}/a.py'))
        self.assertIsNone(self.e.write('/nonexistent/place/a.py'))

    def test_boundary_is_the_target_repo_not_cwd(self):
        outside = Session(os.path.realpath(tempfile.mkdtemp()))
        self.assertDenied(outside.write(self.path('install.sh')))
        self.assertDenied(outside.bash(f'echo x > {self.path("install.sh")}'))
        other = temp_repo()
        self.assertDenied(self.e.write(os.path.join(other, 'install.sh')))

    def test_from_a_subfolder(self):
        sub = Session(self.path('tui'))
        self.assertDenied(sub.bash('echo x > scripts/vps.sh'), 'scripts/vps.sh')
        self.assertDenied(sub.write(self.path('tui/scripts/vps.sh')))
        self.assertIsNone(sub.pre_bash('echo x > ../notes.md'))

    def test_bash_writers_denied(self):
        for command in ('cp a install.sh', 'cp a b 2>/dev/null; mv c install.sh', 'install -m 755 a tui/x', 'rsync -a a tui/',
                        'cat a | tee -a install.sh', 'sed -i "s/a/b/" install.sh', "sed -i '' -e 's/a/b/' install.sh",
                        "perl -pi -e 's/a/b/' install.sh", 'git apply x.patch', 'git -C tui apply x.patch', 'patch -p1 < x',
                        "python3 -c \"open('new.py', 'w').write('x')\"", "python3 -c \"from pathlib import Path; Path('n.py').write_text('x')\"",
                        "python3 -c \"import shutil; shutil.copy('/tmp/a', 'n.py')\"", "python3 -c \"import os; os.replace('/tmp/a', 'n.py')\"",
                        "python3 - <<'EOF'\nopen('n.py', 'a')\nEOF", "node -e \"require('fs').writeFileSync('n.js', 'x')\"",
                        "cat > n.py <<'EOF'\nx\nEOF", 'timeout 30 sed -i s/a/b/ install.sh', "bash -c 'echo x > n.py'",
                        '(echo x)>n.py', '# note\necho x > n.py', 'mv a b\nmv c n.py', 'cp -t tui a', 'ssh h cmd > n.py'):
            with self.subTest(command = command):
                self.assertDenied(self.e.pre_bash(command))

    def test_bash_not_writes_open(self):
        for command in ("python3 -c \"open('/tmp/x', 'w').write('a')\"", "python3 -c \"print(open('notes.md').read())\"",
                        "python3 -c \"print('w', 'a.py')\"", "grep '>' install.sh", 'grep ">" install.sh | head -3', 'sed -n 1,5p install.sh',
                        "sed -i 's/a/b/' notes.md", "sed -i '' 's/a/b/' /tmp/x.py", 'echo x > /dev/null', 'ls 2>&1 >/dev/null',
                        'cat install.sh > /dev/stderr', 'cd /tmp && echo x > f', '(cd /tmp && echo x > f)', 'cd /tmp; cp a b',
                        'cd "$X" && echo x > f', 'echo x > "$OUT"', 'rsync -a a host:/srv/app/', 'git apply --check x.patch',
                        '# echo x > install.sh', "python3 script.py <<'EOF'\nopen('n.py', 'w')\nEOF", 'python3 -m pytest tests/'):
            with self.subTest(command = command):
                self.assertIsNone(self.e.pre_bash(command))

    def test_comparisons_are_not_redirects(self):
        for command in ('(( x > 3 )) && echo y', 'if (( n > 0 )); then echo y; fi', '[[ a > b ]] && echo y', 'echo $(( 3 > 2 ))',
                        'for ((i=0;i>3;i++)); do echo $i; done', '(( $(wc -l < a) > 3 )) && echo y', 'if (( (1+2) > 3 )); then echo y; fi',
                        'n=$(( $(wc -l < a) > 3 ))', '[[ $(cat a) > b ]] && echo y', '[[ a =~ (b|c) ]] && echo y'):
            with self.subTest(command = command):
                self.assertIsNone(self.e.pre_bash(command))
        for command in ('(( x > 3 )) && echo y > n.py', '[[ a > b ]] > n.py', '((echo x); (echo y)) > n.py', '((echo x); (echo y > n.py))'):
            with self.subTest(command = command):
                self.assertDenied(self.e.pre_bash(command), 'n.py')

    def test_a_comparison_hides_no_write(self):
        for command in ("echo '[[ ' > n.py; echo ' ]]'", 'grep "[[ " a > n.py && grep " ]]" b', '[[ -n $(echo x > n.py) ]]'):
            with self.subTest(command = command):
                self.assertDenied(self.e.pre_bash(command), 'n.py')
        for command in ('[[ $(cp a n.py) == b ]]', '(( $(cp a n.py) > 3 ))', '(( $(echo x > n.py) > 3 ))', '[[ $(echo x > n.py) > b ]]',
                        '[[ $(cd /tmp) > b ]]; echo x > n.py', '(( $(cat a) > 3 )) > n.py', '[[ $(echo $(echo x > n.py)) > b ]]', '[[ $(echo x > n.py $(echo y)) > b ]]'):
            with self.subTest(command = command):
                self.assertDenied(self.e.pre_bash(command), 'n.py')
        self.assertIsNone(self.e.pre_bash('echo "[[ a > b ]]"'))

    def test_every_in_place_spelling_denied(self):
        for command in ("perl -0pi -e 's/a/b/' install.sh", "sed -I '' s/a/b/ install.sh", 'sed -I.bak s/a/b/ install.sh'):
            with self.subTest(command = command):
                self.assertDenied(self.e.pre_bash(command), 'install.sh')

    def test_perl_switches_with_an_i_are_not_in_place(self):
        for command in ("perl -Mstrict -ne 'print if /x/' install.sh", "perl -Ilib -ne 'print' install.sh",
                        "perl -MList::Util=sum -e 'print 1' install.sh"):
            with self.subTest(command = command):
                self.assertIsNone(self.e.pre_bash(command))
        self.assertDenied(self.e.pre_bash("perl -Mstrict -i -pe 's/a/b/' install.sh"), 'install.sh')

    def test_pushd_and_popd_are_followed(self):
        self.assertIsNone(self.e.pre_bash('pushd /tmp && echo x > f && popd'))
        self.assertDenied(self.e.pre_bash('pushd /tmp && popd && echo x > f'), 'f')
        self.assertDenied(self.e.pre_bash('pushd tui && echo x > f'), 'f')

    def test_a_subshell_keeps_the_directory_stack_apart(self):
        for command in ('(pushd /tmp; pushd /var); echo x > n.py', '(cd /tmp; pushd /var); echo x > n.py',
                        'pushd /tmp && (popd; echo x > n.py)', 'popd; echo x > n.py'):
            with self.subTest(command = command):
                self.assertDenied(self.e.pre_bash(command), 'n.py')
        self.assertIsNone(self.e.pre_bash('pushd /tmp && (popd); echo x > n.py'))

    def test_patch_directory_in_every_spelling(self):
        for spelled in (f'--directory {self.top}', f'-d{self.top}', f'-d {self.top}', f'--directory={self.top}'):
            with self.subTest(spelled = spelled):
                self.assertDenied(self.e.pre_bash(f'cd /tmp && patch {spelled} -p1 < x'), 'patch')
        for spelled in ('--directory /tmp', '-d/tmp'):
            with self.subTest(spelled = spelled):
                self.assertIsNone(self.e.pre_bash(f'patch {spelled} -p1 < x'))

    def test_patch_dry_run_and_elsewhere_open(self):
        for command in ('patch --dry-run -p1 < x', 'patch -d /tmp -p1 < x', 'patch --directory=/tmp < x'):
            with self.subTest(command = command):
                self.assertIsNone(self.e.pre_bash(command))
        self.assertDenied(self.e.pre_bash('patch -d tui -p1 < x'), 'patch')

    def test_copy_into_a_folder_judged_by_the_file(self):
        for command in ('mv a.md tui/', 'cp notes.md tui/', 'cp a.md b.md new/'):
            with self.subTest(command = command):
                self.assertIsNone(self.e.pre_bash(command))
        for command in ('mv a.py tui/', 'cp a.md b.py tui/', 'cp "$f" tui/'):
            with self.subTest(command = command):
                self.assertDenied(self.e.pre_bash(command), 'tui/')

    def test_cd_is_followed_and_ends_with_its_subshell(self):
        self.assertDenied(self.e.pre_bash('cd tui && echo x > f'), 'f')
        self.assertDenied(self.e.pre_bash('(cd /tmp && echo x > f); echo y > g'), 'g')
        self.assertDenied(self.e.pre_bash(f'cd /tmp && echo x > {self.path("f")}'))
        self.assertIsNone(self.e.pre_bash('cd tui && echo x > a.md'))
        self.assertIsNone(self.e.pre_bash('git -C /tmp apply x.patch'))

    def test_git_itself_open(self):
        for command in ('git merge dev', 'git cherry-pick a', 'git commit -m "a > install.sh"', 'git rebase main', 'git checkout -- install.sh',
                        'git push origin main', 'git stash', 'git -C tui merge dev', "git commit -m \"$(cat <<'EOF'\nx > install.sh\nEOF\n)\""):
            with self.subTest(command = command):
                self.assertIsNone(self.e.pre_bash(command))

    def test_redirect_of_git_is_a_write(self):
        self.assertDenied(self.e.pre_bash('git show HEAD:install.sh > n.sh'))

    def test_ssh_inside_open_local_redirect_not(self):
        self.assertIsNone(self.e.bash("ssh -o ConnectTimeout=1 nonexistent.invalid 'echo x > f'"))
        self.assertIsNone(self.e.pre_bash("ssh h <<'EOF'\necho x > install.sh\nEOF"))
        self.assertDenied(self.e.pre_bash('ssh h cmd > f'))

    def test_builder_write_open(self):
        self.assertIsNone(self.e.write(self.path('install.sh'), agent_id = 'builder-1'))
        self.assertIsNone(self.e.hook(hook_event_name = 'PreToolUse', tool_name = 'Bash', agent_id = 'builder-1',
                                      tool_input = {'command': 'echo x > install.sh'}))

    def test_observer_and_role_less_untouched(self):
        for role in ('observer', None):
            with self.subTest(role = role):
                s = Session(self.top, role)
                self.assertIsNone(s.write(self.path('install.sh')))
                self.assertIsNone(s.pre_bash('echo x > install.sh'))

    def test_role_less_as_a_real_process(self):
        env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_ROLE', 'TMUX_PANE')}
        ev = {'hook_event_name': 'PreToolUse', 'tool_name': 'Write', 'cwd': self.top, 'tool_input': {'file_path': self.path('install.sh')}}
        done = subprocess.run([sys.executable, os.path.join(KIT, 'hooks', 'role-state.py')], input = json.dumps(ev), text = True,
                              capture_output = True, env = env)
        self.assertEqual((done.returncode, done.stdout), (0, ''))

    def test_git_failure_means_open(self):
        with mock.patch.dict(os.environ, {'PATH': '/nonexistent'}):
            self.assertIsNone(self.e.write(self.path('install.sh')))
            self.assertIsNone(self.e.pre_bash('python3 s.py'))
            self.assertIsNone(self.e.post_bash('python3 s.py'))


class Layer2(Base):
    SCRIPT = "with open('install.sh', 'a') as f: f.write('x')\n"

    def setUp(self):
        super().setUp()
        self.script = os.path.join(tempfile.mkdtemp(), 's.py')
        with open(self.script, 'w') as f:
            f.write(self.SCRIPT)

    def snapshots(self):
        place = os.path.join(roles.STATE_DIR, f'write-guard--{self.e.name}')  # the stubbed pane has no observer
        return [f for f in os.listdir(place) if f.startswith('before-')] if os.path.isdir(place) else []

    def test_python_script_writing_a_tracked_file_reported_never_reverted(self):
        said = self.e.bash(f'python3 {self.script}')
        self.assertReported(said, 'install.sh')
        self.assertEqual(said['hookEventName'], 'PostToolUse')
        self.assertEqual(self.read('install.sh'), 'old\nx')
        self.assertEqual(self.snapshots(), [])

    def test_failing_command_reported_and_snapshot_dropped(self):
        said = self.e.bash(f'python3 {self.script}; exit 3')
        self.assertReported(said, 'install.sh')
        self.assertEqual(said['hookEventName'], 'PostToolUseFailure')
        self.assertEqual(self.snapshots(), [])

    def test_a_dirty_file_changed_again_reported(self):
        with open(self.path('install.sh'), 'a') as f:
            f.write('dirty')
        self.assertReported(self.e.bash(f'python3 {self.script}'), 'install.sh')

    def test_an_already_dirty_file_unchanged_not_reported(self):
        with open(self.path('install.sh'), 'a') as f:
            f.write('dirty')
        self.assertIsNone(self.e.bash('true'))

    def test_new_file_in_a_new_folder_reported(self):
        self.assertReported(self.e.bash('v=new/a.py; mkdir -p new; : > "$v"'), 'new/a.py')

    def test_only_open_or_ignored_files_not_reported(self):
        self.assertIsNone(self.e.bash('v=notes.md; echo x >> "$v"; v=build/out.log; mkdir -p build; echo x > "$v"'))

    def test_tests_producing_ignored_files_not_reported(self):
        self.assertIsNone(self.e.bash('mkdir -p build/cache && python3 -c "import sys" && cd build/cache && touch a.pyc'))

    def test_git_command_not_reported(self):
        git(self.top, 'checkout', '-qb', 'dev')
        with open(self.path('install.sh'), 'a') as f:
            f.write('dev')
        git(self.top, 'commit', '-qam', 'dev')
        git(self.top, 'checkout', '-q', '-')
        env = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
        with mock.patch.dict(os.environ, env):
            self.assertIsNone(self.e.bash('git merge -q dev | tail -3'))
        self.assertIn('dev', self.read('install.sh'))

    def test_git_changing_a_dirty_file_beside_a_read_not_reported(self):
        env = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
        with mock.patch.dict(os.environ, env):
            for command in ('git stash -q && ls', 'git stash pop -q | cat', 'git checkout -- install.sh; pwd'):
                with self.subTest(command = command):
                    if 'pop' not in command:
                        with open(self.path('install.sh'), 'a') as f:
                            f.write('dirty')
                    self.assertIsNone(self.e.bash(command))

    def test_a_turn_end_leaves_no_snapshot(self):
        for event in ({'hook_event_name': 'Stop'}, {'hook_event_name': 'SessionStart', 'source': 'compact'}, {'hook_event_name': 'SessionEnd'}):
            with self.subTest(event = event):
                self.e.pre_bash('true', 'lost')
                self.assertEqual(len(self.snapshots()), 1)
                self.e.hook(**event)
                self.assertEqual(self.snapshots(), [])

    def test_git_beside_another_command_is_not_a_git_command(self):
        self.assertReported(self.e.bash(f'git add notes.md && python3 {self.script}'), 'install.sh')
        for command in (f'git add notes.md && [[ $(python3 {self.script}) == ok ]]', f'git add notes.md && echo `python3 {self.script}`',
                        f'git add notes.md && echo "$(python3 {self.script})"', f'git log -1 "$(true; python3 {self.script})"',
                        f'git add notes.md && (( $(python3 {self.script}) > 3 ))', 'git status; sort -o install.sh install.sh notes.md',
                        'git log -1 | uniq - install.sh'):
            with self.subTest(command = command):
                self.assertReported(self.e.bash(command), 'install.sh')
                git(self.top, 'checkout', '--', 'install.sh')

    def test_skipped_while_a_subagent_runs(self):
        self.e.hook(hook_event_name = 'SubagentStart', agent_id = 'a1', agent_type = 'builder')
        self.assertIsNone(self.e.bash(f'python3 {self.script}'))
        self.e.hook(hook_event_name = 'SubagentStop', agent_id = 'a1', agent_type = 'builder')
        self.assertReported(self.e.bash(f'python3 {self.script}'), 'install.sh')

    def test_a_subagent_tool_event_alone_marks_it_running(self):
        self.e.write(self.path('a.py'), agent_id = 'a2')
        self.assertIsNone(self.e.bash(f'python3 {self.script}'))

    def test_a_subagent_starting_during_the_call_skips_it(self):
        self.e.pre_bash(f'python3 {self.script}', 'mid')
        self.e.hook(hook_event_name = 'SubagentStart', agent_id = 'a3', agent_type = 'builder')
        self.e.hook(hook_event_name = 'SubagentStop', agent_id = 'a3', agent_type = 'builder')
        subprocess.run(['python3', self.script], cwd = self.top)
        self.assertIsNone(self.e.post_bash('python3 s.py', 'mid'))

    def test_stop_keeps_a_background_subagent_and_clears_otherwise(self):
        self.e.hook(hook_event_name = 'SubagentStart', agent_id = 'a4', agent_type = 'builder')
        self.e.hook(hook_event_name = 'Stop', background_tasks = [{'type': 'subagent', 'description': 'b'}])
        self.assertIsNone(self.e.bash(f'python3 {self.script}'))
        self.e.hook(hook_event_name = 'Stop', background_tasks = [{'type': 'shell', 'description': 'b'}])
        self.assertReported(self.e.bash(f'python3 {self.script}'), 'install.sh')

    def test_parallel_calls_keep_their_own_snapshots(self):
        self.e.pre_bash('true', 'one')
        subprocess.run(['python3', self.script], cwd = self.top)
        self.e.pre_bash('true', 'two')
        self.assertIsNone(self.e.post_bash('true', 'two'))
        self.assertReported(self.e.post_bash('true', 'one'), 'install.sh')

    def test_outside_a_repo_and_background_skipped(self):
        outside = Session(os.path.realpath(tempfile.mkdtemp()))
        self.assertIsNone(outside.bash(f'python3 -c "open(\'{self.path("install.sh")}\'[:0] or \'a\', \'w\')"'))
        self.e.pre_bash(f'python3 {self.script}', 'bg', run_in_background = True)
        subprocess.run(['python3', self.script], cwd = self.top)
        self.assertIsNone(self.e.post_bash('x', 'bg'))

    def test_a_cd_during_the_session_compares_the_repo_of_the_call(self):
        self.e.pre_bash('true', 'c')
        subprocess.run(['python3', self.script], cwd = self.top)
        moved = Session(os.path.realpath(tempfile.mkdtemp()))
        moved.name = self.e.name
        self.assertReported(moved.post_bash('true', 'c'), 'install.sh')

    def test_a_status_entry_with_a_space_and_a_rename(self):
        git(self.top, 'mv', 'notes.md', 'a b.txt')
        self.assertIsNone(self.e.bash('true'))
        self.assertReported(self.e.bash('v="a b.txt"; echo x >> "$v"'), 'a b.txt')


class GuardFailure(Base):
    def test_a_broken_table_is_open_and_the_write_guard_still_holds(self):
        os.makedirs(self.path('.claude'))
        for table in ('[]', '"x"', '{"gates": ["x"]}', '{"gates": {"a": 1}}', '{"gates": [{"bash": "(", "skills": ["x"]}]}'):
            with self.subTest(table = table):
                with open(self.path('.claude/kit-gates.json'), 'w') as f:
                    f.write(table)
                self.assertIsNone(self.e.pre_bash('ls'))
                self.assertDenied(self.e.write(self.path('install.sh')), 'install.sh')

    def test_a_name_not_in_utf8_reaches_the_feedback(self):
        place = tempfile.mkdtemp()
        real = shutil.which('git')
        with open(os.path.join(place, 'git'), 'w') as f:  # APFS refuses such names: git says it, the file is not needed
            f.write(f'#!/bin/sh\nfor a in "$@"; do [ "$a" = status ] && {{ [ -f {place}/on ] && printf \'?? bad\\377.py\\0\'; exit 0; }}; done\nexec {real} "$@"\n')
        os.chmod(os.path.join(place, 'git'), 0o755)
        with mock.patch.dict(os.environ, {'PATH': f'{place}:{os.environ["PATH"]}'}):
            self.e.pre_bash('python3 x.py', 'u')
            open(os.path.join(place, 'on'), 'w').close()
            self.assertReported(self.e.post_bash('python3 x.py', 'u'), 'bad')


class SkillGates(Base):
    TABLE = {'gates': [{'action': 'git commit', 'bash': r'\bgit\s+commit\b', 'skills': ['facts']},
                       {'action': 'an agent', 'tool': ['Agent'], 'skills': ['orchestration']},
                       {'action': 'a write under spec', 'write': ['specs-folder'], 'skills': ['spec-change']}]}

    def setUp(self):
        super().setUp()
        os.makedirs(self.path('.claude'))
        with open(self.path('.claude/kit-gates.json'), 'w') as f:
            json.dump(self.TABLE, f)

    def agent(self, **ev):
        return self.e.hook(hook_event_name = 'PreToolUse', tool_name = 'Agent', tool_input = {}, **ev)

    def test_gate_denies_until_the_skill_is_loaded(self):
        self.assertDenied(self.e.pre_bash('git commit -m x'), '`facts`')
        self.e.load('facts')
        self.assertIsNone(self.e.pre_bash('git commit -m x'))

    def test_quoted_text_does_not_hit_a_bash_gate(self):
        self.assertIsNone(self.e.pre_bash('echo "git commit"'))

    def test_tool_gate_and_typed_slash_command(self):
        self.assertDenied(self.agent(), '`orchestration`')
        self.e.hook(hook_event_name = 'UserPromptSubmit', prompt = '/orchestration go')
        self.assertIsNone(self.agent())

    def test_write_gate_relative_to_cwd(self):
        self.assertDenied(self.e.write(self.path('specs-folder/a.md')), '`spec-change`')
        self.assertDenied(self.e.pre_bash('echo x > specs-folder/a.md'), '`spec-change`')
        self.assertIsNone(self.e.write(self.path('notes.md')))
        self.e.load('spec-change')
        self.assertIsNone(self.e.write(self.path('specs-folder/a.md')))

    def test_gates_survive_compaction_and_clear_resets(self):
        self.e.load('facts')
        for source in ('compact', 'resume'):
            self.e.start(source)
            self.assertIsNone(self.e.pre_bash('git commit -m x'))
        self.e.start('clear')
        self.assertDenied(self.e.pre_bash('git commit -m x'))

    def test_table_found_from_a_subfolder_none_outside(self):
        self.assertDenied(Session(self.path('tui')).pre_bash('git commit -m x'))
        self.assertIsNone(Session(os.path.realpath(tempfile.mkdtemp())).pre_bash('git commit -m x'))

    def test_subagent_and_observer_not_gated(self):
        self.assertIsNone(self.agent(agent_id = 'b'))
        self.assertIsNone(Session(self.top, 'observer').pre_bash('git commit -m x'))

    def test_a_denied_call_leaves_no_snapshot_to_report(self):
        self.e.pre_bash('git commit -m x; python3 s.py', 'g')
        with open(self.path('install.sh'), 'a') as f:
            f.write('x')
        self.assertIsNone(self.e.post_bash('x', 'g'))


if __name__ == '__main__':
    unittest.main()
