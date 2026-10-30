# Quality ratchets

Debt in a baseline: **a new finding goes red, a fixed one requires crossing out its line**. Key = path + symbol name
(repeats `#2`), not the line. Never top the baseline up by hand.

## `~/.claude/tools/quality/gate.py` (any language)

```
python3 ~/.claude/tools/quality/gate.py setup                     # once per machine: vulture and lizard into the kit environment
python3 ~/.claude/tools/quality/gate.py dup|dead|complexity|all [--project DIR] [--init]
```
Tests (`test_*`, `*.test.*`, `*.spec.*`, `tests/`, `e2e/`) are excluded.

| check | Python | JS / TS / TSX | other languages |
|---|---|---|---|
| `dup` | own pass: windows of 6 statements | jscpd | jscpd |
| `complexity` | own McCabe | the package's own `complexity` ESLint rule; without ESLint lizard | lizard |
| `dead` | vulture from the live "users" | the package's knip | no adapter: tools below |

- `complexity` threshold 10; with coverage CRAP = c²·(1−cov)³ + c (`coverage.json` and/or `lcov.info`); may not grow past
  the baseline.
- No tool (Node.js, kit environment) → the language's check is skipped with a warning.
- Versions pinned.
- `--init` records current debt; hookup only.
- Config `.quality/config.toml` or `[tool.quality-gate]` in `pyproject.toml`; without it roots are found automatically (top-level directories with sources); keys `roots`, `users` (dead Python: code
  whose calls count), `exclude`, `complexity-max`, `coverage`, `dead-ignore-decorators`. Baselines `.quality/dup.txt`,
  `dead.txt`, `complexity.txt` are in git.
- Guard: a test running `gate.py all` and asserting returncode 0 (JS: script `"quality": "python3 ~/.claude/tools/quality/gate.py all"` in `package.json` + CI step).
  An existing project guard of the kind stays; no second home.

## `~/.claude/tools/quality/sabotage.py`

```
python3 ~/.claude/tools/quality/sabotage.py FILE --find "exact fragment" --replace "broken" [--expect test_name ...] -- <test command>
```
Clean run first (must be green); substitute; run; file always restored, `.pyc` removed. Exit 0 — the guard sees; 1 —
blind or the wrong thing went red.

## Other tools

- duplicates: `jscpd` (150+ languages), `dupl` (Go), PMD CPD (JVM)
- dead code: `knip`, `ts-prune` (JS/TS), `deadcode`, `staticcheck` U1000 (Go), IntelliJ inspections, detekt `unused` (JVM)
- complexity: ESLint `complexity` (JS/TS), `gocyclo` (Go), PMD, detekt (JVM), `lizard` (many languages)
- mutations: Stryker, `go-mutesting`, PIT; coverage: `c8`/`istanbul`, `go test -cover`, JaCoCo

Any of them: findings → stable keys (path + symbol) → the baseline scheme above (new red, vanished crossed out).

## Mutation testing

`mutmut`/`cosmic-ray`: run on the edit's zone; cover surviving mutants or delete the dead code.
