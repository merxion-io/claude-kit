#!/usr/bin/env python3
# The kit's self-check over the real tree and over a small invented kit: python3 tools/test_kit_check.py
import json, os, shutil, subprocess, sys, tempfile, time, unittest

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(KIT, 'tools'))
import kit_check
import roles

# Dead hooks a later change deletes; that change empties this and then removes it.
EXPECTED_DEAD = ['hooks/watch-ensure.sh', 'hooks/context-guard.sh']
LIVE = 'bash "$HOME/.claude/hooks/live.sh"'
FOREIGN = 'python3 /opt/my/own-hook.py'


def hooks_of(*commands):
    return {'Stop': [{'hooks': [{'type': 'command', 'command': c} for c in commands]}]}


class Tree(unittest.TestCase):
    def test_the_kit_agrees_with_itself(self):
        found = [what for what, _ in kit_check.tree_findings(KIT, tempfile.gettempdir())]
        self.assertEqual(sorted(w.split(':')[0] for w in found), sorted(EXPECTED_DEAD), found)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cwd = os.path.join(self.root, 'project')
        os.makedirs(self.cwd)
        self.write('agents/a.md', '---\nname: a\nskills:\n  - known\nmodel: opus\n---\nbody\n')
        self.write('skills/known/SKILL.md', 'x\n')
        for name in roles.OBSERVER_SKILLS:
            self.write(f'skills/{name}/SKILL.md', 'x\n')
        for role in roles.ROLE_NAMES:
            self.write(f'roles/{role}.md', 'x\n')
        self.write('hooks/live.sh', 'bash "$(dirname "$0")/helper.sh"\n')
        self.write('hooks/helper.sh', 'true\n')
        self.settings('settings.base.json', hooks = hooks_of(LIVE))
        self.settings('settings.json', hooks = hooks_of(LIVE))
        self.git('init', '-q')
        self.git('add', 'agents', 'skills', 'hooks', 'settings.base.json')

    def git(self, *args):
        subprocess.run(['git', '-C', self.root, *args], check = True, capture_output = True)

    def write(self, path, text):
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok = True)
        with open(full, 'w', encoding = 'utf-8') as f:
            f.write(text)

    def settings(self, name, **values):
        self.write(name, json.dumps(values))

    def found(self):
        return [what for what, _ in kit_check.findings(self.root, self.cwd)]

    def test_a_clean_kit_has_no_findings(self):
        self.assertEqual(self.found(), [])

    def test_an_agent_names_a_missing_skill(self):
        for head in ('skills:\n  - known\n  - gone', 'skills: [known, gone]', 'skills: gone'):
            with self.subTest(head = head):
                self.write('agents/a.md', f'---\nname: a\n{head}\nmodel: opus\n---\n')
                self.assertEqual(self.found(), ['agents/a.md names skill gone: not under skills/'])

    def test_skills_in_the_body_of_an_agent_are_no_names(self):
        self.write('agents/a.md', '---\nname: a\n---\nskills: [gone]\n')
        self.assertEqual(self.found(), [])

    def gates(self, text):
        self.write('project/.claude/kit-gates.json', text)

    def test_a_gate_table_names_kit_project_and_missing_skills(self):
        self.write('project/.claude/skills/own/SKILL.md', 'x\n')
        self.gates(json.dumps({'gates': [{'skills': ['known', 'own']}, {'skills': ['gone']}]}))
        found = self.found()
        self.assertEqual(len(found), 1, found)
        self.assertIn('names skill gone', found[0])

    def test_a_table_above_cwd_is_found_with_the_skills_of_its_project(self):
        self.write('project/.claude/skills/own/SKILL.md', 'x\n')
        self.gates(json.dumps({'gates': [{'skills': ['known', 'own']}, {'skills': ['gone']}]}))
        table = os.path.join(self.cwd, '.claude', 'kit-gates.json')
        self.cwd = os.path.join(self.cwd, 'deeper', 'still')
        os.makedirs(self.cwd)
        self.assertEqual(self.found(), [f'{table} names skill gone: not in the kit or the project'])

    def test_a_broken_gate_table_is_a_finding(self):
        for text in ('{', '[]', '{"gates": ["x"]}', '{"gates": 1}'):
            with self.subTest(text = text):
                self.gates(text)
                self.assertIn('is unreadable', self.found()[0])

    def test_a_role_file_is_gone(self):
        os.remove(os.path.join(self.root, 'roles/executor.md'))
        self.assertEqual(self.found(), ['roles/executor.md: no such file'])

    def test_a_role_text_over_the_limit_of_a_hook(self):
        self.write('roles/observer.md', 'x' * roles.CONTEXT_LIMIT)
        self.assertEqual(self.found(), [f'roles/observer.md: its intro is over {roles.CONTEXT_LIMIT} chars, the end would be lost'])

    def test_an_observer_skill_is_gone(self):
        shutil.rmtree(os.path.join(self.root, 'skills/checkpoint'))
        self.assertEqual(self.found(), ['tools/roles.py OBSERVER_SKILLS names skill checkpoint: not under skills/'])

    def test_a_hook_file_without_registration_or_caller(self):
        self.write('hooks/dead.sh', 'true\n')
        self.assertEqual(self.found(), ['hooks/dead.sh: not in settings.base.json, no tracked file calls it'])

    def test_only_a_test_naming_a_hook_does_not_make_it_live(self):
        self.write('hooks/dead.sh', 'true\n')
        self.write('tools/test_x.py', 'dead.sh\n')
        self.git('add', 'tools/test_x.py')
        self.assertEqual(len(self.found()), 1)

    def test_a_status_line_registers_its_hook(self):
        self.write('hooks/bar.sh', 'true\n')
        self.settings('settings.base.json', hooks = hooks_of(LIVE), statusLine = {'command': 'bash "$HOME/.claude/hooks/bar.sh"'})
        self.assertEqual(self.found(), [])

    def test_outside_a_repository_the_caller_rule_is_silent(self):
        shutil.rmtree(os.path.join(self.root, '.git'))
        self.write('hooks/dead.sh', 'true\n')
        self.assertEqual(self.found(), [])

    def test_a_base_hook_command_without_its_file(self):
        gone = 'bash "$HOME/.claude/hooks/gone.sh"'
        self.settings('settings.base.json', hooks = hooks_of(LIVE, gone))
        self.settings('settings.json', hooks = hooks_of(LIVE, gone))
        self.assertEqual(self.found(), [f'settings.base.json hook {gone}: no such file'])

    def test_a_base_kit_hook_missing_from_settings(self):
        self.settings('settings.json', hooks = hooks_of(FOREIGN))
        self.assertEqual(self.found(), ['kit hooks in settings.json: missing in Stop'])

    def test_a_kit_hook_the_base_dropped_is_stale_a_foreign_one_stays(self):
        self.settings('settings.json', hooks = hooks_of(LIVE, FOREIGN, 'bash "$HOME/.claude/hooks/helper.sh"'))
        self.assertEqual(self.found(), ['settings.json runs a kit hook settings.base.json does not hold there: bash "$HOME/.claude/hooks/helper.sh"'])

    def test_settings_json_absent_or_broken(self):
        for text in (None, '{', '[]'):
            with self.subTest(text = text):
                self.write('settings.json', '')
                os.remove(os.path.join(self.root, 'settings.json'))
                if text:
                    self.write('settings.json', text)
                self.assertIn('settings.json is unreadable', self.found()[0])

    def test_a_broken_base_is_said_once(self):
        self.write('settings.base.json', '{')
        self.assertEqual(sum('settings.base.json is unreadable' in what for what in self.found()), 1)

    def test_the_tree_findings_do_not_need_settings_json(self):
        os.remove(os.path.join(self.root, 'settings.json'))
        self.assertEqual(kit_check.tree_findings(self.root, self.cwd), [])


