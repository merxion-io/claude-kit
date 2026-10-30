#!/usr/bin/env python3
# Code cleanliness ratchets for any project: duplicates, dead code, complexity (CRAP with coverage).
# A new finding outside the baseline goes red; one removed from the code requires striking its line — the line only gets thinner.
# Python has its own parsing; other languages — polyglot.py adapters (jscpd, the project ESLint, lizard, knip).
# Setup — .quality/config.toml or [tool.quality-gate] in pyproject.toml; without setup roots and languages are found automatically.
from __future__ import annotations

import io
import os
import re
import ast
import sys
import json
import shutil
import fnmatch
import hashlib
import argparse
import tokenize
import subprocess
from pathlib import Path
from itertools import combinations, count
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import polyglot

# Kit environment: vulture and lizard are installed once by the setup command, the project does not carry them
VENV = Path(__file__).resolve().parent / '.venv'
PINS = ['vulture==2.16', 'lizard==1.17.13']
SOURCES = {'.py'} | polyglot.JS | set(polyglot.LIZARD)
TEST_NAME = re.compile(r'(^test_|_test\.|\.test\.|\.spec\.|^conftest\.py$)')
TEST_DIRS = {'test', 'tests', '__tests__', 'spec', 'e2e', 'testdata', 'fixtures'}

SCOPES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
SKIP_DIRS = {'.git', '.venv', 'venv', 'env', 'node_modules', '__pycache__', 'build', 'dist', 'out', 'coverage', '.next', '.nuxt', 'target', 'vendor', '.tox', '.mypy_cache', '.pytest_cache', 'site-packages', 'migrations'}
NOISE = {tokenize.COMMENT, tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
# Called by the framework, not by code: web routes and hooks, pydantic validators, pytest fixtures, click/typer entry points
FRAMEWORK_DECORATORS = [f'@*.{verb}' for verb in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'route', 'api_route', 'websocket', 'middleware', 'exception_handler', 'on_event', 'command', 'callback', 'task', 'fixture')] + [
    '@field_validator', '@model_validator', '@field_serializer', '@model_serializer', '@computed_field', '@validator', '@root_validator', '@pytest.fixture', '@property']
SHAPES = {'BaseModel', 'TypedDict', 'NamedTuple', 'Enum', 'StrEnum', 'IntEnum', 'Flag', 'IntFlag'}
DEFINITIONS = {'function', 'method', 'class', 'property'}
FIX = {'dup': 'move the common part into one function and call it from both places',
       'dead': 'remove the symbol or connect it to the production path; if a framework calls it, add the decorator/name to the settings, not a line to the baseline',
       'complexity': 'split the function by meaning or cover it with tests (CRAP falls with coverage); replace a branch for one case with a seam'}

def repo_root(start:Path) -> Path:
    out = subprocess.run(['git', '-C', str(start), 'rev-parse', '--show-toplevel'], capture_output = True, text = True)
    return Path(out.stdout.strip()) if out.returncode == 0 else start.resolve()

def settings(root:Path, args:argparse.Namespace) -> dict:
    import tomllib
    conf = {}
    if (own := root / '.quality' / 'config.toml').exists(): conf = tomllib.loads(own.read_text(encoding = 'utf-8'))
    elif (py := root / 'pyproject.toml').exists(): conf = tomllib.loads(py.read_text(encoding = 'utf-8')).get('tool', {}).get('quality-gate', {})
    pick = lambda name, default: getattr(args, name) or conf.get(name.replace('_', '-'), conf.get(name, default))
    roots = pick('roots', None) or guess_roots(root)
    return {'roots': [root / r for r in roots], 'users': [root / u for u in (pick('users', None) or roots)], 'exclude': pick('exclude', []),
            'baseline_dir': root / pick('baseline_dir', '.quality'), 'window': int(pick('window', 6)), 'max': float(pick('complexity_max', 10)),
            'decorators': FRAMEWORK_DECORATORS + list(conf.get('dead-ignore-decorators', [])), 'names': list(conf.get('dead-ignore-names', [])),
            'confidence': int(conf.get('dead-confidence', 60)), 'coverage': args.coverage or conf.get('coverage')}

