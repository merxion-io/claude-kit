#!/usr/bin/env python3
# Guard against private words in a public kit: python3 tools/private_words.py [--message FILE | --range A..B | --pre-push REMOTE]
# No arguments: the working tree and the index. --message (commit-msg hook): the index and the message. --range: the messages.
# --pre-push: what the push sends, messages and files of every new commit.
# The denylist is <kit root>/.kit-private-words (untracked): one word per line, blank lines and # ignored.
# A hit prints file:line and the word, exit 1. No list or no word in it: one line saying so, exit 0.
import itertools, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LIST = os.path.join(ROOT, '.kit-private-words')
ZERO = '0' * 40
GITLINK = '160000'
SCISSORS = '# ------------------------ >8 ------------------------\n'


def load_words(path = LIST):
    with open(path, encoding = 'utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.lstrip().startswith('#')]


def word_pattern(words):
    """Case-insensitive, Unicode, whole word: not adjacent to a word character; an entry is matched literally."""
    parts = sorted((re.escape(w) for w in words), key = len, reverse = True)
    return re.compile(r'(?<!\w)(?:' + '|'.join(parts) + r')(?!\w)', re.IGNORECASE)


def hits(pattern, text, where):
    """[(where:line, word)] for every match in the text."""
    return [(f'{where}:{n}', m.group()) for n, line in enumerate(text.splitlines(), 1) for m in pattern.finditer(line)]


def git(*args, check = True):
    done = subprocess.run(['git', '-C', ROOT, *args], capture_output = True)
    if check and done.returncode != 0:
        sys.exit(f'git {" ".join(args)}: {done.stderr.decode("utf-8", "replace").strip()}')
    return done.stdout


def text_of(data):
    """The text of a file, or None for a binary one."""
    return None if b'\0' in data[:8000] else data.decode('utf-8', 'replace')


def blobs(listing, field):
    """Rows of git ls-files -s or ls-tree -r → [(path, blob sha at this field)]; a submodule has no blob here."""
    rows = (row.split('\t', 1) for row in git(*listing, '-z').decode('utf-8', 'replace').split('\0') if row)
    return [(path, meta.split()[field]) for meta, path in rows if not meta.startswith(GITLINK)]


def scan_blobs(pattern, entries, prefix = ''):
    found = []
    for path, blob in entries:
        found += hits(pattern, path, f'path {path}')
        text = text_of(git('cat-file', 'blob', blob))
        if text is not None:
            found += hits(pattern, text, prefix + path)
    return found


def scan_index(pattern):
    """What the next commit holds: tracked paths and staged content (under git commit -a, its temporary index)."""
    return scan_blobs(pattern, blobs(['ls-files', '-s'], 1))


def scan_tree(pattern):
    """The index and the edits not staged yet."""
    found = scan_index(pattern)
    for path in git('diff', '--name-only', '-z').decode('utf-8', 'replace').split('\0'):
        full = os.path.join(ROOT, path)
        if path and os.path.isfile(full):
            with open(full, 'rb') as f:
                text = text_of(f.read())
            if text is not None:
                found += hits(pattern, text, f'{path} (not staged)')
    return found


def commits(rev_list_args):
    return git('rev-list', *rev_list_args).decode().split()


def scan_commits(pattern, rev_list_args):
    found = []
    for sha in commits(rev_list_args):
        message = git('show', '-s', '--format=%B', sha).decode('utf-8', 'replace')
        found += hits(pattern, message, f'commit {sha[:8]}')
    return found


def scan_message(pattern, path):
    """The file of commit-msg: comments are no part of the message, nor is the diff of git commit -v under the scissors."""
    with open(path, encoding = 'utf-8', errors = 'replace') as f:
        text = ''.join(line for line in itertools.takewhile(lambda l: l != SCISSORS, f) if not line.startswith('#'))
    return hits(pattern, text, 'commit message')


def pushed(remote, local, known):
    """rev-list arguments of what a push brings to this remote: a ref new to it, or over a commit unknown here (a forced
    push), has only what this remote is known to hold to go by; what another remote holds is news to this one."""
    if known != ZERO and git('rev-parse', '-q', '--verify', f'{known}^{{commit}}', check = False):
        return [f'{known}..{local}']
    return [local, '--not', f'--remotes={remote}']


def scan_push(pattern, remote, refs):
    """refs: lines of pre-push stdin, 'local_ref local_sha remote_ref remote_sha'. What leaves is checked, not the working
    tree: the messages of the new commits, the paths and files of each of them and of the tip."""
    found, seen = [], set()
    for line in refs.splitlines():
        fields = line.split()
        if len(fields) != 4 or fields[1] == ZERO:
            continue
        local, args = fields[1], pushed(remote, fields[1], fields[3])
        found += scan_commits(pattern, args)
        for sha in [local, *commits(args)]:
            new = [e for e in blobs(['ls-tree', '-r', sha], 2) if e not in seen]
            seen.update(new)
            found += scan_blobs(pattern, new, f'{sha[:8]}:')
    return found


def main(argv):
    words = load_words() if os.path.exists(LIST) else []
    if not words:
        print(f'private words: no words at {LIST}, nothing to check')
        return 0
    pattern = word_pattern(words)
    if argv[:1] == ['--message'] and len(argv) == 2:
        found = scan_index(pattern) + scan_message(pattern, argv[1])
    elif argv[:1] == ['--range'] and len(argv) == 2:
        found = scan_commits(pattern, [argv[1]])
    elif argv[:1] == ['--pre-push'] and len(argv) == 2:
        found = scan_push(pattern, argv[1], sys.stdin.read())
    elif not argv:
        found = scan_tree(pattern)
    else:
        sys.exit('usage: private_words.py [--message FILE | --range A..B | --pre-push REMOTE]')
    for where, word in found:
        print(f'{where}: {word}')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