class Doctor(unittest.TestCase):
    def setUp(self):
        """A copy of the kit's code and an invented HOME whose settings.json is broken."""
        self.kit = tempfile.mkdtemp()
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.kit, True)
        self.addCleanup(shutil.rmtree, self.home, True)
        shutil.copytree(os.path.join(KIT, 'bin'), os.path.join(self.kit, 'bin'))
        shutil.copytree(os.path.join(KIT, 'tools'), os.path.join(self.kit, 'tools'), ignore = shutil.ignore_patterns('quality', '__pycache__'))
        os.makedirs(os.path.join(self.kit, 'hooks'))
        os.makedirs(os.path.join(self.kit, 'agents'))
        shutil.copytree(os.path.join(KIT, 'roles'), os.path.join(self.kit, 'roles'))
        for name in roles.OBSERVER_SKILLS:
            os.makedirs(os.path.join(self.kit, 'skills', name))
            open(kit_check.skill_file(self.kit, name), 'w').close()
        with open(os.path.join(self.kit, 'hooks', 'live.sh'), 'w') as f:
            f.write('true\n')
        for name in ('settings.base.json', 'settings.json'):
            with open(os.path.join(self.kit, name), 'w') as f:
                json.dump({'hooks': hooks_of(LIVE)}, f)
        os.makedirs(os.path.join(self.home, '.claude'))
        with open(os.path.join(self.home, '.claude', 'settings.json'), 'w') as f:
            f.write('{')

    def doctor(self):
        env = {**os.environ, 'HOME': self.home, 'CLAUDE_ROLES_STATE_DIR': os.path.join(self.home, 'state')}
        for name in ('TMUX', 'TMUX_PANE'):  # no talk to the tmux of whoever runs the tests
            env.pop(name, None)
        return subprocess.run([sys.executable, os.path.join(self.kit, 'bin', 'claude-role'), 'doctor'], cwd = self.home,
                              env = env, capture_output = True, text = True).stdout

    def test_the_kit_is_the_copy_holding_the_file_not_home(self):
        self.assertIn('ok   the kit agrees with itself', self.doctor())

    def test_a_finding_is_a_line_of_its_own(self):
        with open(os.path.join(self.kit, 'agents', 'a.md'), 'w') as f:
            f.write('---\nskills: [gone]\n---\n')
        out = self.doctor()
        self.assertIn('no   agents/a.md names skill gone: not under skills/  → add skills/gone/SKILL.md', out)
        self.assertNotIn('the kit agrees with itself', out)