# Without setup: top-level directories with sources of any known language, except tests and environments
def guess_roots(root:Path) -> list[str]:
    tops = {p.relative_to(root).parts[0] for p in walk(root) if len(p.relative_to(root).parts) > 1}
    return sorted(t for t in tops if not t.startswith('.') and t not in TEST_DIRS) or ['.']

def walk(base:Path):
    for d, dirs, names in os.walk(base):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith('.')]
        yield from (Path(d) / n for n in names if Path(n).suffix in SOURCES)

# Tests are not prod: their functions are not "users" of code, their duplicates and complexity are not engine debt
def is_test(p:Path) -> bool: return bool(TEST_NAME.search(p.name)) or bool(TEST_DIRS & set(p.parts))

def files_of(conf:dict, exts:set[str] = frozenset({'.py'}), roots:list[Path]|None = None) -> list[Path]:
    out = []
    for base in roots or conf['roots']:
        paths = [base] if base.is_file() else walk(base)
        out += [p for p in paths if p.suffix in exts and not is_test(p) and not any(fnmatch.fnmatch(p.as_posix(), g) for g in conf['exclude'])]
    return sorted(set(out))

def ignore_globs(conf:dict) -> list[str]:
    return [f'**/{d}/**' for d in SKIP_DIRS | TEST_DIRS] + ['**/test_*', '**/*_test.*', '**/*.test.*', '**/*.spec.*'] + list(conf['exclude'])

# File scopes: (first line with decorators, last, dotted name, node)
def scopes(tree:ast.AST, chain:tuple = ()) -> list[tuple[int, int, str, ast.AST]]:
    return [span for node in ast.iter_child_nodes(tree) for span in (scope(node, chain + (node.name,)) if isinstance(node, SCOPES) else scopes(node, chain))]

def scope(node:ast.AST, qual:tuple) -> list[tuple[int, int, str, ast.AST]]:
    return [(min([node.lineno] + [d.lineno for d in node.decorator_list]), node.end_lineno, '.'.join(qual), node)] + scopes(node, qual)

def scope_at(spans:list, line:int) -> tuple[str, ast.AST|None]:
    inner = max((s for s in spans if s[0] <= line <= s[1]), key = lambda s: s[0], default = (0, 0, '', None))
    return inner[2], inner[3]

# The finding key is the path and symbol name, not the line number: an edit higher in the file does not redden the guard
def symbol(rel:str, *names:str) -> str: return '::'.join([rel, qual] if (qual := '.'.join(n for n in names if n)) else [rel])

# --- duplicates: windows of logical lines by tokens, without comments and imports
def statements(source:str) -> list[tuple[int, str]]:
    lines, tokens = [], []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.NEWLINE:
            if tokens and tokens[0].string not in ('import', 'from'): lines.append((tokens[0].start[0], ' '.join(t.string for t in tokens)))
            tokens = []
        elif token.type not in NOISE: tokens.append(token)
    return lines

# Pairs of matched windows are merged into the largest block; a window overlapping its own copy is not a duplicate
def duplicates(files:dict[str, list[tuple[int, str]]], window:int) -> dict[str, tuple[int, list[tuple[str, int]]]]:
    windows = defaultdict(list)
    for rel, lines in files.items():
        for i in range(len(lines) - window + 1): windows['\n'.join(text for _, text in lines[i:i + window])].append((rel, i))
    pairs = {(a, b) for spots in windows.values() for a, b in combinations(spots, 2) if a[0] != b[0] or b[1] - a[1] >= window}
    blocks = defaultdict(set)
    for (ra, ia), (rb, ib) in pairs:
        if ((ra, ia - 1), (rb, ib - 1)) in pairs: continue
        size = next(k for k in count(1) if ((ra, ia + k), (rb, ib + k)) not in pairs) + window - 1
        digest = hashlib.sha1('\n'.join(text for _, text in files[ra][ia:ia + size]).encode()).hexdigest()[:10]
        blocks[(digest, size)] |= {(ra, files[ra][ia][0]), (rb, files[rb][ib][0])}
    return {digest: (size, sorted(spots)) for (digest, size), spots in blocks.items()}

