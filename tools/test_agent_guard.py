#!/usr/bin/env python3
# hooks/agent-guard.py as a role session runs it: python3 tools/test_agent_guard.py
import json, os, shutil, subprocess, sys, tempfile, unittest

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(KIT, 'tools'))
from kit_check import ROUTING_TABLE as TABLE


def refusal(kit, subagent_type):
    """The reason the guard of this kit gives an executor's Agent call of this type, or None."""
    with tempfile.TemporaryDirectory() as state:
        env = {**os.environ, 'CLAUDE_ROLE': 'executor', 'CLAUDE_ROLES_STATE_DIR': state}
        call = {'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'tool_input': {'subagent_type': subagent_type}}
        out = subprocess.run([sys.executable, os.path.join(kit, 'hooks', 'agent-guard.py')], input = json.dumps(call),
                             env = env, capture_output = True, text = True).stdout
    return json.loads(out)['hookSpecificOutput']['permissionDecisionReason'] if out.strip() else None


class ForbiddenType(unittest.TestCase):
    def test_the_reason_names_the_kit_roles(self):
        self.assertIn('researcher', refusal(KIT, 'general-purpose'))

    def test_a_new_role_file_is_named_with_no_edit_of_the_guard(self):
        kit = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, kit, True)
        for part in ('hooks', 'tools', 'agents'):
            shutil.copytree(os.path.join(KIT, part), os.path.join(kit, part), ignore = shutil.ignore_patterns('quality', '__pycache__'))
        os.makedirs(os.path.dirname(os.path.join(kit, TABLE)))
        shutil.copy(os.path.join(KIT, TABLE), os.path.join(kit, TABLE))
        with open(os.path.join(kit, 'agents', 'zeta.md'), 'w') as f:
            f.write('---\nname: zeta\n---\n')
        self.assertIn('verifier, zeta)', refusal(kit, 'general-purpose'))


if __name__ == '__main__':
    unittest.main()
