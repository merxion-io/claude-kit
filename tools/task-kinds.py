import os, re, sys, json, glob, argparse, datetime, statistics, importlib.util
ap = argparse.ArgumentParser(description='Kinds of agent work: model, turns, price, handoff share from Claude Code transcripts')
ap.add_argument('--since', default=(datetime.date.today() - datetime.timedelta(days=14)).isoformat())
ap.add_argument('--json', action='store_true')
# --ops: what the main sessions do themselves (operation per turn: count, price, streaks), not the agents
ap.add_argument('--ops', action='store_true')
ap.add_argument('--project', default=None)
a = ap.parse_args()
# Price and the PRICE table — from token-spend.py (the script runs whole on import, so we substitute argv)
sys.argv = [sys.argv[0], '--since', a.since]
spec = importlib.util.spec_from_file_location('ts_cost', os.path.expanduser('~/.claude/tools/token-spend.py'))
src = open(spec.origin).read().split("since = datetime")[0].replace('ap.parse_args()', 'ap.parse_args([])')
ns = {}
exec(compile(src, spec.origin, 'exec'), ns)
cost = ns['cost']

# Kinds of work: first match by description + start of prompt (lowercase), order matters.
KINDS = [
    ('review round', ['review round', 'code review', 'review ', 'skeptic', 'verify finding', 'verifier', 'audit']),
    ('fix after review', ['fix review', 'review fix', 'after review', 'address review', 'fix findings', 'round 2', 'round 3', 'blocker']),
    ('ticks, report, board card', ['tick', 'checkbox', 'board card', 'on the board']),
    ('map/scouting', ['scout', 'map of', 'code map', 'locate', 'find where', 'survey', 'inventory', 'explore', 'investigate', 'research', 'read-only', 'only read']),
    ('delta merge and archive', ['merge delta', 'archive', 'merge deltas', 'delta merge', 'validate --specs']),
    ('proposal and spec deltas', ['proposal', 'delta', 'spec ', 'specs', 'design.md', 'tasks.md', 'adr', 'decisions.md']),
    ('reference labelling', ['annotat', 'golden', 'goldset', 'label ', 'labels']),
    ('measurement/live run', ['measure', 'live run', 'harness', 'benchmark', 'probe', 'smoke', 'e2e', 'before/after', 'profil', 'latency', 'baseline', 'eval ', 'evals']),
    ('production rollout', ['rollout', 'roll out', 'deploy']),
    ('cabinet/UI', ['cabinet', ' ui', 'ui ', 'frontend', 'tsx', 'react', 'next.js', 'component', 'css', 'screenshot', 'i18n', 'messages/', 'layout', 'web/']),
    ('tests by contract', ['test', 'pytest', 'coverage', 'sabotage', 'spec test', 'regression']),
    ('cleanup/transfer/indexes', ['cleanup', 'clean up', 'rename', 'move ', 'migrate', 'index', 'refactor', 'lint', 'format', 'remove', 'dead code', 'docs', 'readme', 'text', 'translat', 'rewrite', 'port ', 'sync', 'update skill', 'skill', 'hook', 'config', 'script']),
    ('engine logic', ['queue', 'transaction', 'model', 'engine', 'classif', 'pipeline', 'worker', 'lock', 'concurren', 'schema', 'sql', 'db ', 'database', 'api', 'endpoint', 'implement', 'build', 'add ', 'fix', 'bug', 'feature', 'change', 'edit', 'service', 'provider', 'mail', 'send', 'import', 'task ', 'step', 'phase', 'stage', 'wave', 'milestone', 'class', 'contact', 'parser', 'compan', 'dedup', 'owner', 'container']),
]
# In a builder's brief "map", "review", ticks and rollout lines always occur — these kinds are not assigned by prompt
PROMPT_NOISE = ('map/scouting', 'review round', 'ticks, report, board card', 'production rollout')
OTHER = 'other'

# The role decides itself where it is unambiguous; otherwise description first, then the start of prompt
ROLE_KIND = {'scout': 'map/scouting', 'code-reviewer': 'review round', 'verifier': 'review round', 'spec-reviewer': 'review round', 'spec-auditor': 'review round'}

def kind_of(role, desc, prompt):
    if role in ROLE_KIND: return ROLE_KIND[role]
    for text, skip in ((desc, ()), (prompt, PROMPT_NOISE)):
        t = text.lower()
        for name, words in KINDS:
            if name not in skip and any(w in t for w in words): return name
    return OTHER

