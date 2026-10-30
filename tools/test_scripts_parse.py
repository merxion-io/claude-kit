#!/usr/bin/env python3
# Every script of the kit parses: python3 tools/test_scripts_parse.py. A hook that does not parse fails silently on each call.
# The kit is what its .gitignore keeps: plugins and shell snapshots of the machine are not scanned.
import ast, os, re, shutil, subprocess, tempfile, unittest

KIT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
PYTHON_HOMES = ('hooks', 'tools')
SKIPPED_DIRS = ('__pycache__',)
BASH_TIMEOUT = 30  # seconds per file


def shebang(path):
    with open(path, 'rb') as f:
        return f.readline().decode('utf-8', 'replace') if f.read(2) == b'#!' else ''


def kit_files(root):
    """Files under the root, relative, without dot directories, __pycache__ and what the root's git ignores."""
    found = []
    for here, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in SKIPPED_DIRS]
        found += [os.path.relpath(os.path.join(here, f), root) for f in files]
    done = subprocess.run(['git', '-C', root, 'check-ignore', '--stdin'], input = '\n'.join(found), capture_output = True, text = True)
    ignored = set(done.stdout.splitlines()) if done.returncode == 0 else set()
    return [f for f in found if f not in ignored]


def scripts(root):
    """(python scripts, shell scripts), absolute: hooks/*.py, tools/*.py, every *.sh, bin/* by extension or shebang."""
    python, shell = [], []
    for rel in kit_files(root):
        path, home = os.path.join(root, rel), os.path.dirname(rel)
        line = shebang(path) if home == 'bin' else ''
        if (home in PYTHON_HOMES and rel.endswith('.py')) or (home == 'bin' and (rel.endswith('.py') or 'python' in line)):
            python.append(path)
        elif rel.endswith('.sh') or re.search(r'\b(ba)?sh\b', line):
            shell.append(path)
    return python, shell


def problems(root):
    """The scripts under the root that do not parse, each with why."""
    found, (python, shell) = [], scripts(root)
    for path in python:
        try:
            with open(path, 'rb') as f:
                ast.parse(f.read(), path)
        except (SyntaxError, ValueError) as e:
            found.append(f'{path}: {e}')
    for path in shell:
        done = subprocess.run(['bash', '-n', path], capture_output = True, text = True, timeout = BASH_TIMEOUT)
        if done.returncode:
            found.append(f'{path}: {done.stderr.strip()}')
    return found


class ScriptsParse(unittest.TestCase):
    def test_the_kit_parses_and_the_scan_is_not_empty(self):
        python, shell = scripts(KIT)
        self.assertGreater(len(python), 5)
        self.assertGreater(len(shell), 5)
        self.assertIn(os.path.join(KIT, 'bin', 'claude-role'), python)
        self.assertEqual(problems(KIT), [])

    def test_a_broken_script_is_reported(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        os.makedirs(os.path.join(root, 'hooks'))
        os.makedirs(os.path.join(root, 'bin'))
        os.makedirs(os.path.join(root, 'tools', '.venv'))
        for name in ('role-state.py', 'statusline.sh'):
            shutil.copy(os.path.join(KIT, 'hooks', name), os.path.join(root, 'hooks', name))
        shutil.copy(os.path.join(KIT, 'hooks', 'context-fill.sh'), os.path.join(root, 'hooks', 'fine.sh'))
        for name, text in (('hooks/role-state.py', "x = '\n"), ('hooks/statusline.sh', 'echo "\n'), ('tools/.venv/skipped.py', "x = '\n"),
                           ('bin/py-tool', "#!/usr/bin/env python3\nx = '\n"), ('bin/sh-tool', '#!/bin/bash\necho "\n')):
            with open(os.path.join(root, name), 'a') as f:
                f.write(text)
        reported = {os.path.relpath(p.split(':')[0], root) for p in problems(root)}
        self.assertEqual(reported, {'hooks/role-state.py', 'hooks/statusline.sh', 'bin/py-tool', 'bin/sh-tool'})


if __name__ == '__main__':
    unittest.main()
