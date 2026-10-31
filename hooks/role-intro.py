#!/usr/bin/env python3
# SessionStart (start, resume, /clear, compaction): for sessions with a role, who it is and the whole text of its role go into
# the context (roles.role_intro), so nothing is left for the model to load. Without a role and in nested claudes: silent.
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'tools'))
from roles import ROLE_NAMES, role_intro, role_session

role = ROLE_NAMES.get(role_session())
if role:
    print(role_intro(role, os.environ.get('CLAUDE_ROLE_NAME', '')))