def text_of(c):
    if isinstance(c, str): return c
    return ' '.join(b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text')

def read_agent(f):
    seen = set(); calls = 0; total = 0.0; model = ''; first = ''; last_text = ''
    for line in open(f, errors='ignore'):
        try: d = json.loads(line)
        except Exception: continue
        m = d.get('message') or {}
        if d.get('type') == 'user' and not first: first = text_of(m.get('content', ''))
        if d.get('type') != 'assistant': continue
        t = text_of(m.get('content', ''))
        if t.strip(): last_text = t
        u = m.get('usage'); key = (m.get('id'), d.get('requestId'))
        if not u or key in seen or (d.get('timestamp') or '')[:10] < a.since: continue
        seen.add(key); c = cost(m.get('model', ''), u)
        if c is None: continue
        total += sum(c.values()); calls += 1; model = m.get('model') or model
    return {'calls': calls, 'usd': total, 'model': model, 'first': first, 'last': last_text}

def family(m):
    g = re.search(r'(opus|sonnet|haiku|fable)', (m or '').lower())
    return g.group(1) if g else '?'

def outcome(last):
    low = last.lower()
    if re.search(r'"done"\s*:\s*false', low) or re.search(r'"handoff"\s*:\s*"[^"]', low): return 'handoff'
    if re.search(r'"done"\s*:\s*true', low): return 'done'
    return 'unknown'

# Operations of the main session itself — the classifier shared with hooks/agent-guard.py
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from routing import op_of

if a.ops:
    root = os.path.expanduser('~/.claude/projects/' + (a.project or '*'))
    stat = {}; since_ts = datetime.datetime.fromisoformat(a.since).timestamp()
    for f in glob.glob(root + '/*.jsonl'):
        if os.path.getmtime(f) < since_ts: continue
        msgs = {}; order = []
        for line in open(f, errors='ignore'):
            if '"assistant"' not in line: continue
            try: d = json.loads(line)
            except Exception: continue
            m = d.get('message') or {}
            if d.get('type') != 'assistant' or (d.get('timestamp') or '')[:10] < a.since: continue
            key = (m.get('id'), d.get('requestId'))
            if key not in msgs: msgs[key] = {'usd': 0.0, 'ops': []}; order.append(key)
            if m.get('usage') and not msgs[key]['usd']:
                c = cost(m.get('model', ''), m['usage']); msgs[key]['usd'] = sum(c.values()) if c else 0.0
            for b in m.get('content') or []:
                if isinstance(b, dict) and b.get('type') == 'tool_use': msgs[key]['ops'].append(op_of(b.get('name', ''), b.get('input') or {}))
        prev = None; streak = 0
        for key in order + [None]:
            ops = sorted(set(msgs[key]['ops'])) if key else []
            op = ops[0] if len(ops) == 1 else ('reply' if not ops else 'mixed')
            if op != prev and prev is not None:
                s = stat[prev]; s['streaks'] += 1; s['long'] += streak > 2
                streak = 0
            if key is None: break
            s = stat.setdefault(op, {'turns': 0, 'usd': 0.0, 'streaks': 0, 'long': 0})
            s['turns'] += 1; s['usd'] += msgs[key]['usd']; streak += 1; prev = op
    T = sum(s['usd'] for s in stat.values()) or 1
    print(f'Since {a.since}: main-session turns by operation ({a.project or "all projects"})')
    print(f'{"operation":24}{"turns":>7}{"$":>8}{"share":>6}{"series":>7}{"> 2 turns":>10}')
    for op, s in sorted(stat.items(), key=lambda x: -x[1]['usd']):
        print(f'{op:24}{s["turns"]:>7}{s["usd"]:>8.0f}{100 * s["usd"] / T:>5.0f}%{s["streaks"]:>7}{s["long"]:>10}')
    sys.exit()

# Cap on role turns — maxTurns from agents/<role>.md; a role without a file — 100
CAP = {}
for f in glob.glob(os.path.expanduser('~/.claude/agents/*.md')):
    g = re.search(r'^maxTurns:\s*(\d+)', open(f).read(), re.M)
    if g: CAP[os.path.basename(f)[:-3]] = int(g.group(1))
files = {}
for f in glob.glob(os.path.expanduser('~/.claude/projects/*/*/subagents/**/*.jsonl'), recursive=True):
    files[os.path.basename(f)[:-6].removeprefix('agent-')] = f
since_ts = datetime.datetime.fromisoformat(a.since).timestamp()
runs = []; used = set()
by_prompt = {}
for aid, f in files.items():
    try:
        for line in open(f, errors='ignore'):
            if '"type":"user"' in line:
                by_prompt[text_of(json.loads(line)['message']['content'])[:200]] = aid; break
    except Exception: pass
for f in glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')):
    if os.path.getmtime(f) < since_ts: continue
    pend = {}
    for line in open(f, errors='ignore'):
        if '"tool_use"' in line and ('"name":"Agent"' in line or '"name":"Task"' in line):
            try: d = json.loads(line)
            except Exception: continue
            for b in d['message']['content']:
                if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') in ('Agent', 'Task'): pend[b['id']] = b['input']
        elif '"tool_result"' in line and 'agentId' in line:
            for tid, inp in list(pend.items()):
                if tid in line:
                    m = re.search(r'agentId[\\"]*[:\s]+"?([0-9a-f]{8,})', line)
                    if m: inp['_aid'] = m.group(1)
    for tid, inp in pend.items():
        aid = inp.get('_aid') or by_prompt.get((inp.get('prompt') or '')[:200])
        if aid not in files or aid in used: continue
        used.add(aid)
        r = read_agent(files[aid])
        if not r['calls']: continue
        role = inp.get('subagent_type') or '?'
        cap = CAP.get(role, 100)
        out = outcome(r['last'])
        if out != 'handoff' and r['calls'] >= 0.95 * cap: out = 'handoff'
        runs.append({'role': role, 'model': family(inp.get('model') or r['model']), 'effort': inp.get('effort') or '?', 'description': inp.get('description', ''),
                     'kind': kind_of(role, inp.get('description') or '', (inp.get('prompt') or '')[:400]), 'calls': r['calls'], 'usd': round(r['usd'], 2), 'outcome': out})

def p90(xs):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(0.9 * len(xs)))]
rows = []
for k in [n for n, _ in KINDS] + [OTHER]:
    rs = [r for r in runs if r['kind'] == k]
    if not rs: continue
    mods = {}
    for m in {r['model'] for r in rs}:
        ms = [r for r in rs if r['model'] == m]
        mods[m] = (len(ms), round(100 * sum(r['outcome'] == 'handoff' for r in ms) / len(ms)))
    ho = sum(r['outcome'] == 'handoff' for r in rs)
    efforts = {e: sum(r['effort'] == e for r in rs) for e in {r['effort'] for r in rs}}
    roles = {e: sum(r['role'] == e for r in rs) for e in {r['role'] for r in rs}}
    rows.append({'kind': k, 'n': len(rs), 'models': mods, 'efforts': efforts, 'roles': roles, 'median_calls': statistics.median(r['calls'] for r in rs), 'p90_calls': p90([r['calls'] for r in rs]),
                 'avg_usd': round(sum(r['usd'] for r in rs) / len(rs), 2), 'handoff_pct': round(100 * ho / len(rs))})