def check_dup(conf:dict, root:Path) -> tuple[dict, list[str]]:
    found, notes = py_dup(conf, root), []
    if (exts := {p.suffix for p in files_of(conf, SOURCES - {'.py'})}):
        other = polyglot.dup(root, conf['roots'], ignore_globs(conf), exts)
        if other is None: notes.append('dup: other languages skipped, no npx (Node.js) for jscpd')
        else: found |= other
    return found, notes

def py_dup(conf:dict, root:Path) -> dict[str, tuple[str, float|None]]:
    sources = {p.relative_to(root).as_posix(): p.read_text(encoding = 'utf-8') for p in files_of(conf)}
    spans = {rel: scopes(ast.parse(src)) for rel, src in sources.items()}
    blocks = duplicates({rel: statements(src) for rel, src in sources.items()}, conf['window'])
    found = {}
    for digest, (size, spots) in blocks.items():
        key = f'{digest} {size} ' + ' | '.join(symbol(rel, scope_at(spans[rel], line)[0]) for rel, line in spots)
        found[key] = (f'{size} statements: ' + ' == '.join(f'{rel}:{line}' for rel, line in spots), None)
    return found

# --- dead code: vulture from production "users" of code, framework frames removed by rules
def tail(node:ast.expr) -> str:
    node = node.func if isinstance(node, ast.Call) else node.value if isinstance(node, ast.Subscript) else node
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, 'id', '')

# Schema fields are read by serialization and the constructor by name, not by dot access
def shape_classes(trees:list[ast.AST]) -> set[str]:
    classes = [node for tree in trees for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    shapes = SHAPES | {c.name for c in classes if 'dataclass' in map(tail, c.decorator_list)}
    while (grown := {c.name for c in classes if c.name not in shapes and shapes & set(map(tail, c.bases))}): shapes |= grown
    return shapes

def check_dead(conf:dict, root:Path) -> tuple[dict, list[str]]:
    found, notes = {}, []
    if files_of(conf):
        py = py_dead(conf, root)
        if py is None: notes.append('dead: Python skipped, no vulture; once: python3 ~/.claude/tools/quality/gate.py setup')
        else: found |= py
    js, js_notes = polyglot.knip_dead(root, files_of(conf, polyglot.JS))
    notes += js_notes
    if js is None: notes.append('dead: JS/TS skipped, no npx (Node.js) for knip')
    else: found |= js
    if (rest := {p.suffix for p in files_of(conf, SOURCES - {'.py'} - polyglot.JS)}): notes.append(f'dead: no adapter for {", ".join(sorted(rest))}, tools in skills/engineering/references/gates.md')
    return found, notes

def py_dead(conf:dict, root:Path) -> dict[str, tuple[str, float|None]]|None:
    try: import vulture
    except ImportError: return None
    scan = vulture.Vulture(ignore_names = conf['names'], ignore_decorators = conf['decorators'])
    scan.scavenge([str(p) for p in conf['users']], exclude = conf['exclude'])
    trees = {str(p): ast.parse(p.read_text(encoding = 'utf-8')) for p in files_of(conf)}
    spans, shapes = {path: scopes(tree) for path, tree in trees.items()}, shape_classes(list(trees.values()))
    rows = []
    for item in scan.get_unused_code(min_confidence = conf['confidence']):
        if str(item.filename) not in spans: continue
        rel = Path(item.filename).resolve().relative_to(root).as_posix()
        qual, owner = scope_at(spans[str(item.filename)], item.first_lineno)
        if item.typ == 'variable' and isinstance(owner, ast.ClassDef) and owner.name in shapes: continue
        rows.append((symbol(rel, *((qual,) if item.typ in DEFINITIONS else (qual, item.name))) + ' ' + item.typ, f'{rel}:{item.first_lineno} {item.message}'))
    rows.sort()
    # Identical findings in one symbol are told apart by ordinal number
    names = [name for name, _ in rows]
    return {name + (f' #{n}' if (n := names[:i + 1].count(name)) > 1 else ''): (where, None) for i, (name, where) in enumerate(rows)}

# --- complexity: cyclomatic by McCabe; with a coverage.py json report — CRAP = c² · (1 − cov)³ + c
def complexity(node:ast.AST) -> int:
    score = 1
    for child in walk_own(node):
        if isinstance(child, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.Assert, ast.match_case)): score += 1
        elif isinstance(child, ast.BoolOp): score += len(child.values) - 1
        elif isinstance(child, ast.comprehension): score += 1 + len(child.ifs)
    return score

