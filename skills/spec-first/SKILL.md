---
name: spec-first
description: "For repos where behaviour is written into a spec first (OpenSpec, ADR, RFC, docs/specs): proposal, delta, code, merge into live specs, archive. Load when the repo has a spec or proposal directory and you change behaviour or write or close a proposal. Triggers: spec, delta, archiving, removing a mechanism, delta merge"
---

# Spec-first

Flow: proposal + spec delta → code → delta merged into the live spec → proposal archived. Concrete paths, validator commands and format: the project's `CLAUDE.md` and skills. OpenSpec: `specs/<capability>/spec.md` (live), `changes/<name>/`
(proposal, tasks, deltas), `changes/archive/`.

## 0. Adjust to the project

Find: specs dir, validator + pinned version, decisions log, parameter owners, closing rule (default
`orchestration/references/closing.md`).

## Spec and code disagree

Trust neither: check by command, name the discrepancy; the owner decides. A lie (spec states what does not exist) is not a gap (spec is silent). Verify spec claims ("already done", "guarded by a test") against the code BEFORE the plan.

## Delta: MODIFIED drags a stale line along

A rewritten requirement carries live text verbatim, wording being removed included. After the delta `grep` the
decision-carrying word (old name, parameter name) across ALL delta files: requirement prose, scenarios, parameter table. One name for declaration, prose and code.

## Archiving — five steps

Code shipped → close at once.
1. **Merge the deltas BY HAND into the live specs** (requirements, scenarios, parameters). Moving the folder
   merges nothing. Tool "archive" only if it leaves others' uncommitted edits alone.
2. **Validator green** on the whole set (judges FORM only).
3. **Move to the archive** (`git mv` to `archive/<date>-<name>`). Empty move: name in the message the commit that merged the delta.
4. **One commit carries merged spec and move:** `git status` clean, `git show --name-only HEAD` has both; item
   checkmarks are in the index before the move.
5. **All plan items closed** per the closing rule.

## Merging — by substance

- REMOVED lines disappear from the live spec.
- A requirement the code does not execute is not carried in as executed.
- Prose quoting a changed requirement: `grep` its name in all specs.
- No bulk re-pour of the archive: item by item.

## Removing a mechanism

Owner decision → decisions log: what, why, **a probe against its return** (command or test red if it comes back)
and a "Forbidden in live specs" line (projects grep this literal; a project already grepping its own wording keeps it). Clear traces in ONE exhaustive pass: `grep` code, UI
with translations, specs, tests, fixtures, comments; a verdict on every hit; one wave of edits; list what stayed.

## Parameters

One number — one owner spec (its parameter table); code reads it from one registry, no copies. New parameter: owner spec → registry → consumer.

## Validator

Pin the version; probe the fresh one separately; upgrade by decision.
