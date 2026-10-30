#!/usr/bin/env python3
# Observer waiter: Stop hook with asyncRewake. Waits until one of ITS executors (@claude_observer = the
# observer name) needs attention, and wakes the observer: exit 2, who · state · gist — in stderr (a tell — its full text). Wakes on:
# asks, waits for permission, stopped, broke, hung ("working" without events longer than HANG), died (the claude
# of this role is not running while the state label stayed — the normal SessionEnd did not erase it; or an executor from the list that
# has no pane — not closed normally, except those waiting for the revive after a reboot). Does not wake on: works, runs a
# command, waits for its background. The check runs right at start: what happened while the observer was busy wakes it at once.
# What was seen — the @claude_seen label of the executor pane (the same state label) — does not wake again; death —
# seen in the list entry, one per launch: died in the pane, then the pane vanished — one wake-up.
# One waiter: its PID is in the @claude_waiter label of the observer pane, a new one kills the previous by PID.
# Silent without the observer role and in nested claudes (roles.role_session).
import os, signal, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'tools'))
import roles
from roles import SEEN, SEP, WORKING

# Measurement 2026-10-28 on the journals of three executors: "working" without a new event while the model works — up to 64 s
# (2763 intervals, p99.9 58 s); the threshold was chosen by the observer
HANG = 120
POLL = 2
WAITER = '@claude_waiter'


def death(entry):
    """The seen key of a death, one per launch (the pane and the entry's confirmation time): died in the pane, then the
    pane vanished too: no second wake."""
    return SEP.join(('died', str(entry.get('pane')), str(entry.get('since'))))


def attention(me, all_panes, tree, now, team, started):
    """→ [(pane or None, name, seen key, line for the observer)]: executors of observer me that need attention and
    were not yet seen in this state; pane None: seen goes in the list entry (seen).
    team: its executors from the list, started: the start of the tmux server."""
    found = []
    for p in all_panes:
        if p['@claude_role'] != 'executor' or p['@claude_observer'] != me:
            continue
        name, label, where = p['@claude_name'], p['@claude_state'], p['pane_id']
        seen = p['@claude_seen']
        if not roles.live(p, 'executor', tree):
            entry = team.get(name, {})
            if not label or entry.get('closed'):
                continue  # closed normally: SessionEnd (not a kill) erased the label, or close marked the entry first
            key, what = f'died{SEP}{label}', f'died (claude is not running), last: {label}'
            if entry.get('pane') == where:
                key, seen, where = death(entry), entry.get('seen'), None
        else:
            kind, since, _ = roles.parse_state(label)
            if kind in roles.WAKES:
                key = what = label
                full = roles.told(where, label)
                if full is not None:  # tell: the whole text from its file, the label is cut
                    what = SEP.join(label.split(SEP, 2)[:2] + [full])
            elif kind == WORKING and now - since > HANG:
                key, what = f'hung{SEP}{label}', f'hung: {round(now - since)} s without events · {label}'
            else:
                continue
        if key != seen:
            found.append((where, name, key, f'"{name}" (session {p["session_name"]}): {what}'))
    pane_ids = {p['pane_id'] for p in all_panes}
    for name, entry in team.items():
        if entry.get('pane') in pane_ids or entry.get('closed') or entry.get('since', 0) < started:
            continue  # pane exists — looked at above; closed normally; waiting for the revive after a reboot
        if death(entry) != entry.get('seen'):
            found.append((None, name, death(entry), f'"{name}" (session {entry.get("session")}): died, pane '
                                                    f'{entry.get("pane")} is gone, bring it up with claude-role revive'))
    return found


def is_waiter(pid):
    argv = roles.processes().get(pid, (0, []))[1]
    return any(os.path.basename(a) == os.path.basename(__file__) for a in argv)


def take_over(pane):
    old = roles.pane_option(pane, WAITER)
    if old.isdigit() and int(old) != os.getpid() and is_waiter(int(old)):
        os.kill(int(old), signal.SIGTERM)
    roles.set_pane_option(pane, WAITER, str(os.getpid()))


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def main():
    pane = os.environ.get('TMUX_PANE')
    if roles.role_session() != 'observer':
        return 0
    sys.stdin.read()
    me, claude = os.environ['CLAUDE_ROLE_NAME'], roles.own_claude()
    if not claude:
        return 0
    take_over(pane)
    while roles.pane_option(pane, WAITER) == str(os.getpid()) and alive(claude):
        # Processes, panes, list, in this order: a list older than the panes reads a normal close as "died".
        tree, all_panes = roles.processes(), roles.panes()
        team = roles.read_roster().get(me, {}).get('executors', {})
        found = attention(me, all_panes, tree, time.time(), team, roles.server_start())
        if found:
            for executor_pane, name, key, _ in found:
                if executor_pane:
                    roles.set_pane_option(executor_pane, SEEN, key)
                    roles.forget_tell(executor_pane, key)
                else:
                    roles.update_roster(me, 'executor', name, {'seen': key})
            roles.unset_pane_option(pane, WAITER)
            sys.stderr.write('Executors need attention:\n' + '\n'.join(line for *_, line in found) + '\n')
            return 2
        time.sleep(POLL)
    return 0


if __name__ == '__main__':
    sys.exit(main())