# A nested function and class are their own scopes with their own count
def walk_own(node:ast.AST):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, SCOPES): continue
        yield child
        yield from walk_own(child)

# Coverage: coverage.py json (Python) and/or lcov .info (JS/TS, Go, Rust, Java, … — a common format); a list is allowed
def coverage_of(conf:dict, root:Path) -> dict[str, tuple[set[int], set[int]]]:
    out = {}
    for item in ([conf['coverage']] if isinstance(conf['coverage'], str) else conf['coverage'] or []):
        path = root / item
        if path.suffix == '.json':
            for name, f in json.loads(path.read_text(encoding = 'utf-8'))['files'].items(): out[polyglot.rel(name, root)] = (set(f['executed_lines']), set(f['missing_lines']))
        else: out |= {polyglot.rel(name, root): lines for name, lines in polyglot.lcov(path).items()}
    return out

def check_complexity(conf:dict, root:Path) -> tuple[dict, list[str]]:
    cover, notes = coverage_of(conf, root), []
    found = py_complexity(conf, root, cover)
    js, missed = polyglot.eslint_complexity(root, files_of(conf, polyglot.JS), conf['max'], cover)
    found |= js
    # A package without its own ESLint — its .js/.ts is counted by lizard (lizard does not parse TSX/JSX)
    rest = files_of(conf, set(polyglot.LIZARD) - polyglot.JS) + [f for f in missed if f.suffix in ('.js', '.ts')]
    if (skipped := [f for f in missed if f.suffix not in ('.js', '.ts')]): notes.append(f'complexity: {len(skipped)} JSX/TSX files without ESLint in the package, not measured')
    other = polyglot.lizard_complexity(root, rest, conf['max'], cover)
    if other is None: notes.append('complexity: other languages skipped, no lizard; once: python3 ~/.claude/tools/quality/gate.py setup')
    else: found |= other
    return found, notes

def py_complexity(conf:dict, root:Path, cover:dict) -> dict[str, tuple[str, float|None]]:
    found = {}
    for path in files_of(conf):
        rel = path.relative_to(root).as_posix()
        for first, last, qual, node in scopes(ast.parse(path.read_text(encoding = 'utf-8'))):
            if isinstance(node, ast.ClassDef): continue
            got = polyglot.scored(complexity(node), first, last, cover.get(rel), conf['max'])
            if got: found[symbol(rel, qual)] = (f'{rel}:{first} {got[1]}', got[0])
    return found

CHECKS = {'dup': check_dup, 'dead': check_dead, 'complexity': check_complexity}

# Baseline line: "key" or "key<TAB>number" — the number of complexity cannot grow
def read_baseline(path:Path) -> dict[str, float|None]:
    if not path.exists(): return {}
    rows = (raw.rstrip('\n') for raw in path.read_text(encoding = 'utf-8').splitlines())
    return {key: float(val) if val else None for key, _, val in (row.partition('\t') for row in rows if row.strip() and not row.startswith('#'))}

def write_baseline(path:Path, found:dict, name:str) -> None:
    path.parent.mkdir(parents = True, exist_ok = True)
    head = f'# Ratchet debt {name}: a line goes when the finding is removed from the code; new lines are not added here, they get fixed\n'
    path.write_text(head + ''.join(f'{k}\t{v:g}\n' if v is not None else f'{k}\n' for k, (_, v) in sorted(found.items())), encoding = 'utf-8')

