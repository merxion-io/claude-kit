#!/usr/bin/env python3
# The private-words guard over a temp git repo with an invented list: python3 tools/test_private_words.py
import os, shutil, subprocess, sys, tempfile, unittest

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
GUARD = os.path.join(KIT, 'tools', 'private_words.py')
WORDS = ['zorblax', 'quux.engine', 'Ünïcode']


class PrivateWords(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 't@example.test')
        self.git('config', 'user.name', 't')
        os.makedirs(os.path.join(self.repo, 'tools'))
        shutil.copy(GUARD, os.path.join(self.repo, 'tools'))

    def git(self, *args):
        return subprocess.run(['git', '-C', self.repo, *args], capture_output = True, text = True)

    def write(self, path, text):
        full = os.path.join(self.repo, path)
        os.makedirs(os.path.dirname(full), exist_ok = True)
        with open(full, 'w', encoding = 'utf-8') as f:
            f.write(text)
        self.git('add', path)

    def list_words(self, words = WORDS):
        self.write('.kit-private-words', '# invented\n\n' + '\n'.join(words) + '\n')
        self.git('reset', '-q', '.kit-private-words')

    def guard(self, *args, stdin = ''):
        return subprocess.run([sys.executable, os.path.join(self.repo, 'tools', 'private_words.py'), *args],
                              input = stdin, capture_output = True, text = True)

    def test_hit_in_file_with_line(self):
        self.list_words()
        self.write('docs/a.md', 'clean\nthe Zorblax is here\n')
        done = self.guard()
        self.assertEqual(done.returncode, 1)
        self.assertIn('docs/a.md', done.stdout)
        self.assertIn(':2: Zorblax', done.stdout)

    def test_hit_in_path(self):
        self.list_words()
        self.write('docs/zorblax-notes.md', 'clean\n')
        done = self.guard()
        self.assertEqual(done.returncode, 1)
        self.assertIn('path docs/zorblax-notes.md', done.stdout)

    def test_hit_in_staged_version_only(self):
        self.list_words()
        self.write('a.md', 'zorblax\n')
        self.git('commit', '-qm', 'x')
        self.write('a.md', 'clean\n')
        self.git('reset', '-q', 'a.md')
        self.assertEqual(self.guard().returncode, 1)

    def test_whole_word_only_and_literal_entries(self):
        self.list_words()
        self.write('a.md', 'zorblaxes and unzorblax and zorblax_1\nquuxXengine\n')
        self.assertEqual(self.guard().returncode, 0)
        self.write('b.md', 'see (quux.engine) and ÜNÏCODE.\n')
        done = self.guard()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(done.stdout.splitlines()), 2)

    def test_binary_file_skipped(self):
        self.list_words()
        self.write('a.bin', 'zorblax\0\n')
        self.assertEqual(self.guard().returncode, 0)

    def test_message_hit_and_comment_lines_dropped(self):
        self.list_words()
        msg = os.path.join(self.repo, 'msg')
        with open(msg, 'w') as f:
            f.write('fine subject\n# zorblax in a comment\n')
        self.assertEqual(self.guard('--message', msg).returncode, 0)
        with open(msg, 'w') as f:
            f.write('fine subject\n\nabout zorblax\n')
        done = self.guard('--message', msg)
        self.assertEqual(done.returncode, 1)
        self.assertIn('Zorblax'.lower(), done.stdout.lower())

    def test_range_checks_messages(self):
        self.list_words()
        self.write('a.md', 'x\n')
        self.git('commit', '-qm', 'first')
        self.write('b.md', 'x\n')
        self.git('commit', '-qm', 'mentions zorblax')
        self.assertEqual(self.guard('--range', 'HEAD~1..HEAD').returncode, 1)
        self.assertEqual(self.guard('--range', 'HEAD~1..HEAD~1').returncode, 0)

    def test_pre_push_checks_new_ref_commits(self):
        self.list_words()
        self.write('a.md', 'x\n')
        self.git('commit', '-qm', 'mentions zorblax')
        sha = self.git('rev-parse', 'HEAD').stdout.strip()
        done = self.guard('--pre-push', 'origin', stdin = f'refs/heads/main {sha} refs/heads/main {"0" * 40}\n')
        self.assertEqual(done.returncode, 1)

    def test_no_list_says_so_and_passes(self):
        self.write('a.md', 'zorblax\n')
        done = self.guard()
        self.assertEqual(done.returncode, 0)
        self.assertEqual(len(done.stdout.splitlines()), 1)

    def test_installed_commit_msg_hook_rejects_bad_message(self):
        self.list_words()
        env = {**os.environ, 'CLAUDE_HOME': self.repo, 'XDG_BIN_HOME': tempfile.mkdtemp()}
        for _ in range(2):  # a repeat run is the same state
            done = subprocess.run(['bash', os.path.join(KIT, 'install.sh')], env = env, capture_output = True, text = True)
            self.assertEqual(done.returncode, 0, done.stderr)
        self.write('a.md', 'clean\n')
        bad = self.git('commit', '-m', 'about zorblax')
        self.assertNotEqual(bad.returncode, 0)
        self.assertEqual(self.git('rev-list', '--all', '--count').stdout.strip(), '0')
        self.assertEqual(self.git('commit', '-m', 'about nothing').returncode, 0)

    def test_foreign_hook_is_not_overwritten(self):
        hooks = os.path.join(self.repo, '.git', 'hooks')
        os.makedirs(hooks, exist_ok = True)
        with open(os.path.join(hooks, 'commit-msg'), 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        env = {**os.environ, 'CLAUDE_HOME': self.repo, 'XDG_BIN_HOME': tempfile.mkdtemp()}
        done = subprocess.run(['bash', os.path.join(KIT, 'install.sh')], env = env, capture_output = True, text = True)
        self.assertIn('foreign hook', done.stdout)
        with open(os.path.join(hooks, 'commit-msg')) as f:
            self.assertEqual(f.read(), '#!/bin/sh\nexit 0\n')

    def install(self):
        env = {**os.environ, 'CLAUDE_HOME': self.repo, 'XDG_BIN_HOME': tempfile.mkdtemp()}
        done = subprocess.run(['bash', os.path.join(KIT, 'install.sh')], env = env, capture_output = True, text = True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def bare(self, name):
        path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, path, True)
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', path], check = True)
        self.git('remote', 'add', name, path)
        return path

    def committed(self, path, text, message = 'clean'):
        self.write(path, text)
        self.assertEqual(self.git('commit', '-q', '--no-verify', '-m', message).returncode, 0)

    def test_installed_hook_refuses_a_commit_of_a_staged_word(self):
        self.list_words()
        self.install()
        self.write('a.md', 'zorblax\n')
        self.assertEqual(self.git('commit', '-m', 'clean').returncode, 1)
        self.write('a.md', 'clean\n')
        self.assertEqual(self.git('commit', '-m', 'clean').returncode, 0)
        with open(os.path.join(self.repo, 'a.md'), 'w') as f:
            f.write('zorblax\n')
        self.assertEqual(self.git('commit', '-a', '-m', 'clean').returncode, 1)  # -a: a temporary index

    def test_commit_ignores_an_unstaged_word_and_a_verbose_diff_removing_it(self):
        self.list_words()
        self.install()
        self.committed('c.md', 'clean\n')
        self.write('a.md', 'clean\n')
        with open(os.path.join(self.repo, 'b.md'), 'w') as f:
            f.write('zorblax\n')  # not tracked at all
        with open(os.path.join(self.repo, 'c.md'), 'w') as f:
            f.write('zorblax\n')  # tracked, the edit not staged
        self.assertEqual(self.git('commit', '-m', 'clean').returncode, 0)
        self.git('reset', '-q', '--hard')
        self.committed('c.md', 'zorblax\n')
        with open(os.path.join(self.repo, 'c.md'), 'w') as f:
            f.write('clean\n')
        verbose = subprocess.run(['git', '-C', self.repo, 'commit', '-a', '-v'], capture_output = True, text = True,
                                 env = {**os.environ, 'GIT_EDITOR': 'sed -i 1iremoved'})
        self.assertEqual(verbose.returncode, 0, verbose.stdout)

    def test_push_refuses_a_word_only_in_the_pushed_history(self):
        self.list_words()
        self.install()
        self.bare('o')
        self.committed('a.md', 'clean\n')
        self.committed('a.md', 'zorblax\n')
        self.committed('a.md', 'clean again\n')
        done = self.git('push', 'o', 'main')
        self.assertEqual(done.returncode, 1)
        self.assertIn('a.md:1: zorblax', done.stdout + done.stderr)

    def test_push_refuses_a_word_on_a_branch_that_is_not_checked_out(self):
        self.list_words()
        self.install()
        self.bare('o')
        self.committed('a.md', 'clean\n')
        self.git('checkout', '-q', '-b', 'side')
        self.committed('a.md', 'zorblax\n')
        self.git('checkout', '-q', '-')
        self.assertEqual(self.git('push', 'o', 'side').returncode, 1)
        self.assertEqual(self.git('push', 'o', 'main').returncode, 0)

    def test_push_is_not_blocked_by_an_uncommitted_edit(self):
        self.list_words()
        self.install()
        self.bare('o')
        self.committed('a.md', 'clean\n')
        with open(os.path.join(self.repo, 'a.md'), 'w') as f:
            f.write('zorblax\n')
        self.assertEqual(self.git('push', 'o', 'main').returncode, 0)

    def test_what_one_remote_holds_is_still_checked_for_another(self):
        self.list_words()
        self.install()
        self.bare('private')
        self.bare('public')
        self.committed('a.md', 'clean\n', 'about zorblax')
        self.assertEqual(self.git('push', '--no-verify', 'private', 'main').returncode, 0)
        self.assertEqual(self.git('push', 'public', 'main').returncode, 1)
        self.git('branch', 'copy')
        self.assertEqual(self.git('push', 'private', 'copy').returncode, 0)  # already there: this push carries nothing new

    def test_force_push_over_a_remote_commit_unknown_here(self):
        self.list_words()
        self.install()
        path = self.bare('o')
        self.committed('a.md', 'clean\n')
        self.git('push', 'o', 'main')
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, True)
        subprocess.run(['git', 'clone', '-q', path, other], check = True)
        def theirs():
            subprocess.run(['git', '-C', other, '-c', 'user.email=a@b.test', '-c', 'user.name=a', 'commit', '-q', '--allow-empty',
                            '-m', 'theirs'], check = True)
            subprocess.run(['git', '-C', other, 'push', '-q', '-f', 'origin', 'HEAD:main'], check = True)
        theirs()
        self.committed('a.md', 'mine\n')
        self.assertEqual(self.git('push', '-f', 'o', 'main').returncode, 0)
        theirs()
        self.committed('a.md', 'mine too\n', 'about zorblax')
        self.assertEqual(self.git('push', '-f', 'o', 'main').returncode, 1)

    def test_deleting_a_remote_ref_passes(self):
        self.list_words()
        self.install()
        self.bare('o')
        self.committed('a.md', 'zorblax\n')
        self.assertEqual(self.git('push', '--no-verify', 'o', 'main:side').returncode, 0)
        self.assertEqual(self.git('push', 'o', ':side').returncode, 0)

    def test_a_list_of_only_comments_checks_nothing(self):
        self.write('.kit-private-words', '# none yet\n\n')
        self.git('reset', '-q', '.kit-private-words')
        self.write('a.md', 'one\n\ntwo  three\n')
        self.assertEqual(self.guard().returncode, 0)

    def test_install_says_when_git_will_not_run_its_hooks(self):
        self.git('config', 'core.hooksPath', 'elsewhere')
        self.assertIn('core.hooksPath', self.install())

    def test_a_linked_worktree_reads_the_list_of_the_main_root(self):
        self.list_words()
        self.write('docs/a.md', 'clean\n')
        self.git('add', 'tools/private_words.py')
        self.git('commit', '-q', '-m', 'one')
        linked = os.path.join(tempfile.mkdtemp(), 'linked')
        self.addCleanup(shutil.rmtree, os.path.dirname(linked), True)
        self.git('worktree', 'add', '-q', '-b', 'side', linked)
        with open(os.path.join(linked, 'docs', 'a.md'), 'w', encoding = 'utf-8') as f:
            f.write('the zorblax is here\n')
        done = subprocess.run([sys.executable, os.path.join(linked, 'tools', 'private_words.py')], capture_output = True, text = True)
        self.assertEqual((done.returncode, 'docs/a.md (not staged):1: zorblax' in done.stdout), (1, True), done.stdout)

    def test_outside_a_repo_the_list_is_read_beside_the_tools(self):
        plain = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, plain, True)
        os.makedirs(os.path.join(plain, 'tools'))
        shutil.copy(GUARD, os.path.join(plain, 'tools'))
        with open(os.path.join(plain, '.kit-private-words'), 'w') as f:
            f.write('zorblax\n')
        done = subprocess.run([sys.executable, os.path.join(plain, 'tools', 'private_words.py')], capture_output = True, text = True)
        self.assertNotIn('no words at', done.stdout)  # the list was found; git itself then has no repo to scan

    def test_a_dangling_link_at_a_hook_is_foreign_too(self):
        target = os.path.join(tempfile.mkdtemp(), 'theirs')
        hook = os.path.join(self.repo, '.git', 'hooks', 'pre-push')
        os.makedirs(os.path.dirname(hook), exist_ok = True)
        os.symlink(target, hook)
        self.assertIn('foreign hook', self.install())
        self.assertFalse(os.path.exists(target))


if __name__ == '__main__':
    unittest.main()
