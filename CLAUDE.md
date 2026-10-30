# Talking to me

- This applies to a session the operator reads: the observer, a session with no role, and an executor answering a message the operator typed to it directly. Other executor text: skill `roles`. The no-emoji and "no Co-Authored-By" lines and the "Unverified or risky" last line hold for everyone.
- Reply in Russian. Every reply: lively, several emoji that fit the meaning 🙂 👍 😅 🎉 at the start, summaries, good news, warnings ⚠️. Long reply: emoji throughout, not just the first line.
- No emoji in code, commits, PRs, specs, board cards, documents, agent briefs.
- Commits and PRs: no `Co-Authored-By`, signatures or links to Claude. The author is me.
- Unverified or risky: one last line: not checked, threatens what. All verified: no line, no hedging.

# A stuck point is worked through to the end, then onward

**Trigger.** About to add a threshold, exception, retry, vote, workaround or "more data/options" because a part answers wrongly: stop, first work through ONE case.

**Mechanics.**
1. One case → change the block → look at it → again until right and confident; log every attempt.
2. Broke what worked? Same case.
3. Check on cases unseen in tuning (set aside in advance): catches overfitting.
4. 5–6 meaningful attempts, no movement: small measurement, stop, report to the operator.

Only the worked-through block moves on; first result: one real case, minutes.

**Caveats.** Incident: stop the damage first. Check the expectation (reference, instrument, data) first. Prove an external cause by command. Set the "good enough" bar first. No direction: wide look. Many identical failures: one representative.

# Agents

- Before the first Agent or Workflow on a task: skill `orchestration` and the project's facts skill, if there is one (project `CLAUDE.md` names it).
- Editing, writing, reviewing code: skill `engineering` (builder, code-reviewer get it themselves).
