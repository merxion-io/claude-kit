# Review that can be trusted

## Isolation
- Reviewer gets: **diff (paths), intent in one sentence, contract/spec, acceptance command, focuses**; NOT the builder's
  report/reasoning, nor verdicts of earlier rounds or other reviewers. A repeat round: the **diff since the last round**.

## Attack
- Focuses: races, transactions, errors/rollbacks, idempotency, permissions/data boundaries, money; project traps — if the project has a list (a skill, a CLAUDE.md section), insert it by name.
- ALWAYS structure: second home of a rule, flag for one case, `if` on top of the old path, dead code, duplicate.
- **Do not report:** old defects outside the diff, linter catches, taste, untouched lines.

## Proof
- Finding = a failing test or a command with output; none → `unproven`, not fixed.
- Live spec or intent must oblige it, else `minor`. "No confident verdict" is allowed. No red under sabotage → does the line have an outcome?

## Wide review
`dossier → reviewers by lenses → dedup by code → verifier on every red → synthesis`. `verifier`: reproduces on clean
HEAD? does the live contract oblige it? Default "not confirmed", doubt → drop; unverified → separate field, not counted as "clean". Judgment → agents; counting, dedup, ranking → code or orchestrator.

## Rounds
≤ 3; a third still finding → builder's sabotage before handing in, no fourth.
