#!/usr/bin/env python3
# Waiter scan and screen footer rule: python3 tools/test_roles.py. The real waiter scan (hooks/observer-wait.py attention)
# reads the state labels; screen.dialog reads a captured pane.
import importlib.machinery, importlib.util, os, sys, tempfile, time, unittest

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


def scan(state, seen = '', now = None):
    """The real scan over one live executor pane → the (pane, name, key, line) it wakes the observer on."""
    pane = {'pane_id': '%7', 'session_name': 's', 'pane_pid': '90', 'pane_current_command': 'claude',
            '@claude_role': 'executor', '@claude_name': 'e', '@claude_observer': 'me', '@claude_state': state,
            '@claude_seen': seen, '@claude_flags': '', roles.PID_LABEL: '100'}
    return waiter.attention('me', [pane], PROCS, now or time.mktime(time.strptime(STAMP, roles.TIME_FORMAT)) + 1, {}, 0)


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


if __name__ == '__main__':
    unittest.main()
