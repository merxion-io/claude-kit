#!/usr/bin/env python3
# The context report over an invented transcript tree, through its command line: python3 tools/test_context_report.py
import json, os, shutil, subprocess, sys, tempfile, unittest

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(KIT, 'tools'))
import roles

SCRIPT = os.path.join(KIT, 'tools', 'context-report.py')
OLD_INTRO = 'You are the executor "n", your rules are in skill `roles`. Load it now (Skill roles), before any work.'
DAY = '2026-10-10T10:00:00.000Z'


def intro(text):
    return {'type': 'attachment', 'attachment': {'type': 'hook_additional_context', 'hookEvent': 'SessionStart', 'content': [text]}}


def role_intro(role):
    return intro(json.loads(roles.role_intro(role, 'n'))['hookSpecificOutput']['additionalContext'])


def assistant(message, tokens = 0, day = DAY, **usage):
    return {'type': 'assistant', 'timestamp': day, 'message': {'id': message, 'usage': {
        'input_tokens': tokens, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0, 'output_tokens': 7, **usage}}}


BOUNDARY = {'type': 'system', 'subtype': 'compact_boundary'}
SUMMARY = {'type': 'user', 'isCompactSummary': True, 'message': {'role': 'user', 'content': 'summary'}}
ZEROED = {'iterations': [{'input_tokens': 1}, {'input_tokens': 2, 'cache_read_input_tokens': 30, 'cache_creation_input_tokens': 400, 'output_tokens': 5000}]}


