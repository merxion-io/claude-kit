#!/usr/bin/env python3
# The kit checks itself: the one home of the rules, called by `claude-role doctor` and tools/test_kit_check.py. Read-only.
# Everything is read from the kit root and the cwd handed in, never from HOME: "$HOME/.claude" in a hook command means the root.
# A finding is (what is wrong, what to do). Which hook files have a caller is known only in a git repository: elsewhere
# (a kit copied by install.sh) that rule says nothing.
import glob, json, os, re, shlex, subprocess

import roles
from write_guard import project_table_path

KIT_PREFIX = re.compile(r'^(?:\$HOME|\$\{HOME\}|~)/\.claude(?=/)')


def skill_file(home, name):
    return os.path.join(home, 'skills', name, 'SKILL.md')


def frontmatter_skills(text):
    """The names under `skills:` of an agent's frontmatter, as a block list or inline."""
    head = re.match(r'---\n(.*?)\n---', text, re.S)
    field = head and re.search(r'^skills:[ \t]*(.*)((?:\n[ \t]*-[ \t]*.+)*)', head[1], re.M)
    if not field:
        return []
    names = field[1].strip(' []').split(',') + re.findall(r'-[ \t]*(.+)', field[2])
    return [n.strip(' \'"') for n in names if n.strip(' \'"')]


def agent_skills(root, cwd):
    found = []
    for path in sorted(glob.glob(os.path.join(root, 'agents', '*.md'))):
        with open(path, encoding = 'utf-8') as f:
            names = frontmatter_skills(f.read())
        found += [(f'agents/{os.path.basename(path)} names skill {name}: not under skills/',
                   f'add skills/{name}/SKILL.md or drop the name') for name in names if not os.path.isfile(skill_file(root, name))]
    return found


def gate_skills(root, cwd):
    """A gate may name a kit skill or one of the project's own; the table is the one up from cwd."""
    path = project_table_path(cwd)
    if not path:
        return []
    try:
        with open(path, encoding = 'utf-8') as f:
            gates = json.load(f).get('gates', [])
        names = sorted({name for gate in gates for name in gate.get('skills', [])})
    except (OSError, ValueError, AttributeError, TypeError) as e:
        return [(f'{path} is unreadable: {e}', 'fix the table: {"gates": [{"skills": [...]}]}')]
    return [(f'{path} names skill {name}: not in the kit or the project', f'add skill {name} or fix the table')
            for name in names if not any(os.path.isfile(skill_file(home, name)) for home in (root, os.path.dirname(path)))]


def role_texts(root, cwd):
    """A role's file exists and its SessionStart output stays whole."""
    found = []
    for role in roles.ROLE_NAMES:
        if not os.path.isfile(roles.role_file(root, role)):
            found.append((f'roles/{role}.md: no such file', 'restore it from git'))
        elif len(roles.role_intro(role, 'name', root)) >= roles.CONTEXT_LIMIT:
            found.append((f'roles/{role}.md: its intro is over {roles.CONTEXT_LIMIT} chars, the end would be lost', 'shorten the role text'))
    return found


def observer_skills(root, cwd):
    return [(f'tools/roles.py OBSERVER_SKILLS names skill {name}: not under skills/', f'add skills/{name}/SKILL.md or drop the name')
            for name in roles.OBSERVER_SKILLS if not os.path.isfile(skill_file(root, name))]


def read_settings(path):
    with open(path, encoding = 'utf-8') as f:
        settings = json.load(f)
    if not isinstance(settings, dict):
        raise ValueError('not an object')
    return settings


def base_settings(root):
    """settings.base.json, or {} when it is broken: hook_commands says so, once."""
    try:
        return read_settings(os.path.join(root, 'settings.base.json'))
    except (OSError, ValueError):
        return {}


