# Ratchet adapters for languages other than Python: duplicates — jscpd, complexity — the project ESLint (JS/TS, understands TSX)
# and lizard (the rest), dead JS/TS code — knip. Each adapter returns {key: (signature, number|None)} or None — the tool is missing.
from __future__ import annotations

import re
import sys
import csv
import json
import shutil
import hashlib
import tempfile
import subprocess
from pathlib import Path
from collections import defaultdict

# Versions are pinned: a tool update changes findings without a code edit and breaks the lines
JSCPD, KNIP = 'jscpd@5.4.2', 'knip@6.43.0'
JS = {'.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts'}
LIZARD = {'.c': 'cpp', '.h': 'cpp', '.cc': 'cpp', '.cpp': 'cpp', '.hpp': 'cpp', '.cs': 'csharp', '.go': 'go', '.java': 'java',
          '.kt': 'kotlin', '.kts': 'kotlin', '.lua': 'lua', '.m': 'objectivec', '.php': 'php', '.rb': 'ruby', '.rs': 'rust',
          '.scala': 'scala', '.swift': 'swift', '.sol': 'solidity', '.erl': 'erlang', '.gd': 'GDScript', '.f90': 'fortran',
          '.js': 'javascript', '.ts': 'typescript'}
# jscpd format by extension: code only — JSON, YAML and translation texts are data, their repetition is not a duplicate of logic
JSCPD_FORMATS = {'.ts': 'typescript', '.mts': 'typescript', '.cts': 'typescript', '.tsx': 'tsx', '.js': 'javascript', '.mjs': 'javascript',
                 '.cjs': 'javascript', '.jsx': 'jsx', '.go': 'go', '.java': 'java', '.kt': 'kotlin', '.rs': 'rust', '.rb': 'ruby', '.php': 'php',
                 '.cs': 'csharp', '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.cc': 'cpp', '.hpp': 'cpp', '.swift': 'swift', '.scala': 'scala',
                 '.lua': 'lua', '.m': 'objectivec', '.sol': 'solidity', '.erl': 'erlang'}
COMPLEXITY = re.compile(r"^(.*?) has a complexity of (\d+)")

def run(cmd:list[str], cwd:Path, timeout:int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd = cwd, capture_output = True, text = True, timeout = timeout)

def rel(path:str|Path, root:Path, base:Path|None = None) -> str:
    p = Path(path)
    p = p if p.is_absolute() else (base or root) / p
    return p.resolve().relative_to(root).as_posix()

# Identical names in one file are told apart by ordinal number, not by line: an edit higher in the file does not redden
def numbered(rows:list[tuple[str, str, float|None]]) -> dict[str, tuple[str, float|None]]:
    seen, out = defaultdict(int), {}
    for key, label, score in rows:
        seen[key] += 1
        out[key + (f' #{seen[key]}' if seen[key] > 1 else '')] = (label, score)
    return out

# --- duplicates: jscpd for all formats except Python (Python has its own pass over statements)
def dup(root:Path, roots:list[Path], ignore:list[str], exts:set[str]) -> dict|None:
    formats = sorted({JSCPD_FORMATS[e] for e in exts if e in JSCPD_FORMATS})
    if not formats: return {}
    if not shutil.which('npx'): return None
    with tempfile.TemporaryDirectory() as out:
        cmd = ['npx', '--yes', JSCPD, '--silent', '--absolute', '--reporters', 'json', '--output', out, '--format', ','.join(formats), '--ignore', ','.join(ignore)]
        run(cmd + [str(r.resolve()) for r in roots], root)
        report = Path(out) / 'jscpd-report.json'
        if not report.exists(): return {}
        pairs = json.loads(report.read_text(encoding = 'utf-8')).get('duplicates', [])
    blocks = defaultdict(set)
    for d in pairs:
        digest = hashlib.sha1(' '.join(d.get('fragment', '').split()).encode()).hexdigest()[:10]
        for side in ('firstFile', 'secondFile'): blocks[(digest, d['lines'])].add((rel(d[side]['name'], root), d[side]['start']))
    return {f'{digest} {lines} ' + ' | '.join(sorted({p for p, _ in spots})): (f'{lines} lines: ' + ' == '.join(f'{p}:{s}' for p, s in sorted(spots)), None)
            for (digest, lines), spots in blocks.items()}

# JS/TS packages are directories with package.json; ESLint and knip are taken from the package itself
def packages(root:Path, files:list[Path]) -> dict[Path, list[Path]]:
    out = defaultdict(list)
    for f in files:
        pkg = next((d for d in f.parents if (d / 'package.json').exists() and 'node_modules' not in d.parts), None)
        if pkg and (pkg == root or root in pkg.parents): out[pkg].append(f)
    return out