def verdict(name:str, found:dict, known:dict, baseline:Path) -> list[str]:
    fresh = [f'{found[k][0]}  [{k}]' for k in sorted(found.keys() - known.keys())]
    worse = [f'{found[k][0]} — was {known[k]:g}  [{k}]' for k in sorted(found.keys() & known.keys()) if known[k] is not None and found[k][1] is not None and found[k][1] > known[k]]
    gone = sorted(known.keys() - found.keys())
    out = []
    for title, rows in ((f'{name}: new (not in {baseline.name}) — {FIX[name]}', fresh), (f'{name}: grew above the baseline — {FIX[name]}', worse), (f'{name}: removed from the code — strike the line from {baseline}', gone)):
        if rows: out.append(f'{title}:\n  ' + '\n  '.join(rows))
    return out

def main() -> int:
    ap = argparse.ArgumentParser(description = 'Code cleanliness ratchets: dup | dead | complexity | all')
    ap.add_argument('check', choices = [*CHECKS, 'all', 'setup'])
    ap.add_argument('--project', default = '.', help = 'project directory (default: current; the git root is taken)')
    ap.add_argument('--roots', nargs = '*', help = 'directories/files to check, relative to the root')
    ap.add_argument('--users', nargs = '*', help = 'dead: production code whose calls count (default = roots)')
    ap.add_argument('--exclude', nargs = '*', help = 'glob exclusions by path')
    ap.add_argument('--baseline-dir', dest = 'baseline_dir', help = 'baseline directory (default .quality/)')
    ap.add_argument('--window', type = int, help = 'dup: window size in statements (6)')
    ap.add_argument('--complexity-max', dest = 'complexity_max', type = float, help = 'complexity or CRAP threshold (10)')
    ap.add_argument('--coverage', help = 'complexity: coverage.py json (coverage json -o …), computes CRAP')
    ap.add_argument('--init', action = 'store_true', help = 'record current findings as debt (only when connecting)')
    args = ap.parse_args()
    if args.check == 'setup': return setup()
    root = repo_root(Path(args.project))
    conf = settings(root, args)
    problems = []
    for name in (CHECKS if args.check == 'all' else [args.check]):
        (found, notes), path = CHECKS[name](conf, root), conf['baseline_dir'] / f'{name}.txt'
        for note in notes: print('⚠ ' + note, file = sys.stderr)
        if args.init:
            write_baseline(path, found, name)
            print(f'{name}: debt recorded, {len(found)} lines in {path}')
            continue
        problems += verdict(name, found, read_baseline(path), path)
        print(f'{name}: findings {len(found)}, in the baseline {len(read_baseline(path))}', file = sys.stderr)
    print('\n\n'.join(problems) if problems else 'clean')
    return 1 if problems else 0

def setup() -> int:
    if not (VENV / 'bin' / 'python').exists(): subprocess.run([sys.executable, '-m', 'venv', str(VENV)], check = True)
    subprocess.run([str(VENV / 'bin' / 'python'), '-m', 'pip', 'install', '-q', '--disable-pip-version-check'] + PINS, check = True)
    print(f'done: {", ".join(PINS)} in {VENV}' + ('' if shutil.which('npx') else ' · JS/TS and duplicates of other languages need Node.js (npx)'))
    return 0

# The kit environment exists — we work in it (vulture and lizard are there), the project does not give out its own environment
def in_venv() -> None:
    py = VENV / 'bin' / 'python'
    # The environment Python is a link to the system one: "already inside" is decided by sys.prefix, not by the interpreter path
    if py.exists() and Path(sys.prefix).resolve() != VENV.resolve() and not os.environ.get('QUALITY_GATE_NO_VENV'):
        os.execv(str(py), [str(py), __file__] + sys.argv[1:])

if __name__ == '__main__':
    in_venv()
    sys.exit(main())