class Report(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def session(self, name, *entries, project = 'secret-project'):
        path = os.path.join(self.root, project, f'{name}.jsonl')
        os.makedirs(os.path.dirname(path), exist_ok = True)
        with open(path, 'a') as f:
            for entry in entries:
                f.write((entry if isinstance(entry, str) else json.dumps(entry)) + '\n')
        return path

    def run_report(self, *args):
        done = subprocess.run([sys.executable, SCRIPT, '--projects-dir', self.root, *args], capture_output = True, text = True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def rows(self, *args):
        """{role: [sessions, start n, median, p90, compact n, median, p90]} as printed."""
        return {line.split()[0]: line.split()[1:] for line in self.run_report(*args).splitlines()[1:-1]}

    def test_start_and_compaction_by_role(self):
        self.session('a', role_intro('observer'), assistant('a1', 100), assistant('a2', 999), BOUNDARY, SUMMARY,
                     role_intro('observer'), assistant('a3', 200), assistant('a4', 999), BOUNDARY, assistant('a5', 400))
        self.session('b', intro(OLD_INTRO), assistant('b1', 300))
        self.session('c', assistant('c1', 500))
        rows = self.rows()
        self.assertEqual(rows['observer'], ['1', '1', '100', '100', '2', '300', '400'])
        self.assertEqual(rows['executor'], ['1', '1', '300', '300', '0', '-', '-'])
        self.assertEqual(rows['none'], ['1', '1', '500', '500', '0', '-', '-'])

    def test_the_present_intro_of_each_role_classifies(self):
        for role in roles.ROLE_NAMES:
            self.session(role, role_intro(role), assistant(role, 10))
        rows = self.rows()
        self.assertEqual([rows[role][1] for role in roles.ROLE_NAMES], ['1', '1'])
        self.assertEqual(rows['none'][1], '0')

    def test_zeroed_top_level_takes_the_last_iteration_without_output(self):
        self.session('a', assistant('a1', 0, **ZEROED), BOUNDARY, assistant('a2', 0, **ZEROED))
        self.assertEqual(self.rows()['none'], ['1', '1', '432', '432', '1', '432', '432'])

    def test_top_level_sums_input_and_both_caches(self):
        self.session('a', assistant('a1', 1, cache_read_input_tokens = 20, cache_creation_input_tokens = 300))
        self.assertEqual(self.rows()['none'][2], '321')

    def test_a_zero_entry_measures_nothing(self):
        self.session('a', assistant('a0', 0), assistant('a1', 50))
        self.assertEqual(self.rows()['none'][1:4], ['1', '50', '50'])

    def test_p90_is_the_nearest_rank(self):
        for i in range(1, 11):
            self.session(f's{i}', assistant(f'm{i}', i * 10))
        self.assertEqual(self.rows()['none'][:4], ['10', '10', '55', '90'])

    def test_the_phrase_elsewhere_does_not_give_a_role(self):
        listing = {'type': 'attachment', 'attachment': {'type': 'skill_listing', 'hookEvent': 'SessionStart', 'content': ['You are the observer']}}
        quoted = {'type': 'user', 'message': {'role': 'user', 'content': 'You are the observer'}}
        restored = intro('Restored. Notes: You are the observer "n"')
        other_event = {'type': 'attachment', 'attachment': {'type': 'hook_additional_context', 'hookEvent': 'Stop', 'content': ['You are the observer']}}
        self.session('a', listing, quoted, restored, other_event, assistant('a1', 10))
        self.assertEqual(self.rows()['none'][1], '1')

    def test_subagents_and_sidechains_are_excluded(self):
        self.session('a', {**assistant('side', 7), 'isSidechain': True}, {**BOUNDARY, 'isSidechain': True}, assistant('a1', 10), assistant('a2', 20))
        self.session('agent-1', assistant('sub', 999), project = 'secret-project/a/subagents')
        rows = self.rows()
        self.assertEqual(rows['none'], ['1', '1', '10', '10', '0', '-', '-'])

    def test_a_forked_session_counts_its_parents_messages_once(self):
        shared = [assistant('m1', 10), BOUNDARY, assistant('m2', 20)]
        self.session('a', *shared)
        self.session('b', *shared)
        rows = self.rows()['none']
        self.assertEqual((rows[1], rows[4]), ('1', '1'))

    def test_since_filters_by_the_message_day(self):
        self.session('a', assistant('a1', 10, day = '2026-09-30T23:59:00.000Z'), BOUNDARY, assistant('a2', 20, day = '2026-10-01T00:00:00.000Z'))
        self.session('b', assistant('b1', 30, day = '2026-09-01T00:00:00.000Z'))
        self.assertEqual(self.rows('--since', '2026-10-01')['none'], ['1', '0', '-', '-', '1', '20', '20'])

    def test_malformed_input_does_not_crash(self):
        path = self.session('a', '{"type":"assistant", truncated', 'null', '[1]', '"assistant"',
                            {'type': 'assistant', 'message': 'text'}, {'type': 'assistant', 'message': {'usage': 'x'}},
                            {'type': 'assistant', 'message': {'id': 'x', 'usage': {'input_tokens': 'many', 'iterations': ['y']}}},
                            {'type': 'attachment', 'attachment': 'text'},
                            {'type': 'attachment', 'attachment': {'type': 'hook_additional_context', 'hookEvent': 'SessionStart', 'content': [1, None]}},
                            assistant('a1', 10))
        with open(path, 'ab') as f:
            f.write(b'\xff\xfe"assistant"\n')
        self.assertEqual(self.rows()['none'][1:3], ['1', '10'])
        self.assertIn('2 malformed lines', self.run_report())

    def test_no_transcripts_and_no_directory(self):
        self.assertEqual(self.rows()['none'], ['0', '0', '-', '-', '0', '-', '-'])
        done = subprocess.run([sys.executable, SCRIPT, '--projects-dir', os.path.join(self.root, 'missing')], capture_output = True, text = True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_output_names_no_project_or_path(self):
        self.session('a1b2c3', role_intro('observer'), assistant('a1', 10), project = 'secret-project')
        out = self.run_report()
        for private in ('secret', self.root, 'a1b2c3', '"n"', '/'):
            self.assertNotIn(private, out)

    def test_a_bad_date_is_refused(self):
        done = subprocess.run([sys.executable, SCRIPT, '--since', 'soon'], capture_output = True, text = True)
        self.assertEqual(done.returncode, 2)


if __name__ == '__main__':
    unittest.main()
