import os, re, sys, json
# PostToolUse(Write|Edit): exit code 2 hands stderr to the model — the edit is already done, the guard only orders to compress
NOTE, INDEX, INDEX_LINES, SKILL, REF = 4096, 8192, 40, 12288, 8192
try: path = json.load(sys.stdin).get('tool_input', {}).get('file_path') or ''
except Exception: sys.exit(0)
if not path or not os.path.isfile(path): sys.exit(0)
size = os.path.getsize(path); name = os.path.basename(path)
rule = 'A new lesson REWRITES the rule, it does not add a dated paragraph; history goes in the commit message or an archive outside memory.'
if re.search(r'/\.claude/projects/[^/]+/memory/', path):
    if name == 'MEMORY.md':
        lines = sum(1 for l in open(path, errors='ignore') if l.startswith('- ['))
        if size > INDEX or lines > INDEX_LINES:
            print(f'Memory guard: index MEMORY.md = {size} bytes and {lines} lines (limit {INDEX} bytes and {INDEX_LINES} lines). The index holds only everyday rules, one line ≤ 110 chars; topical material goes to a skill in .claude/skills/. Compress now.', file=sys.stderr); sys.exit(2)
    elif size > NOTE:
        print(f'Memory guard: {name} = {size} bytes (limit {NOTE}). {rule} Compress the note now; if the topic has grown, it belongs in a skill in .claude/skills/.', file=sys.stderr); sys.exit(2)
elif name == 'CLAUDE.md':
    lines = sum(1 for _ in open(path, errors='ignore'))
    if lines > 100:
        print(f'CLAUDE.md guard: {path} = {lines} lines (operator rule: at most 100). CLAUDE.md holds only rules and links to skills; procedures, measurements and history go to skills in .claude/skills/ or to the project's spec (its CLAUDE.md names where). Compress now.', file=sys.stderr); sys.exit(2)
elif '/.claude/skills/' in path and path.endswith('.md'):
    limit = SKILL if name == 'SKILL.md' else REF if '/references/' in path else 0
    if limit and size > limit:
        print(f'Skill guard: {path} = {size} bytes (limit {limit}). A skill body loads WHOLE when triggered: rare details go to references/<topic>.md, repetition and history are removed. {rule}', file=sys.stderr); sys.exit(2)
sys.exit(0)
