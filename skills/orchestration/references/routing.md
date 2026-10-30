# Kind of work → model and effort

Rule: `SKILL.md` §2. A cheap model suits search and planning, not implementing logic. **Opus:** unclear spec, transactions, concurrency, schema/SQL, money, security, judgment, new work without a pattern; doubt → opus. Effort = the role's default (scout low, builder medium, review high); other than the row (a high builder, opus for a complex layout) only with a `Why: …` line in the brief. Turns = usual / long case; more than the ceiling → cut the subtask smaller. The kind name in brackets (none: the name itself) is how `tools/task-kinds.py` prints it; volume: agent kinds — its runs for 14 days, orchestrator operations — your own main-session turns / $ for 7 days, one project's dev (`--ops`); refresh: `python3 ~/.claude/tools/task-kinds.py [--ops] --since <date> [--project=<folder>]`; cheapen where the volume is.

Orchestrator operations (the rows with Series): more than Series turns of one in a row → not in your long context: a short agent (`builder`) does it and returns a 5–10 line result; decisions (what to commit, which status) stay yours. Role: a row with a role needs no `Kind:` line — the call's `subagent_type` finds it. Steps: a row with them gets one builder per step, its brief has `Step: <one of them>`. `hooks/agent-guard.py` reads this table (`tools/routing.py`): a row edited here changes its decision.

| Kind | Role | When | Model | Effort | Plan for turns | Ceiling | Volume | Series | Steps |
|---|---|---|---|---|---|---|---|---|---|
| git and commit (git) | — | status, log, diff; commit of named paths | sonnet | medium | — | 30 | 1024 turns / $114 | 2 | — |
| containers (containers) | — | logs, status, exec, restart of containers; a production write — the rollout row (opus) | sonnet | medium | — | 30 | 551 turns / $46 | 2 | — |
| build and test run | — | run a given command, return the tail | sonnet | medium | — | 30 | 106 turns / $9 | 2 | — |
| watching background work (watch background) | — | wait for a condition, read the output | sonnet | medium | — | 30 | 56 turns / $4 | 2 | — |
| the board (board) | — | card status, comment, milestone | sonnet | medium | — | 30 | 73 turns / $7 | 2 | — |
| files and cleanup | — | move, copy, delete, permissions | sonnet | medium | — | 30 | 108 turns / $9 | 2 | — |
| config files | — | json, yaml, toml, env by a decision | sonnet | medium | — | 30 | 3 turns / $0 | 2 | — |
| ticks, report, board card | — | tick decided items, write the milestone report by results, update the card | sonnet | medium | — | 100 | 1 run | — | — |
| map/scouting | — | find where code, tests, spec anchors live; no edits | sonnet | low | 8 / 24 | 40 | 85 runs | — | — |
| reference labelling | — | label cases of a reference set by a given rule | sonnet | medium | 17 / 52 | 100 | 91 runs | — | — |
| delta merge and archive | — | merge decided spec deltas into live specs, archive the proposal | sonnet | medium | 21 / 98 | 100 | 25 runs | — | — |
| cleanup/transfer/indexes | — | remove, rename, move, re-index by a decided pattern | sonnet | medium | 38 / 102 | 100 | 89 runs | — | — |
| tests by contract | — | tests for a contract already decided | sonnet | medium | 34 / 96 | 100 | 23 runs | — | — |
| cabinet/UI | — | screens and components by a design; complex layout — opus | sonnet | medium | 38 / 98 | 100 | 61 runs | — | — |
| proposal and spec deltas | — | write a proposal or spec delta for new behaviour | opus | medium | 59 / 109 | 100 | 158 runs | — | — |
| measurement/live run | — | a live run or a measurement on real data | opus | medium | 48 / 119 | 100 | 95 runs | — | — |
| production rollout | — | each step its own builder | opus | medium | — | 100 per step | 3 runs | — | build/migrate/swap/verify |
| engine logic | — | logic, schema, SQL, money, concurrency | opus | medium | 58 / 127 | 100 | 305 runs | — | — |
| review round | — | a fresh review of a round's diff | opus | high | 46 / 77 | 100 | 293 runs | — | — |
| fix after review | — | fix proven findings of a review | the original edit's | medium | 32 / 56 | 100 | 6 runs | — | — |
| Claude Code docs (claude-code-guide) | claude-code-guide | a question about Claude Code, the Agent SDK, the API | sonnet | low | — | 30 | — | — | — |
| wide search (Explore) | Explore | a read-only sweep of many files for a conclusion | sonnet | low | — | 30 | — | — | — |
| implementation plan (Plan) | Plan | a plan of an implementation, critical files, trade-offs | opus | medium | — | 30 | — | — | — |
| status line setup (statusline-setup) | statusline-setup | configure the status line setting | sonnet | low | — | 30 | — | — | — |
| web page (web-fetch) | web-fetch | read a known URL and answer | sonnet | low | — | 30 | — | — | — |

Main-session context: auto-compact window 400k (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`, the operator's choice) — `~/.claude/docs/measurements/auto-compact-2026-10-29.md`.
