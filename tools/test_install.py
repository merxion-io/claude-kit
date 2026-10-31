#!/usr/bin/env python3
# install.sh into a temp target: python3 tools/test_install.py. Adds what the kit lacks there, leaves the rest alone.
import json, os, subprocess, sys, tempfile, unittest

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ROLE_STATE = 'python3 "$HOME/.claude/hooks/role-state.py"'
FOREIGN = 'python3 /opt/my/own-hook.py'


class Install(unittest.TestCase):
    def setUp(self):
        self.target = tempfile.mkdtemp()
        self.bin = tempfile.mkdtemp()
        self.settings = os.path.join(self.target, 'settings.json')

    def install(self):
        env = {**os.environ, 'CLAUDE_HOME': self.target, 'XDG_BIN_HOME': self.bin}
        done = subprocess.run(['bash', os.path.join(KIT, 'install.sh')], env = env, capture_output = True, text = True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def write_settings(self, settings):
        with open(self.settings, 'w') as f:
            json.dump(settings, f)

    def read_settings(self):
        with open(self.settings) as f:
            return json.load(f)

    def commands(self, event):
        return [h['command'] for entry in self.read_settings()['hooks'].get(event, []) for h in entry['hooks']]

    def test_fresh_install_has_the_kit_and_no_project_tables(self):
        self.install()
        self.assertTrue(os.path.exists(os.path.join(self.target, 'tools', 'write_guard.py')))
        self.assertTrue(os.path.exists(os.path.join(self.target, 'tools', 'skill_gates.py')))
        self.assertTrue(os.path.exists(os.path.join(self.target, 'roles', 'observer.md')))
        self.assertTrue(os.path.exists(os.path.join(self.target, 'roles', 'executor.md')))
        self.assertFalse(os.path.exists(os.path.join(self.target, 'gates')))
        self.assertEqual(self.commands('SubagentStop'), [ROLE_STATE])

    def test_missing_hooks_added_foreign_hook_kept(self):
        self.write_settings({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': FOREIGN}]}]}})
        out = self.install()
        self.assertIn('hooks added', out)
        pre = self.read_settings()['hooks']['PreToolUse']
        self.assertEqual(pre[0], {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': FOREIGN}]})
        self.assertIn(ROLE_STATE, self.commands('PreToolUse'))
        self.assertEqual(self.commands('SubagentStart'), [ROLE_STATE])
        agent_guard = next(e for e in pre if any('agent-guard' in h['command'] for h in e['hooks']))
        self.assertEqual(agent_guard['matcher'], 'Agent|Task|Bash')

    def test_a_kit_hook_already_present_is_not_doubled(self):
        self.write_settings({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': ROLE_STATE}]}]}})
        self.install()
        self.assertEqual(self.commands('Stop').count(ROLE_STATE), 1)
        self.assertEqual(len(self.commands('Stop')), 2)  # plus observer-wait, missing before

    def test_the_same_command_under_a_narrower_matcher_does_not_count(self):
        narrow = {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': ROLE_STATE}]}
        self.write_settings({'hooks': {'PreToolUse': [narrow]}})
        self.install()
        pre = self.read_settings()['hooks']['PreToolUse']
        self.assertEqual(pre[0], narrow)
        self.assertTrue(any('matcher' not in e and ROLE_STATE in [h['command'] for h in e['hooks']] for e in pre), pre)
        self.install()
        self.assertEqual(self.read_settings()['hooks']['PreToolUse'], pre)

    def test_the_same_command_matching_everything_is_enough(self):
        agent_guard = 'python3 "$HOME/.claude/hooks/agent-guard.py"'
        for matcher in ('', '*'):
            with self.subTest(matcher = matcher):
                self.write_settings({'hooks': {'PreToolUse': [{'matcher': matcher, 'hooks': [{'type': 'command', 'command': agent_guard}]}]}})
                self.install()
                self.assertEqual(self.commands('PreToolUse').count(agent_guard), 1)

    def test_malformed_hooks_kept_and_the_install_ends(self):
        for hooks in (None, [], 'x', {'Stop': None}, {'Stop': {'a': 1}}):
            with self.subTest(hooks = hooks):
                self.write_settings({'hooks': hooks, 'mine': 1})
                out = self.install()
                settings = self.read_settings()
                self.assertEqual(settings['mine'], 1)
                self.assertEqual(settings['hooks'] if not isinstance(hooks, dict) else settings['hooks']['Stop'], hooks if not isinstance(hooks, dict) else hooks['Stop'])
                self.assertIn('left untouched', out)

    def test_malformed_entries_kept_kit_hook_added(self):
        junk = ['x', {'hooks': None}, {'hooks': ['x']}, {'matcher': 'y'}]
        self.write_settings({'hooks': {'Stop': list(junk)}})
        self.install()
        stop = self.read_settings()['hooks']['Stop']
        self.assertEqual(stop[:4], junk)
        self.assertIn(ROLE_STATE, [h['command'] for e in stop[4:] for h in e['hooks']])

    def test_foreign_value_kept(self):
        self.write_settings({'model': 'my-model', 'theme': 'light', 'mine': 1})
        self.install()
        settings = self.read_settings()
        self.assertEqual((settings['model'], settings['theme'], settings['mine']), ('my-model', 'light', 1))
        self.assertIn('hooks', settings)

    def test_second_run_byte_identical(self):
        self.write_settings({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': FOREIGN}]}]}, 'mine': 'key'})
        self.install()
        with open(self.settings, 'rb') as f:
            first = f.read()
        out = self.install()
        with open(self.settings, 'rb') as f:
            self.assertEqual(f.read(), first)
        self.assertIn('left untouched', out)

    def test_foreign_files_survive(self):
        for rel in ('tools/mine.py', 'skills/mine/SKILL.md', 'gates/mine.json', 'state/roles.json'):
            path = os.path.join(self.target, rel)
            os.makedirs(os.path.dirname(path))
            with open(path, 'w') as f:
                f.write('mine')
        self.install()
        for rel in ('tools/mine.py', 'skills/mine/SKILL.md', 'gates/mine.json', 'state/roles.json'):
            with open(os.path.join(self.target, rel)) as f:
                self.assertEqual(f.read(), 'mine', rel)


if __name__ == '__main__':
    sys.exit(unittest.main())
