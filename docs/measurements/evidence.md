# Why the method is what it is — sources and measurements

For people: agents do not read this file. The rules these numbers back are in `skills/`.

The measurements were collected on one large project (September–October 2026); the full set with sources is kept by the owner outside this kit.

## Our spend (reference project, 18.09–18.10.2026, 2,056 agents, real 5.5 prices)
- ≈ $8.6 thousand/month: builders 42 %, main sessions 33 %, reviewers 12 %; cache reads 64 %, writes 29 %, answers 7 %.
- A main-session turn — on average 306 thousand context, 55 % of its money is its own reading and probes.
- Builders: 1.03 calls per turn; before the first edit a median of 23 turns; > 100 turns — 30 % of builders, 72 % of money.
- Roles without `tools:` start with ~46–49 thousand tokens of base, with a list — with 9–12 thousand (a conclusion, confirm by measurement).
- The 5-minute cache for subagents: misses ~0.2 per agent; the hourly one costs ×1.6 more to write — not a lever.
- Review: 61 of 123 milestones hit 3 rounds, the third round fixes a median of 1 finding; review = 0.31 of the build.

- Agents without a role (`general-purpose`, `claude`, empty `subagent_type`), 19–22.10.2026: 94 such agents on Opus —
  $308, 27 % of subagent spend.

## Prices per 1 million tokens (platform.claude.com, 2026-10)
Opus 5.5: input 4, output 20, 5-min write 5 / 1 h 8, read 0.20. Sonnet 5.5: 2 / 10 / 2.5 / 4 / 0.10.
Fable 5.1: 10 / 50 / 12.5 / 20 / 0.25.

## External sources
- Anthropic: an agent ~4× the tokens of a chat, a multi-agent system ~15×; the gain of multi-agent is in research, in code
  less is parallelised. The author does not judge their own work; re-measure the skeptic on every model. Opus 5.5 medium ≈
  Opus 5 high; `max` tends to change its mind.
- Agent teams on code — 3–7× the price of a single agent (ProgramBench); a cheap planner — 47.5 % of the gain for 13.9 %
  extra cost, a cheap executor lowers the result.
- Long context itself degrades work by 14–85 %; compaction loses constraints (violations 0 → 30–59 %) — hence short
  subtasks and `handoff` instead of a long-lived agent.
- MAST: a goal-level check +15.6 % success; superficial checkers are a frequent failure.
- Parallel writers: conflicts 41.7 % against 19.8 %; pre-divided zones — 9/9 clean builds against 1/9.
- Output compressors (rtk and the like): independent A/B — 0 or +6–8 % cost.
- Anthropic's official plugins (`code-review`, `feature-dev`, `math-olympiad`): found → verified → filtered out; an
  explicit "do not report" list; a checker without the author's reasoning, blind votes.

## Configuration trap
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` overrides `autoCompactWindow` in a role's frontmatter — while the variable is set, the
role's compaction window cannot be set (sub-agents.md).

## Practices (Reddit, HN, blogs — second pass, H; official plugins — G)
- A subagent is for context isolation, not for personas; in total it costs more (John Cook's measurement: parallel runs
  ×1.93 and ×3.11), a cold start ~37 thousand tokens, of which the task is ~3 %.
- Agent runaway is confirmed: recursive spawn at 1.2–4 million tokens (issue #68619), ultracode — 206 agents in one post.
  Limiters: `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (20), `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` (3), a ceiling on the
  number of agents in the plan, ~3 in parallel.
- A reviewer asked "where are the holes" always finds them → ask only about correctness and the stated requirements.
- Effort, single measurements of one order: medium $1.69 · high $2.30 · xhigh $4.99 on one task.
- `/clear` + a handover file is preferred by most over a long session with compaction (≥ 6 sources); compaction at 950
  thousand costs ~$60 at API prices.
- A 1-hour subagent cache is disputed: one report −75 % of writes, three — more expensive, one measurement −8.6 %.
- An allow-list of tools as a saving is not independently measured — we measure it ourselves.

## Measurement 27.10.2026: 43 builders of one milestone, $122
- Builders > 100 turns — 6 of 43 and 54 % of money; a turn up to the 50th $0.04, 50–100 $0.07, after 100 $0.11.
- Before the first edit — a median of 32 turns, 24 % of money; the scout's map in the brief — 7 of 43, scouts — 3.
- Extensions: early (an answer to a question before turn 40) 15 — cheap; late 5 — ~5 % of money. Three of the six big ones
  reached 100 turns without a single extension: the trouble is coarse slicing (gluing two plan items), not topping up.
- Recount on the same data: splitting the big ones in 2 at planning — ~11 % of builders' money; a hard limit of 100 + a
  fresh one for the remainder — ~9 % (overlaps, and a cut-off leaves a half-edit in the shared tree — not adopted); a late
  extension → fresh — ~5 %.
- Re-acceptance of the accepted (another agent harness, 10.2026): 265 agents, 122 reviews and audits — a loop.
- A main-session turn is 1.9 times more expensive than a builder's turn; 55 % of its money is its own code reading, base
  and scripts, orchestration — 10 %. Not levers (measured): the 1-hour cache for subagents, repeated reads, "output
  compressors" like context-mode.

## Numbers taken out of the rules (2026-10-28)
- orchestration §0: every agent turn re-reads everything accumulated — measured 2026-10: 64 % of spend is cache reads,
  29 % writes, answers 7 %.
- orchestration §2: roles without a tool list (`general-purpose`, `claude`, empty `subagent_type`) — see "Agents without
  a role" above.
- orchestration §5: a main-session turn is 1.9 times more expensive than a builder's turn.
- orchestration §6: builders made 1.03 calls per turn.
- review.md: 8 top models find 15–31 % of what humans found (SWE-PRBench); raw reviewers give twice as many "blockers"
  as there are (our measurement: of 99, 52 held); self-checked proofs 85.7 % → < 5 % when checked by humans; half of
  the milestones hit 3 rounds and the third round still finds a median of 1 finding.
- engineering pitfalls: `pgrep -f` waiter — measured 10.2026: three such waiters waited for a test run three hours after
  it ended.
- compact-now: auto-compact at about 804k / 80 % — measured 2026-08-05 from `preTokens` in the transcript, not at 900k.
- firecrawl: one site — 403 for WebFetch, 200 for Firecrawl.
