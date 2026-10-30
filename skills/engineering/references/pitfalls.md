# Judgment traps — they pass a green suite

The project's list of traps (if any) is appended to this one.

- **Our absence is not a fact about the subject.** "Didn't ask", "path didn't work", "waiting for permission" is a state
  of US: record `unknown` / `unverifiable` / "not asked", never `False` or a verdict.
  - A stub or fallback never answers FOR the subject; on "couldn't ask" refuse at the gate, never pass.
  - A wait needs a door that lifts it. Ladder: no writer (grep the declaration) → never called (grep callers) → always
    one value (measure the data over a period) → the reader does not follow the value.
  - A step goes by PERMISSION, not by an adapter's presence; the gate comes BEFORE announcing the work.
  - A loop runs FASTER with a dead instrument: the rest gate covers all doors to it.
- **Waiter that catches itself:** `until ! pgrep -f "<pattern>"; do sleep …; done` is eternal if the pattern is in the waiter's own command. Wait by completion notification or returned PID; `pgrep` only by a pattern not in its own command.
- **Instrument, not a number.** Quiet and readiness are declared by an instrument that watches, not a preset number. An emergency fuse is not "quiet": write it with its own reason. Invalidity is the state of the world, not "we did X".
- **One judge of fitness.** Producer and queue use ONE predicate: the producer asks the queue by dry run, keeps no copy
  (else a carousel). "How many per round" ≤ consumer capacity. After changing a knob look at the outcomes of refusals, not at "got more".
- **Dedup in the store:** atomic claim (`UPDATE … RETURNING`, `INSERT … ON CONFLICT … RETURNING`), claim and effect in one
  transaction. Process memory is a fast path only; a miss goes to the database. Suspects: dicts/sets in service fields, in-memory locks.
- **Judgment cache version** covers EVERYTHING that prepares the input (parsing, slicing, thresholds).
- **A rule outlives its instrument.** Changing a number, model or instrument: walk the consumers: what work it did at the OLD
  value and whether it remains. Removing one: list all callers and a successor against each; close empty cells BEFORE removal; an honest stub masks "nobody decides this". Remove the whole closure (class, port, registrations, guards).
- **Closed enumeration.** Grep the literal by EVERY value, not the enumeration's name; expect twice the counted amount.
  Derive a second one from one registry. A schema constraint changes by drop+create; "create if not exists"
  leaves the old one on a live database.
- **Model and code.** What code knows exactly (template, dictionary, format) is decided by code. Give the model the
  minimal window that still shows what a human sees (subject and neighbours). Ask only what holds the result.
