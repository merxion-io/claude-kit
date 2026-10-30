---
name: engineering
description: "How to write and review code: first it works, then it's right, then practice. Load before any code edit, review, test or subtask plan; builder/code-reviewer load it themselves. Triggers: code edit, review, refactoring, tests, sabotage, ratchet, duplicates, dead code, stuck point"
---

# Engineering

Traps: `references/pitfalls.md`.

## 0. Project
First find: truth about behaviour (spec, README), style/helpers (`CLAUDE.md`, `AGENTS.md`, linter), test commands (zone, full), ratchets (`.quality/`, CI), shared tree? Project rules outrank and extend this.

## 1. It works
- **One decision — one place.** Before a new rule find where it lives and call it. Second consumer → shared module, old copy removed in the same edit. A second home or judge is a defect.
- **Smallest edit,** no refactoring "while here", no neighbouring tasks. Ladder: project helper → stdlib/platform → installed dependency → one line → minimal code; no dependency for a couple of lines. All the contract/brief requires is done in full; the rest is not (name it).
- **Never cut:** input validation, data-saving error handling, security, accessibility, what was asked; moved or merged code keeps its checks and error handling.
- **Data shape first:** make the invalid unrepresentable (type, registry enum, schema).
- **No bolting:** build as if the new requirement had been there from the start, delivered in pieces; a flag or branch for one case instead of a seam by meaning is a patch. Removals first, same edit.
- **A blocker:** root-cause breakdown per «A stuck point is worked through to the end» in `~/.claude/CLAUDE.md`; two edits with a common premise failed at one gate → state the premise in one sentence, attack it; no third edit.
- **One case by hand, then a tool.**
- **Boundary:** external data is validated and parsed once, at entry. Business rule = pure function, I/O at edges. Never silence compiler/linter.
- **Idempotency:** repeat/restart ends in the same state; "already done" = atomic claim in the store.
- **Shared state:** each its own; if shared — one writer, held by the structure, not an agreement.
- **External API:** vendor docs first; library behaviour: probe, then code.

## 2. It's right
- **Fix the cause:** reproduce → find → fix; a stub, fallback or `try/except` hiding a failure is no fix.
- **Test behaviour** as the user calls it, no private symbols; drop a test passing if functions return nothing.
- **Failing test before the edit** when an honest one is possible: see it fail for the expected reason.
- **Sabotage is mandatory:** break code → exactly YOUR tests go red → file restored (`~/.claude/tools/quality/sabotage.py`). Blind guard: fixture shorter than the subject, or the compared value never changes.
- **Refactoring:** pin behaviour by test → change structure → behaviour unmoved.
- **Ratchets** (`references/gates.md`: duplicates, dead code, complexity/CRAP): new finding red, debt thins. Complexity threshold 10; with coverage
  CRAP = c²·(1−cov)³ + c.
- **Garbage pass:** linter, compiler, orphaned imports/functions, no TODO, commented-out code, empty bodies.

## 3. Practice
- **Small verifiable steps:** finish a unit, check, next; subtask = 1–3 files + tests.
- **Commit by named paths:** what, why, proof. Into main and outward — only on owner's word.
- **Tests:** zone while working, full suite once before merge or build; don't kill others' runs; scripts under `timeout`, `ulimit -v`.
- **Green = the runner's summary line** («N passed» / «N failed» / `FAIL`), not the exit code (in `tests | tail` it is `tail`'s) — or enable `set -o pipefail`; deciding command last.
- **Journal:** what was done and why, in readable phrases — in the commit, plan item closing, status file.
- **Save context:** ranges, `| head`/`| tail`; wide search → agent (`orchestration`).
- **Close background work at once:** agent reported → close; waiter unneeded → remove.
- **Cleanup:** delete only the verified unneeded; others' uncommitted work waits for its owner.