other = [r for r in runs if r['kind'] == OTHER]
top_other = sorted(other, key=lambda r: -r['usd'])[:5]
if a.json:
    print(json.dumps({'since': a.since, 'runs': len(runs), 'other_share': round(100 * len(other) / max(1, len(runs))), 'kinds': rows, 'top_other': top_other}, ensure_ascii=False, indent=1)); sys.exit()
print(f'Since {a.since}: agent runs {len(runs)}')
print(f'{"kind":26}{"N":>4}  {"models (N, handoff)":44}{"med.turns":>10}{"p90":>5}{"$/run":>7}{"handoff":>8}')
for r in rows:
    print(f'{r["kind"]:26}{r["n"]:>4}  {" ".join(f"{m}:{n}/{h}%" for m, (n, h) in sorted(r["models"].items(), key=lambda x: -x[1][0]))[:43]:44}{r["median_calls"]:>10.0f}{r["p90_calls"]:>5}{r["avg_usd"]:>7.2f}{r["handoff_pct"]:>7}%')
print(f'other: {len(other)} of {len(runs)} ({100 * len(other) / max(1, len(runs)):.0f}%)')
for r in top_other: print(f'  ${r["usd"]:5.2f} {r["calls"]:4} turns {r["role"]} {r["description"][:80]}')
