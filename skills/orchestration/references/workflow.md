# Workflow: rules and template

Docs: code.claude.com/docs/en/workflows; API: skill `/workflow-authoring`.

- Only on the operator's explicit word. For: audit, wide review, refutation, uniform work over many elements, a build by a plan known in advance. Stages needing the
  operator's decision → separate workflows (no questions mid-run).
- The whole result lands in the main context → return short JSON, long output to a file.
- Script has no shell/files (agents do those), no `import()`; `Date.now()`/`Math.random()` throw — pass time via `args`.
- ≤ 16 agents at once, 1,000 per run; agents of one role/model/tools share the first one's cache prefix.
- Restart reruns from the first failed or changed call → stable call order, `label` with element id on every `agent()`.
- Hung agent restarts FROM ZERO (≤ 5), edits stay → larger `stallMs` for builders (template: 1800000; waiting for own commands/tests is not counted); after the run `git status`, sort out half-edits.
- Model: call → role → `CLAUDE_CODE_SUBAGENT_MODEL` → session.
- `agent()` returns `null` on stop/error: filter it.
- Loop: scout → `parallel` builders (`model: 'sonnet'` if mechanical, `stallMs`) → `code-reviewer` ≤ 3 rounds until `ready`;
  mechanical milestone: review on Sonnet, after `ready` one gate round on Opus.
- Wide review: `pipeline(zones, lens, findings → parallel verifier refutations)`.
