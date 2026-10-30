#!/usr/bin/env python3
# Role hook on session events. For the executor — a state label in its tmux pane: @claude_state = "<state> ·
# <time> · <text>", one current, overwritten; the normal SessionEnd erases it, a kill (kill-session, signal)
# leaves it: the waiter will see "died". The observer reads it via `tmux list-panes -a`. Background is the standard field
# background_tasks in the Stop input (checked: builder, background command, Monitor — as shell, Workflow). An MCP server
# window (elicitation) is "asking", the answer to it is "working". Permission grant and denial, any interruption
# (Esc) are invisible to hooks — no events: the label is written by whoever pressed.
# For both roles on SessionStart — pane labels (role, name, observer, flags — passed by the launcher in the environment),
# the revive list (state/roles.json: conversation id, folder, flags, project) and the session into the pult project, if it is not there yet;
# on the normal SessionEnd — "closed"; remote control turned on mid-run goes into the flags. An executor that needs an observer (a state that wakes) while there is none
# brings it up. An executor keeps to its rules by tools/write_guard.py (its main session changes no files inside a git repository) and tools/skill_gates.py (gates of the project table). Without a role and in nested claudes the hook is silent (roles.role_session).
import contextlib, json, os, re, shlex, sys, time, traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'tools'))
import roles, skill_gates, write_guard
from roles import ASKING, BACKGROUND, BROKEN, BUILDER, OPENED, PERMISSION, RUNNING, STOPPED, WORKING

CLEAR = object()
IN_FLIGHT = '@claude_running'  # tool_use_id of foreground commands in flight


def tool_action(tool, tool_input):
    """What exactly the tool is about to do, for "waiting for permission"."""
    detail = next((tool_input[k] for k in ('command', 'file_path', 'url', 'path', 'pattern') if tool_input.get(k)),
                  None)
    return f'{tool}: {detail}' if detail else f'{tool} {json.dumps(tool_input, ensure_ascii = False)}'


def foreground(ev, running):
    """Foreground commands in flight (tool_use_id) after this event: the model may call tools in parallel, and the end
    of one does not mean the command next to it ended. The turn is over: nothing in flight."""
    event, tool_id = ev['hook_event_name'], ev.get('tool_use_id')
    if ev.get('agent_id') or not tool_id and event in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure'):
        return running
    if event == 'PreToolUse' and ev.get('tool_name') == 'Bash' and not (ev.get('tool_input') or {}).get(
            'run_in_background'):
        return running | {tool_id}
    if event in ('PostToolUse', 'PostToolUseFailure'):
        return running - {tool_id}
    if event in ('Stop', 'StopFailure', 'SessionStart', 'SessionEnd'):
        return set()
    return running


def state_for(ev, current, running = frozenset()):
    """The hook input, the current state and the foreground commands in flight after it → (state, text), CLEAR or
    None (no change)."""
    event, tool, tool_input = ev['hook_event_name'], ev.get('tool_name'), ev.get('tool_input') or {}
    if ev.get('agent_id'):
        # Builder inside an executor: its tools are not the executor's turn, except permission — that goes to the operator
        if event == 'PermissionRequest':
            return PERMISSION, f'{BUILDER}{tool_action(tool, tool_input)}'
        if event in ('PostToolUse', 'PostToolUseFailure') and current == PERMISSION:
            # The turn of the executor still belongs to the builder; its own turn, if one is running, will rewrite the label itself
            return BACKGROUND, f'builder got permission: {tool}'
        return None
    if event == 'SessionStart':
        return None if ev.get('source') == 'compact' else (OPENED, f'session open ({ev.get("source")})')
    if event == 'UserPromptSubmit':
        done = re.search(r'<task-notification>.*?<summary>(.*?)</summary>', ev.get('prompt') or '', re.S)
        return WORKING, f'background finished: {done.group(1)}' if done else ev.get('prompt')
    if event == 'PreToolUse':
        if tool == 'AskUserQuestion':
            return ASKING, ' / '.join(q.get('question', '') for q in tool_input.get('questions', []))
        if tool == 'Bash' and not tool_input.get('run_in_background'):
            return RUNNING, tool_input.get('command')
        return WORKING, tool
    if event == 'PermissionRequest':
        return None if tool == 'AskUserQuestion' else (PERMISSION, tool_action(tool, tool_input))
    if event == 'Elicitation':  # MCP server window: the tool waits for a human answer
        return ASKING, f'MCP «{ev.get("mcp_server_name")}»: {ev.get("message")}'
    if event == 'ElicitationResult':
        return WORKING, f'MCP «{ev.get("mcp_server_name")}»: {ev.get("action")}'
    if event in ('PostToolUse', 'PostToolUseFailure'):
        return None if running else (WORKING, tool)  # another command is still running nearby — the label is its
    if event == 'Stop':
        background = ev.get('background_tasks') or []
        if background:
            return BACKGROUND, '; '.join(f'{t.get("type")}: {t.get("description")}' for t in background)
        return STOPPED, ev.get('last_assistant_message')
    if event == 'StopFailure':
        return BROKEN, f'{ev.get("error")}: {ev.get("last_assistant_message") or ev.get("error_details") or ""}'
    if event == 'SessionEnd':
        return CLEAR  # a kill does not get here — main
    return None


def guarded(guard, ev, keeper, name):
    """A guard that fails is open: the labels and the other guard still run; the trace goes to the debug log (stderr, exit 0)."""
    try:
        return guard.hold(ev, keeper, name)
    except Exception:
        traceback.print_exc()
        return None


