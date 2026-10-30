# Roles

How the observer and executor roles work. The short version is in the [README](../README.md).

`bin/claude-role` launches Claude in a tmux pane as an observer or an executor.

```bash
claude-role observer [<name>] [--project <pult project>] [--no-remote-control] [claude flags...]   # the name defaults to the tmux session
claude-role executor "<name>" [--to <observer>] [--project <pult project>] [claude flags...]
claude-role doctor                                                # self-check of the machine
```

## Launch

Any `claude` flags (`-r`, `--model`, `--remote-control "<name>"`) pass straight through. An observer starts with remote
control named as the observer unless `--no-remote-control` (a kit flag, kept for the revive) or its own
`--remote-control`; an executor gets it only when given explicitly.

In a pane where a claude with a role is already running, the launcher refuses.

An executor sends no pushes to the phone (the `no-mobile-push` muffler and the `PushNotification` prohibition) and does
not start while there is no live observer in tmux; if there are several, `--to` is needed.

## Environment and labels

The role and name go into the environment (`CLAUDE_ROLE`, `CLAUDE_ROLE_NAME`) and into the pane labels
(`@claude_role`, `@claude_name`, `@claude_observer`, `@claude_flags`).

The labels, the list and pult are written by the start of the launched claude (SessionStart), not by the launcher: if
claude did not start (`--help`, an error) nothing is touched.

The role hooks work only in the claude that was launched by `claude-role` (PID in `CLAUDE_ROLE_PID`); without a role and
in nested claudes (`claude -p` with the executor's environment) they are silent.

## pult

If `pult` exists, a session of either role that is not in its log is handed by the launch itself to the pult project with
the longest folder containing the launch directory (`pult ls`, then `pult adopt`). Two such projects or none: an executor
is refused, an observer starts outside pult with one line why. The project is given with `--project "<project>"`. The
project is written to the list, and revive brings the session up in the same one.

pult is not part of the kit; without it sessions are simply not handed to projects.

## The list and revival

The live roster for revival is `state/roles.json`: for every session with a role the tmux session, the folder, the launch
flags and the conversation id. Remote control switched on on the fly is appended to an observer's flags; an executor's
lasts that run only.

- A crashed observer is brought up by an executor that needs it: in the same pane with the same conversation, and if
  there is no pane, in its session or a new one. One closed normally is not brought up.
- One that died before the first message (the conversation not yet recorded) is revived with a new conversation with the
  same name and flags.
- After a reboot: `claude-role observer "<name>" -r` brings up the observer, its `claude-role revive` the executors, each
  in its own tmux session.
- `claude --resume "<name>"` does not suit this: a session name is not unique, revival goes by id.
- A probe sets `CLAUDE_ROLES_STATE_DIR`: its own directory for the list and locks; it does not touch the live `state/`.

## The state label

The hook `hooks/role-state.py` (in `settings.base.json`) writes the executor the label `@claude_state`, one current state.
The values:

- `open`, `working`, `running a command`, `asking`, `waiting for permission`, `waiting for its background`, `telling the observer`,
  `stopped`, `broke`.
- `asking` covers both the choice window and the MCP-server window (elicitation).
- `running a command` holds as long as at least one foreground command runs, even if another tool finished in parallel
  next to it.
- `telling the observer` is written by `claude-role tell "<text>"` and holds until the waiter has seen it.

The observer sees everyone with one `tmux list-panes -a -F '#{@claude_name} #{@claude_state}'`.

### tell

The label carries the text cut to 300 chars. The full text (up to `TELL_LIMIT` = 1500 chars; longer is refused: a file and
its path) waits in `state/tell-<pane>-<stamp>.txt`. The waiter wakes the observer with all of it, then deletes the file
(old undelivered ones go after 7 days).

## The waiter

The hook `hooks/observer-wait.py` (the observer's Stop, `asyncRewake`) waits for its executors and wakes the observer when
an executor:

- asks, writes to it (`claude-role tell`), waits for permission, stopped, broke;
- hung (`working` with no events for more than 120 s);
- died: claude killed in the pane or gone together with the pane and session (a normal `/exit` does not wake).

A repeat of the same state does not wake. There is always exactly one waiter. A twin session (`tmux new-session -t`) does
not double the pane: the list shows the original session.

## press

The observer may press in an executor's window only with `claude-role press "<executor>" <digit|Escape>`:

- once, and only with the window visible (the cursor on a numbered item: the permission window, question tabs, and the
  answer-confirmation screen);
- with a label set from the screen after the press, because the granting and the refusal of a permission are not seen by
  the executor's hooks;
- if the window did not go away (the next tab, confirmation), the label is `asking` with what is already chosen; if it
  went, the outcome;
- an incomplete answer (a warning in a window with tabs) press does not send.

## status, last, send

- `claude-role status "<executor>"`: one line with the label's state and for how long, Claude Code's own status from
  `~/.claude/sessions/<pid>.json`, a window on the screen, and "label stale" when the two disagree for over a minute.
- `claude-role last "<executor>"`: the last assistant text of its transcript, "turn in progress" while a tool call is open.
- `claude-role send "<executor>" "<text>"`: refused, nothing typed, on a choice window, a dialog or someone's text in the
  input box (the dim suggestion does not count; the box is never cleared). Otherwise the text is pasted whole through a
  tmux buffer and Enter is pressed only while the text is in the box; a busy executor takes it into its turn.
- Delivery stays text in the box, not the session messaging: an agent may ignore that.

## Guards on the observer

`hooks/agent-guard.py` denies the observer's `tmux send-keys`/`paste-buffer` into a pane whose `@claude_role` is
executor. The same hook guards the orchestration rules for role sessions (table of kinds of work in
`skills/orchestration/references/routing.md`) and reminds an executor about an operation that runs longer than its series.

Screen reading is `tools/screen.py`, pinned to the UI strings of Claude Code 2.1.312.

## Write guard

An executor's main session changes no files inside a git repository (`tools/write_guard.py`, called by
`hooks/role-state.py`), in any project, with no configuration. The boundary is the repository holding the target path, not
the session's folder.

- Before the call: Edit/Write and what a Bash line writes (redirect, cp, mv, install, rsync, tee, sed -i, perl -i,
  python/node/ruby code, git apply, patch) are denied. A builder writes.
- Open: paths outside a repository, `*.md`, `.claude/checkpoints/`, the project's "open" paths, git itself (merge, commit, checkout...),
  commands inside `ssh`.
- After a Bash call: `git status` and content hashes before and after catch what the text does not show
  (`python script.py`). The executor is told to restore the change; nothing is reverted. Skipped while a subagent runs.

## Skill gates

Project gates (`tools/skill_gates.py`): an action (commit, spec write, build, full test run, Agent) is denied while
one of its skills was never loaded in the session. Compaction and resume keep the loaded skills (Claude Code re-injects
them); startup and /clear start empty.

The table is the project's: `<project>/.claude/kit-gates.json`; no table, no gates. Its key "open" (a list of paths, a trailing `/` = a folder at any depth) adds to the write guard's open list.

A bash gate belongs to the project where the command acts: per command of a line, the directory after a literal `cd` and git's `-C`; an unknowable place counts as the session's cwd. Tool and write gates use the session's cwd.

Subagents, observers and sessions without a role are never touched.