def lcov(path:Path) -> dict[str, tuple[set[int], set[int]]]:
    files, name = {}, None
    for line in path.read_text(encoding = 'utf-8').splitlines():
        if line.startswith('SF:'): name = line[3:]; files[name] = (set(), set())
        elif line.startswith('DA:') and name:
            num, hits = line[3:].split(',')[:2]
            files[name][0 if int(hits) else 1].add(int(num))
    return files

def scored(c:int, first:int, last:int, lines:tuple[set[int], set[int]]|None, top:float) -> tuple[float, str]|None:
    if not lines: return (c, f'complexity {c}') if c >= top else None
    hit, miss = (len({n for n in s if first <= n <= last}) for s in lines)
    cov = hit / (hit + miss) if hit + miss else 0.0
    crap = round(c * c * (1 - cov) ** 3 + c, 1)
    return (crap, f'CRAP {crap} (complexity {c}, coverage {cov:.0%})') if crap >= top else None

# --- JS/TS complexity: the complexity rule of the project's own ESLint (its parser knows TS/TSX); with coverage — all functions for CRAP
def eslint_complexity(root:Path, files:list[Path], top:float, cover:dict) -> tuple[dict, list[Path]]:
    rows, missed = [], []
    for pkg, group in packages(root, files).items():
        bin_ = pkg / 'node_modules' / '.bin' / 'eslint'
        if not bin_.exists(): missed += group; continue
        floor = 0 if cover else int(top) - 1
        done = run([str(bin_), '--no-error-on-unmatched-pattern', '--rule', json.dumps({'complexity': ['warn', floor]}), '-f', 'json'] + [f.relative_to(pkg).as_posix() for f in group], pkg)
        try: report = json.loads(done.stdout)
        except json.JSONDecodeError: missed += group; continue
        for entry in report:
            path = rel(entry['filePath'], root)
            for m in sorted(entry.get('messages', []), key = lambda m: m.get('line', 0)):
                hit = COMPLEXITY.match(m.get('message', '')) if m.get('ruleId') == 'complexity' else None
                if not hit: continue
                name = (re.findall(r"'([^']+)'", hit[1]) or ['anonymous'])[0]
                got = scored(int(hit[2]), m.get('line', 0), m.get('endLine', m.get('line', 0)), cover.get(path), top)
                if got: rows.append((f'{path}::{name}', f'{path}:{m.get("line")} {got[1]}', got[0]))
    return numbered(rows), missed

# --- complexity of other languages: lizard (a Python package from the kit environment)
def lizard_complexity(root:Path, files:list[Path], top:float, cover:dict) -> dict|None:
    if not files: return {}
    try: import lizard  # noqa: F401
    except ImportError: return None
    done = run([sys.executable, '-m', 'lizard', '--csv'] + [f.relative_to(root).as_posix() for f in files], root)
    rows = []
    for rec in csv.reader(done.stdout.splitlines()):
        if len(rec) < 11: continue
        path, name, c, first, last = rel(rec[6], root), rec[7], int(rec[1]), int(rec[9]), int(rec[10])
        got = scored(c, first, last, cover.get(path), top)
        if got: rows.append((f'{path}::{name}', f'{path}:{first} {got[1]}', got[0]))
    return numbered(sorted(rows))

# --- dead JS/TS code: the package knip (unused files, exports, types, dependencies); report format — knip 6 json
def knip_dead(root:Path, files:list[Path]) -> tuple[dict|None, list[str]]:
    if not files: return {}, []
    if not shutil.which('npx'): return None, ['knip: no npx']
    allowed, groups = {rel(f, root) for f in files}, packages(root, files)
    rows, notes = [], [] if groups else ['dead: JS/TS without package.json, nothing for knip to read']
    for pkg in groups:
        done = run(['npx', '--yes', KNIP, '--reporter', 'json', '--no-progress', '--no-exit-code'], pkg)
        try: report = json.loads(done.stdout)
        except json.JSONDecodeError: notes.append(f'knip in {pkg.relative_to(root).as_posix() or "."}: did not run: ' + (done.stderr.strip().splitlines() or ['?'])[-1][:160]); continue
        for issue in report.get('issues', []):
            path = rel(issue['file'], root, pkg)
            # Tests, e2e configs and files outside roots are not debt: knip knows about them, the ratchet does not
            if path not in allowed: continue
            for kind, items in issue.items():
                if not isinstance(items, list): continue
                for item in items:
                    if kind == 'files': rows.append((f'{path} file', f'{path} file imported by nobody', None))
                    elif kind == 'duplicates': rows.append((f'{path}::' + '='.join(x['name'] for x in item) + ' duplicate', f'{path}:{item[0].get("line", "")} one export under the names ' + ', '.join(x['name'] for x in item), None))
                    elif isinstance(item, dict) and item.get('name'): rows.append((f'{path}::{item["name"]} {kind}', f'{path}:{item.get("line", "")} {kind}: {item["name"]}', None))
    return numbered(sorted(rows)), notes