def event_commands(settings):
    """event -> the commands of its hooks; a malformed part holds none (install.sh leaves it as it is)."""
    events = settings.get('hooks')
    return {event: {h['command'] for g in groups if isinstance(g, dict) and isinstance(g.get('hooks'), list)
                    for h in g['hooks'] if isinstance(h, dict) and h.get('command')}
            for event, groups in (events.items() if isinstance(events, dict) else ()) if isinstance(groups, list)}


def base_commands(settings):
    status = settings.get('statusLine')
    return sorted(set().union(*event_commands(settings).values(), {status['command']} if status else ()))


def command_files(root, command):
    """The paths a hook command names, the kit's own under the root."""
    return [os.path.normpath(KIT_PREFIX.sub(lambda _: root, word)) for word in shlex.split(command) if '/' in word]


def hook_commands(root, cwd):
    base = os.path.join(root, 'settings.base.json')
    try:
        settings = read_settings(base)
    except (OSError, ValueError) as e:
        return [(f'settings.base.json is unreadable: {e}', 'restore it from git')]
    found = []
    for command in base_commands(settings):
        try:
            files = command_files(root, command)
        except ValueError as e:
            found.append((f'settings.base.json hook {command}: {e}', 'fix the command'))
            continue
        if not files or not all(os.path.isfile(f) for f in files):
            found.append((f'settings.base.json hook {command}: no such file', 'fix the command or restore the file'))
    return found


def git_files(root, *args):
    """Paths from git ls-files, or None outside a repository."""
    done = subprocess.run(['git', '-C', root, 'ls-files', '-z', *args], capture_output = True)
    return None if done.returncode else os.fsdecode(done.stdout).split('\0')[:-1]


def is_test(path):
    return os.path.basename(path).startswith('test_')


def has_caller(root, hook, tracked):
    """A tracked file names it. Neither the hook itself nor a test makes a hook live."""
    name = os.path.basename(hook).encode()
    for path in tracked:
        full = os.path.join(root, path)
        if path != hook and not is_test(path) and os.path.isfile(full):
            with open(full, 'rb') as f:
                if name in f.read():
                    return True
    return False


def hook_files(root, cwd):
    tracked = git_files(root)
    if tracked is None:
        return []
    registered = {f for c in base_commands(base_settings(root)) for f in command_files(root, c)}
    return [(f'{hook}: not in settings.base.json, no tracked file calls it', 'register it or delete it')
            for hook in git_files(root, '-c', '-o', '--exclude-standard', 'hooks/')
            if os.path.join(root, hook) not in registered and not has_caller(root, hook, tracked)]


def is_kit_hook(root, command):
    hooks = os.path.join(root, 'hooks') + os.sep
    try:
        return any(f.startswith(hooks) for f in command_files(root, command))
    except ValueError:
        return False


def settings_hooks(root):
    """settings.json holds every hook of settings.base.json per event, and no kit hook the base dropped; foreign hooks may stay."""
    path = os.path.join(root, 'settings.json')
    try:
        have = event_commands(read_settings(path))
    except (OSError, ValueError) as e:
        return [(f'settings.json is unreadable: {e}', 'run install.sh')]
    need = event_commands(base_settings(root))
    missing = sorted(event for event, commands in need.items() if not commands <= have.get(event, set()))
    stale = sorted({c for event, commands in have.items() for c in commands - need.get(event, set()) if is_kit_hook(root, c)})
    return ([(f'kit hooks in settings.json: missing in {", ".join(missing)}',
              f'move these events from {os.path.join(root, "settings.base.json")} to {path}')] if missing else []) + \
           [(f'settings.json runs a kit hook settings.base.json does not hold there: {c}', f'remove it from {path}') for c in stale]


TREE_CHECKS = (agent_skills, gate_skills, role_texts, observer_skills, hook_commands, hook_files)  # a new rule over the tree is one more function here


def tree_findings(root, cwd):
    """What git holds, so the same on every machine."""
    return [finding for rule in TREE_CHECKS for finding in rule(root, cwd)]


def findings(root, cwd):
    """The tree and this machine's settings.json."""
    return tree_findings(root, cwd) + settings_hooks(root)
