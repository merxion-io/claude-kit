import os, re, sys, json, glob, argparse, datetime, collections
ap = argparse.ArgumentParser(description='Token spend from Claude Code transcripts at API prices')
ap.add_argument('--since', default=(datetime.date.today() - datetime.timedelta(days=7)).isoformat())
# Default project — the transcript directory of the current git root (as Claude Code names it: path with / → -)
ap.add_argument('--project', default=None)
ap.add_argument('--top', type=int, default=10)
a = ap.parse_args()
top = os.popen('git rev-parse --show-toplevel 2>/dev/null').read().strip() or os.getcwd()
root = os.path.expanduser(f"~/.claude/projects/{a.project or top.replace('/', '-')}")
# $/1M (platform.claude.com, 2026-10): input, output, cache write 5m, 1h, read; haiku-5-5 — prompt ≤ 100k (over it ×5)
PRICE = {'claude-opus-5-5': (4, 20, 5, 8, 0.20), 'claude-sonnet-5-5': (2, 10, 2.5, 4, 0.10), 'claude-haiku-5-5': (0.10, 0.50, 0.125, 0.20, 0.01),
    'claude-fable-5-1': (10, 50, 12.5, 20, 0.25), 'claude-fable-5': (10, 50, 12.5, 20, 1.0), 'claude-opus-5': (5, 25, 6.25, 10, 0.5),
    'claude-opus-4-8': (5, 25, 6.25, 10, 0.5), 'claude-opus-4-7': (5, 25, 6.25, 10, 0.5), 'claude-sonnet-5': (2, 10, 2.5, 4, 0.2),
    'claude-haiku-4-5-20251001': (1, 5, 1.25, 2, 0.1)}
# A model without a price is not skipped silently: until 2026-10-19 all *-5-5 got lost this way (showed a fifth of the spend)
unpriced = collections.Counter()
def cost(model, u):
    p = PRICE.get((model or '').split('[')[0])
    if p is None:
        if model and model != '<synthetic>': unpriced[model] += 1
        return None
    cc = u.get('cache_creation') or {}
    w5, w1 = (cc.get('ephemeral_5m_input_tokens', 0), cc.get('ephemeral_1h_input_tokens', 0)) if cc else (u.get('cache_creation_input_tokens', 0), 0)
    return {'read': u.get('cache_read_input_tokens', 0) * p[4] / 1e6, 'write': (w5 * p[2] + w1 * p[3]) / 1e6, 'output': u.get('output_tokens', 0) * p[1] / 1e6, 'input': u.get('input_tokens', 0) * p[0] / 1e6}
since = datetime.datetime.fromisoformat(a.since).timestamp()
parts = collections.Counter(); kinds = collections.Counter(); models = collections.Counter(); types = collections.Counter(); agents = []; sessions = collections.Counter(); seen = set()
for f in glob.glob(root + '/*.jsonl') + glob.glob(root + '/*/subagents/**/*.jsonl', recursive = True):
    if os.path.getmtime(f) < since: continue
    sub = '/subagents/' in f
    kind = 'sub' if sub else 'main'
    atype = 'main'
    if sub:
        try: atype = json.load(open(f[:-6] + '.meta.json')).get('agentType') or '?'
        except Exception: atype = '?'
    sess = f[len(root) + 1:].split('/')[0].replace('.jsonl', '')[:8]
    total = calls = ctx_sum = ctx_max = 0; model = ''; prompt = ''; has_map = False
    for line in open(f, errors='ignore'):
        if sub and not prompt and '"type":"user"' in line:
            try:
                c = json.loads(line)['message']['content']; full = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                prompt = full[:90].replace('\n', ' ')
                # The brief is often passed as a file: we look for the map in it too
                for b in re.findall(r'(/[^\s`\'"]+\.md)', full)[:3]:
                    try: full += open(b, errors='ignore').read()
                    except Exception: pass
                has_map = any(w in full.lower() for w in ('map:', 'scout map', '-map.md'))
            except Exception: pass
        if '"usage"' not in line: continue
        try: d = json.loads(line)
        except Exception: continue
        if d.get('type') != 'assistant' or (d.get('timestamp') or '')[:10] < a.since: continue
        m = d['message']; u = m.get('usage'); key = (m.get('id'), d.get('requestId'))
        if not u or key in seen: continue
        seen.add(key); c = cost(m.get('model', ''), u)
        if c is None: continue
        for k, v in c.items(): parts[k] += v
        s = sum(c.values()); total += s; calls += 1; model = m.get('model')
        ctx = u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0) + u.get('cache_creation_input_tokens', 0); ctx_sum += ctx; ctx_max = max(ctx_max, ctx)
        kinds[kind] += s; models[model] += s; types[atype] += s; sessions[sess] += s
    if calls and sub: agents.append((total, calls, ctx_sum // calls, ctx_max, model, atype, sess, prompt, has_map))
    if calls: kinds[kind + '_calls'] += calls; kinds[kind + '_ctx'] += ctx_sum
T = sum(parts.values()) or 1
print(f'Since {a.since}: ${T:,.0f} at API prices')
print('  ' + ' · '.join(f'{k} {100 * parts[k] / T:.1f}%' for k in ('read', 'write', 'output', 'input')))
for k in ('main', 'sub'):
    n = kinds[k + '_calls'] or 1
    print(f'  {k:4} ${kinds[k]:,.0f} ({100 * kinds[k] / T:.0f}%) · turns {kinds[k + "_calls"]} · average turn context {kinds[k + "_ctx"] // n // 1000}k')
print('  models: ' + ' · '.join(f'{m} ${v:,.0f}' for m, v in models.most_common()))
print('  agent types: ' + ' · '.join(f'{t} ${v:,.0f}' for t, v in types.most_common(8)))
print('  sessions: ' + ' · '.join(f'{s} ${v:,.0f}' for s, v in sessions.most_common(5)))
print(f'Most expensive agents (turns · average/max context):')
for t, n, avg, mx, mo, at, s, p, _ in sorted(agents, reverse=True)[:a.top]: print(f'  ${t:6,.0f} {n:5} turns {avg // 1000:4}k/{mx // 1000}k {mo} {at} [{s}] {p}')
# Slicing and acceleration of builders (measured 10.2026: > 100 turns — 6 of 43 and 54 % of the money; without a scout map 32 turns before the first edit)
builders = [x for x in agents if x[5] == 'builder']
if builders:
    long = [x for x in builders if x[1] > 100]; blind = [x for x in builders if not x[8]]
    spent = sum(x[0] for x in builders) or 1
    print(f'Builders: {len(builders)} · > 100 turns: {len(long)}, ${sum(x[0] for x in long):,.0f} ({100 * sum(x[0] for x in long) / spent:.0f}%) · no map in the prompt and brief file: {len(blind)} of {len(builders)}'
          + ('  ⚠ cut subtasks smaller and give the scout map' if long or len(blind) > len(builders) // 2 else ''))
if unpriced: print('⚠ no price (not counted): ' + ' · '.join(f'{m} {n} turns' for m, n in unpriced.most_common()))
