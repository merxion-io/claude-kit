---
name: orchestration
description: "Orchestrate agents: delegation, roles, models, review, briefs, Workflow. Load FIRST when leading a milestone or as orchestrator (before reading code/specs) and before the first Agent or Workflow. Triggers: agents, orchestrator, milestone, brief, scouting, builder, reviewer, delegate"
---

## 0. Project first
Read `CLAUDE.md`/`AGENTS.md`/`README` (behaviour truth, style, git/test rules, don't-touch), `.claude/skills|agents` (project rules, same-name roles win), test commands, `git status`/`git worktree list` (shared → commit by paths) → "Project:".

## 1. Delegate or not
- **Milestone orchestrator = team lead.** Yours: git/board decisions, plan, briefs, acceptance, operator (executor: via observer, by its role text); their operations > 2 turns → agent (`references/routing.md`). Not yours: code/specs "for understanding" >~150 lines → `scout`; edits → `builder`; long run → background. "Faster myself" doubt → delegate, but agent ≈ $3–7: pays off over one window or a long routine tail; dependent chain in one window — yourself.
- **Yourself (no milestone):** question, bugfix, 1–3 files, frequent operator dialogue, shared-context phases (agent start ~10–50k tokens). **Agent:** wide search, fresh look, independent zones; returns JSON ≤ 1–2k tokens or file; take only JSON, data stays in its file, not your context.
- One writer per file, parallel only on disjoint files; reading and review free. Agent ceiling in plan.
- Executor: hooks hold this (`tools/write_guard.py`) — in any project, your own writes inside a git repository (except `*.md`, `.claude/checkpoints/`, the project's "open" paths) are denied from your first action, loaded or not.

## 2. Roles (`~/.claude/agents/`); kind → model/effort: `references/routing.md`
| role | model | effort |
|---|---|---|
| `scout` | sonnet | low |
| `builder` | opus; mechanics — sonnet | medium |
| `code-reviewer` | opus; mechanical milestone — sonnet + one opus gate round after `ready` | high |
| `verifier` | sonnet | medium |
| `spec-reviewer` / `spec-auditor` | opus high / sonnet medium | — |

- Error costs more than a turn → expensive model, else cheap; effort is a lever equal to model; re-asked/redone > 1 in 3 → wrong choice, a Sonnet row back to Opus.
- Only these roles (or project's): `general-purpose`, `claude`, empty `subagent_type` forbidden; `model`, `effort` in every call. Code → `builder`, search → `scout`, check → `code-reviewer`/`verifier`; none fits → `builder` with brief.

## 3. The loop
1. **Scout:** don't search code yourself; no builder brief without map; one map per milestone (file), path in every brief; new zone extends it, not builder search.
2. **Plan:** from map read pointwise (≤ 150 lines). Subtask = verifiable unit, **~50–60 turns** (ceiling 100, then `handoff`); more → seam or whole; extension, escalation, economy: `references/slicing.md`. Mixed subtask → cut first: judgment → Opus, mechanical tail (ticks, delta merge, archive, labelling) → separate Sonnet builder after the logic; "doubt → opus" only without a seam.
3. **Builders:** parallel, disjoint files; `git status --short`; `done:false` → `handoff` to new.
4. **Review** (`references/review.md`): `fixed` → fresh reviewer on diff since last round; `ready` → exit. **≤ 3 rounds**; proven blocker in third = design defect, yours.
5. **Acceptance:** `git diff --stat`, reports, risky hunks/key functions by eye; tests are truth, not reviewer opinion; full suite once pre-merge; re-verify only on command-shown breakage. Commit each accepted subtask by project rules, paths by name; no uncommitted pile.
6. **Close milestone** only when ALL items closed (`references/closing.md`).

## 4. The brief

```
Kind: <row of references/routing.md; Step:/Why: lines by it>
Project: <truth, tests, git, bans — §0>
Subtask: <what becomes true, one sentence>
Write ONLY: <paths>
Map: <slice of the scout JSON>
Contract: <spec anchor + quote ≤ 30 lines>
Acceptance: <command> → "N passed"; which guards go red under sabotage
Do not: <adjacent work; others' files by name>
Access: <prod DBs/containers; no credential hunting; no writes outside>
Report: JSON, role schema; long → file
```
Brief text in English, operator quotes verbatim. Long brief → file, path in prompt; "Access" mandatory; don't retell role or style.

## 5. Hygiene
- Probes `| tail -20` or agent answering in 5–10 lines; background → wait for notification; close finished agents; blocker only if command-shown; no restriction the operator did not set.
- Task folder, status, candidate copies: `references/closing.md` §Traces.
- Workflow only on operator's explicit word ("workflow", "as a wave", `ultracode`): `references/workflow.md`.
- After method change compare price per closed subtask, review rounds: `python3 ~/.claude/tools/token-spend.py --since <date> [--project=<folder in ~/.claude/projects>]`
