#!/usr/bin/env python3
# Context by role: how many tokens a session holds on its first assistant message and on the first one after each compaction.
# Reads main transcripts only (<projects>/<project>/<session>.jsonl; subagents live deeper). Prints role rows: no project,
# path or title. session_watch.usage_sum and the sensor of hooks/context-fill.sh count output too: a window fill, not this.
import argparse, datetime, glob, json, os, re, statistics, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from roles import ROLE_NAMES

NO_ROLE = 'none'
ROLES = (*ROLE_NAMES, NO_ROLE)
START, COMPACTION = 'start', 'compaction'
# Both the first wording (... your rules are in skill `roles`) and the present one (roles.role_intro) open like this. Anchored and
# only in a SessionStart hook's context: the skill listing, checkpoints and the conversation quote the phrase too.
INTRO = re.compile(rf'You are the ({"|".join(ROLE_NAMES)})\b')
# What the report reads, by substring before parsing: a transcript grows to 160 MB
WANTED = ('"assistant"', 'compact_boundary', 'hook_additional_context')
USAGE_KEYS = ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')


def context_tokens(usage):
    """Input + cache read + cache creation; zeroed top level: the last of usage.iterations (the rule of hooks/context-fill.sh)."""
    if not isinstance(usage, dict): return 0
    top = sum(v for v in map(usage.get, USAGE_KEYS) if isinstance(v, int))
    if top: return top
    iterations = usage.get('iterations')
    return context_tokens(iterations[-1]) if isinstance(iterations, list) and iterations else 0


def intro_role(attachment):
    """The role a SessionStart hook's context names, or None."""
    if attachment.get('type') != 'hook_additional_context' or attachment.get('hookEvent') != 'SessionStart': return None
    content = attachment.get('content')
    for item in content if isinstance(content, list) else [content]:
        found = INTRO.match(item) if isinstance(item, str) else None
        if found: return found.group(1)
    return None


def read_session(lines):
    """(role, [(kind, message id, timestamp, tokens)], malformed lines) of one main transcript."""
    role, samples, malformed = NO_ROLE, [], 0
    pending = START  # the kind the next assistant message with a usage answers; None: not measured
    for line in lines:
        if not any(word in line for word in WANTED): continue
        try: entry = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if not isinstance(entry, dict) or entry.get('isSidechain'): continue
        kind = entry.get('type')
        if kind == 'system' and entry.get('subtype') == 'compact_boundary':
            pending = COMPACTION
        elif kind == 'attachment' and isinstance(entry.get('attachment'), dict):
            role = intro_role(entry['attachment']) or role
        elif kind == 'assistant' and pending and isinstance(entry.get('message'), dict):
            tokens = context_tokens(entry['message'].get('usage'))
            if tokens:  # a zero entry (stop_sequence, api_error) measures nothing: the next one does
                samples.append((pending, entry['message'].get('id'), entry.get('timestamp'), tokens))
                pending = None
    return role, samples, malformed


def collect(root, since):
    """{role: {kind: [tokens]}}, sessions per role, malformed lines, unreadable files. A forked session repeats its parent's
    messages: one message id counts once."""
    table = {role: {START: [], COMPACTION: []} for role in ROLES}
    sessions = dict.fromkeys(ROLES, 0)
    seen, malformed, unreadable = set(), 0, 0
    floor = datetime.datetime.combine(since, datetime.time(), datetime.timezone.utc).timestamp() if since else 0
    for path in sorted(glob.glob(os.path.join(glob.escape(root), '*', '*.jsonl'))):
        try:
            if os.path.getmtime(path) < floor: continue
            with open(path, encoding = 'utf-8', errors = 'replace') as f:
                role, samples, bad = read_session(f)
        except OSError:
            unreadable += 1
            continue
        malformed += bad
        counted = False
        for kind, message, stamp, tokens in samples:
            if since and not (isinstance(stamp, str) and stamp[:10] >= since.isoformat()): continue
            if message and (kind, message) in seen: continue
            seen.add((kind, message))
            table[role][kind].append(tokens)
            counted = True
        sessions[role] += counted
    return table, sessions, malformed, unreadable


def stats(values):
    """count, median, p90 (nearest rank)."""
    if not values: return 0, '-', '-'
    ordered = sorted(values)
    return len(ordered), round(statistics.median(ordered)), ordered[(len(ordered) * 90 + 99) // 100 - 1]


def report(table, sessions, malformed, unreadable):
    rows = [f'{"role":<10}{"sessions":>9}{"start n":>9}{"median":>9}{"p90":>9}{"compact n":>11}{"median":>9}{"p90":>9}']
    for role in ROLES:
        n, median, p90 = stats(table[role][START])
        cn, cmedian, cp90 = stats(table[role][COMPACTION])
        rows.append(f'{role:<10}{sessions[role]:>9}{n:>9}{median:>9}{p90:>9}{cn:>11}{cmedian:>9}{cp90:>9}')
    rows.append(f'skipped: {malformed} malformed lines, {unreadable} unreadable files')
    return '\n'.join(rows)


def main():
    ap = argparse.ArgumentParser(description = 'Context tokens at session start and after compaction, by role')
    ap.add_argument('--since', type = datetime.date.fromisoformat, default = None, help = 'YYYY-MM-DD: messages from this day on')
    ap.add_argument('--projects-dir', default = os.path.expanduser('~/.claude/projects'))
    a = ap.parse_args()
    print(report(*collect(a.projects_dir, a.since)))


if __name__ == '__main__':
    main()
