#!/usr/bin/env python3
# SessionStart (start, resume, /clear, compaction): for sessions with a role — one line into the context: who it is and where
# its rules are. Without a role and in nested claudes — silent.
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'tools'))
from roles import ROLE_NAMES, role_session

session = role_session()
role = ROLE_NAMES.get(session)
if role:
    line = (f'You are the {role} "{os.environ.get("CLAUDE_ROLE_NAME", "")}", your rules are in skill `roles`. '
            f'Load it now (Skill roles), before any work.')
    if session == 'observer':  # after compaction deferred tool schemas are gone: the first push would fail
        line += ' And load the push tool right away: ToolSearch("select:PushNotification").'
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': line}},
                     ensure_ascii = False))