def main():
    pane, role = os.environ.get('TMUX_PANE'), roles.role_session()
    if not role:
        return
    ev, name = json.load(sys.stdin), os.environ['CLAUDE_ROLE_NAME']
    event = ev['hook_event_name']
    if event == 'SessionEnd' and ev.get('reason') == roles.KILLED:
        return  # died, not closed: the label and the list stay as they were — the pane may be gone
    if role == 'executor':
        keeper = os.environ.get(roles.ROLE_OBSERVER) or roles.pane_option(pane, '@claude_observer')
        said = guarded(skill_gates, ev, keeper, name) or guarded(write_guard, ev, keeper, name)  # gates first: a denied call takes no snapshot
        if said:
            print(json.dumps({'hookSpecificOutput': said}))  # ASCII: a file name not in UTF-8 cannot break the output
            if said.get('permissionDecision') == 'deny':
                return  # the call does not run: the label stays as it was
    pid = roles.role_pid()
    if roles.pane_option(pane, roles.PID_LABEL) != pid:
        roles.set_pane_option(pane, roles.PID_LABEL, pid)  # it shows liveness without the environment of a foreign process
    launch = os.environ.get(roles.ROLE_FLAGS)  # none — started by the previous launcher, which wrote the labels itself
    observer = name if role == 'observer' else os.environ.get(roles.ROLE_OBSERVER) \
        or roles.pane_option(pane, '@claude_observer')
    if event == 'SessionStart' and launch is not None:
        roles.label_pane(pane, role, name, os.environ.get(roles.ROLE_OBSERVER), shlex.split(launch))
    if role == 'executor':
        with roles.state_lock(pane):  # hooks of parallel events and claude-role tell
            before = set(roles.pane_option(pane, IN_FLIGHT).split())
            running = foreground(ev, before)
            if running != before:
                roles.set_pane_option(pane, IN_FLIGHT, ' '.join(sorted(running)))
            label = roles.pane_option(pane, roles.STATE)
            new = state_for(ev, roles.parse_state(label)[0], running)
            if new and new is not CLEAR and new[0] not in roles.WAKES and roles.parse_state(label)[0] == roles.TELLING \
                    and roles.pane_option(pane, roles.SEEN) != label:
                new = None  # "telling the observer" stays until the waiter has seen it: the next tool call must not hide it
            if new is CLEAR:
                roles.unset_pane_option(pane, roles.STATE)
            elif new:
                roles.write_state(pane, *new)
        if new and new is not CLEAR and new[0] in roles.WAKES:
            roles.revive_observer(observer, name)
    if event == 'SessionStart':
        session = roles.find_pane(pane)['session_name']  # the original session, not the twin
        launched = {} if launch is None else {'flags': shlex.split(launch)}
        project = os.environ.get(roles.ROLE_PROJECT)
        if project:
            launched['project'] = project
            adopt_pult(session, project, name)
        roles.update_roster(observer, role, name, {'session': session, 'pane': pane, 'cwd': ev['cwd'], **launched,
                                                   'conversation': ev['session_id'],
                                                   'transcript': ev.get('transcript_path'), 'since': int(time.time()),
                                                   'closed': False})
    elif event == 'SessionEnd':
        roles.update_roster(observer, role, name, {'closed': True})
    roles.sync_remote_control(pane, observer, role, name)
    if role == 'observer':
        push_tool(ev)


# The observer's push tool is deferred: after a start or a compaction its schema is gone. A one-time line at SessionStart
# was not held (2026-10-29), so until the observer loads it every prompt and tool call carries a reminder.
PUSH = 'PushNotification'
PUSH_REMINDER = f'Load the push tool now: ToolSearch("select:{PUSH}") — after a start or compaction its schema is gone.'


def push_loaded(ev):
    """This tool call loaded or used the push tool: ToolSearch selecting it, or the tool itself."""
    if ev.get('tool_name') == PUSH:
        return True
    query = str((ev.get('tool_input') or {}).get('query', ''))
    return ev.get('tool_name') == 'ToolSearch' and query.startswith('select:') and \
        PUSH in [q.strip() for q in query[len('select:'):].split(',')]


def push_tool(ev):
    """Mark «push tool loaded» per session: cleared at SessionStart and SessionEnd, set by push_loaded; while unset —
    a reminder on UserPromptSubmit and PostToolUse."""
    event, mark = ev['hook_event_name'], os.path.join(roles.STATE_DIR, f'push-{ev.get("session_id", "x")}')
    if event in ('SessionStart', 'SessionEnd'):
        with contextlib.suppress(OSError):
            os.remove(mark)
        return
    if event == 'PostToolUse' and push_loaded(ev):
        os.makedirs(roles.STATE_DIR, exist_ok = True)
        open(mark, 'w').close()
        return
    if event in ('UserPromptSubmit', 'PostToolUse') and not os.path.exists(mark):
        print(json.dumps({'hookSpecificOutput': {'hookEventName': event, 'additionalContext': PUSH_REMINDER}}))


def adopt_pult(session, project, name):
    """An executor session not in the pult journal goes to the project the launcher chose."""
    journal = roles.pult_journal()
    if journal and session not in journal[1]:
        failed = roles.pult_adopt(session, project, name)
        if failed:
            print(f'pult adopt {session} into "{project}" failed: {failed}', file = sys.stderr)


if __name__ == '__main__':
    main()
