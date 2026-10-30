# Slicing and extending builders

- Subtask = one contract, green at the end; no cutting by file count, no two builders on one contract, no gluing plan items.
- Expect > ~80–100 turns → seam by meaning (schema → logic → readers); none → leave whole, write why. Mixed subtask: `SKILL.md` §3.2.
- Unfamiliar zone or subtask over one file → `scout` first, the brief carries a map slice; the builder walks every place
  the edit reaches (callers, tests, fixtures, exports).

| case | what to do |
|---|---|
| it asked at the start; a short remainder in the same zone | answer via SendMessage, the same one continues |
| a new zone or expansion; red after the full suite and context > ~150 thousand | a fresh builder |
| a side question "how is X built" | `scout` on Sonnet, not the working builder |

`handoff`: done (diff, files), decisions, REJECTED options + reason, contract, reds with output.

Escalation (unclear spec, red twice): a new agent one step up, Sonnet → Opus → Fable.

## Economy
Built into common roles; a project's roles must have it too: independent reads in one turn; `grep -n` → `sed -n` range; `grep`/`diff` `| head`, tests `-q … | tail -15`; swelled → `handoff`, stop.
