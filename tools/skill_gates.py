# An executor keeps to its project's gates: an action of the project's table (commit, spec write, build, full test run,
# Agent…) is denied while one of its skills was never loaded. The table is <project>/.claude/kit-gates.json up from cwd,
# for a Bash command up from the directory it acts in; none → no gates. Kept per executor (observer and name): the skills its main session has loaded — at any time in this
# conversation; compaction and resume keep them (re-injected), startup and /clear start empty.
# Subagents (payload agent_id) are never touched; the observer is not either (the caller passes executors only).
import json, os, re

import roles
import write_guard


def mark_path(observer, name):
    return os.path.join(roles.STATE_DIR, f'skills-{write_guard.session_key(observer, name)}.json')


def read_mark(path):
    try:
        with open(path) as f:
            mark = json.load(f)
    except (OSError, ValueError):
        mark = {}
    return {'skills': mark.get('skills', [])}


def write_mark(path, mark):
    os.makedirs(roles.STATE_DIR, exist_ok = True)
    with open(path + '.tmp', 'w') as f:
        json.dump(mark, f, ensure_ascii = False)
    os.replace(path + '.tmp', path)


def skill_loaded(ev):
    """The skill this event loads: the Skill tool, or the operator typing /<skill> → its name; else None."""
    if ev['hook_event_name'] == 'PostToolUse' and ev.get('tool_name') == 'Skill':
        return str((ev.get('tool_input') or {}).get('skill', '')).split(':')[-1].strip() or None
    if ev['hook_event_name'] == 'UserPromptSubmit':
        m = re.match(r'\s*/([\w.-]+)', ev.get('prompt') or '')
        return m and m.group(1)
    return None


def in_dirs(path, cwd, dirs):
    """The path (absolute, or relative to cwd) lies under one of dirs (relative to cwd)."""
    if not path or path.startswith('/dev/'):
        return False
    rel = os.path.relpath(path, os.path.abspath(cwd))
    return not rel.startswith('..') and any(rel == d or rel.startswith(d.rstrip('/') + '/') for d in dirs)


def gate_hits(gate, ev):
    """The tool call is the gate's action: "tool" — tool names; "write" — dirs it writes under (git apply and patch count whatever the path)."""
    tool, cwd = ev.get('tool_name'), ev.get('cwd') or os.getcwd()
    if tool in gate.get('tool', []):
        return True
    return bool(gate.get('write')) and any(t.whole_tree or in_dirs(t.path, cwd, gate['write']) for t in write_guard.write_targets(ev))


def hit_gates(ev):
    """The gates this call is the action of: tool and write gates of the session's table; "bash" gates, a regex over one
    command (no quoted text), of the table of the directory that command acts in."""
    cwd = ev.get('cwd') or os.getcwd()
    yield from (gate for gate in write_guard.project_table(cwd).get('gates', []) if gate_hits(gate, ev))
    if ev.get('tool_name') == 'Bash':
        for place, words in write_guard.acting_commands((ev.get('tool_input') or {}).get('command') or '', cwd):
            yield from (gate for gate in write_guard.project_table(place).get('gates', [])
                        if gate.get('bash') and re.search(gate['bash'], words, re.M))


def denied(ev, mark):
    """PreToolUse of the main session → the reason of a deny, or None."""
    loaded = set(mark['skills'])
    for gate in hit_gates(ev):
        missing = [s for s in gate.get('skills', []) if s not in loaded]
        if missing:
            return (f'{gate.get("action", "this action")}: load {", ".join(f"`{s}`" for s in missing)} first (Skill tool) — '
                    'it was never loaded in this session; then repeat the call.')
    return None


def hold(ev, observer, name):
    """The hooks of an executor's main session → hookSpecificOutput dict or None."""
    if ev.get('agent_id'):
        return None  # a builder or scout of this executor: never touched
    event, path = ev['hook_event_name'], mark_path(observer, name)
    mark = read_mark(path)
    if event == 'SessionStart':
        if ev.get('source') in ('startup', 'clear'):
            write_mark(path, {'skills': []})  # a new context: nothing loaded yet; compaction and resume keep the skills
        return None
    skill = skill_loaded(ev)
    if skill and skill not in mark['skills']:
        mark['skills'].append(skill)
        write_mark(path, mark)
    if event == 'PreToolUse':
        why = denied(ev, mark)
        return why and {'hookEventName': event, 'permissionDecision': 'deny', 'permissionDecisionReason': why}
    return None