class HookPath(unittest.TestCase):
    """Precompact and sessionend reach claude through nvm under any HOME and any node version."""
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.said = os.path.join(self.home, 'said')
        tools = os.path.join(self.home, '.claude', 'tools')
        os.makedirs(tools)
        with open(os.path.join(tools, 'session_watch.py'), 'w') as f:
            f.write(f'import shutil\nopen({self.said!r} + ".tmp", "w").write(str(shutil.which("claude")))\n'
                    f'import os\nos.replace({self.said!r} + ".tmp", {self.said!r})\n')
        self.bare = os.path.join(self.home, 'bare')  # the tools the hooks use, no claude
        os.makedirs(self.bare)
        for tool in ('bash', 'jq', 'cat', 'dirname', 'basename', 'sed', 'ls', 'head'):
            if shutil.which(tool):
                os.symlink(shutil.which(tool), os.path.join(self.bare, tool))
        os.symlink(sys.executable, os.path.join(self.bare, 'python3'))

    def claude_at(self, folder):
        os.makedirs(folder)
        path = os.path.join(folder, 'claude')
        with open(path, 'w') as f:
            f.write('#!/bin/sh\n')
        os.chmod(path, 0o755)
        return path

    def run_hook(self, hook):
        env = {'HOME': self.home, 'PATH': self.bare, 'SESSIONEND_MIN': '0'}
        subprocess.run([shutil.which('bash'), os.path.join(KIT, 'hooks', hook)], input = '{"session_id": "abc"}', env = env,
                       cwd = self.home, capture_output = True, text = True, check = True)
        for _ in range(100):  # sessionend detaches the watcher
            if os.path.exists(self.said):
                with open(self.said) as f:
                    return f.read()
            time.sleep(0.05)
        self.fail(f'{hook} did not run the watcher')

    def test_claude_is_found_under_nvm_of_this_home(self):
        wanted = self.claude_at(os.path.join(self.home, '.nvm', 'versions', 'node', 'v0.0.1', 'bin'))
        for hook in ('precompact.sh', 'sessionend.sh'):
            with self.subTest(hook = hook):
                self.assertEqual(self.run_hook(hook), wanted)
                os.remove(self.said)

    def test_claude_already_in_path_wins(self):
        self.claude_at(os.path.join(self.home, '.nvm', 'versions', 'node', 'v0.0.1', 'bin'))
        wanted = self.claude_at(os.path.join(self.bare, 'own'))
        os.symlink(wanted, os.path.join(self.bare, 'claude'))
        self.assertEqual(self.run_hook('precompact.sh'), os.path.join(self.bare, 'claude'))

    def test_no_claude_anywhere_still_runs_the_hook(self):
        self.assertEqual(self.run_hook('precompact.sh'), 'None')


if __name__ == '__main__':
    unittest.main()
