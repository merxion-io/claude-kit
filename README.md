# claude-kit

A kit of settings for [Claude Code](https://code.claude.com): rules, skills, subagent roles, hooks and a couple of tools
for checking code quality. Put them in `~/.claude` and the agent works the same way in any project.

Only what does not depend on a project is here. Everything about a specific repository (style, test commands, specs)
stays in the repository itself — in its `CLAUDE.md` and `.claude/skills/`. Project rules outrank the general ones.

## What is inside

**Rules** — `CLAUDE.md`. How to talk to the user and how to work through a problem: not to bypass it with a threshold or an
exception, but to take it to the end on one concrete case.

**Skills** — `skills/`

- `engineering` — how to write and change code: first make it work, then make it right. One rule in one place, a cause
  instead of a patch, tests on behaviour, traps that pass green tests.
- `orchestration` — how to lead a large task with subagents: who does what, how to write a brief, how to review and not
  burn tokens. Separately — when a task may be considered closed: only when all items are done.
- `spec-first` — for projects where behaviour is written into a spec first: proposal → code → merge → archive,
  removing a mechanism with a check that it does not come back.
- `roles` — the observer and executor roles (`claude-role`): how an executor asks, what the
  observer decides alone and what it brings to the operator. For sessions with a role, the hook `hooks/role-intro.py`
  at start, resume and compaction says who it is and asks to load the skill.
- `checkpoint`, `compact-now` — save the session state before context compaction.
- `artifact-location` — where to put HTML reports and pages.
- `firecrawl` — fetch a page when an ordinary request gets 403 or an empty response.

**Subagents** — `agents/`: `builder` writes code from a brief, `code-reviewer` reviews and fixes only what is proven,
`scout` finds the right places in code, `verifier` checks one finding. For projects with specs — `spec-reviewer`
(looks for what refutes "done per spec") and `spec-auditor` (is the proposal implemented). `builder`, `code-reviewer`
and `spec-reviewer` get `engineering` right away.

**Roles** — `bin/claude-role` launches Claude in a tmux pane as an observer or an executor. The observer talks to the
operator and watches the executors; an executor does the work and asks the observer when it needs a decision.

```bash
claude-role observer [<name>] [--project <pult project>] [--no-remote-control] [claude flags...]
claude-role executor "<name>" [--to <observer>] [--project <pult project>] [claude flags...]
claude-role doctor      # self-check of the machine
```

An executor's main session changes no files inside a git repository (a builder writes), sends no pushes to the phone,
and does not start without a live observer. A project may also forbid actions until a skill is loaded. How it all works
(labels, the list and revival, press, status, the write guard, skill gates): [docs/roles.md](docs/roles.md).

**Hooks** — `hooks/`: save a checkpoint before context compaction and return it after, watch the size of memory, draw
the status line.

- `role-state.py` — writes an executor's state label, the pane labels and the revive list; holds the write guard and skill gates.
- `observer-wait.py` — the observer's waiter: wakes it when one of its executors asks, waits, stops, hangs or dies.
- `agent-guard.py` — denies the observer typing into an executor's pane and checks the orchestration rules.

**Measurements** — `docs/measurements/`: the numbers behind the rules, for people; agents read only `skills/`.

**Tools** — `tools/`

- `quality/gate.py` — checks for a project in any language: code duplicates, dead code, function complexity (and CRAP if
  a coverage report exists). Python it parses itself, the rest through jscpd, the project's ESLint, lizard and knip.
- `quality/sabotage.py` — breaks a line of code, runs the tests and checks that they noticed.
- `token-spend.py` — how much sessions and subagents cost.
- `write_guard.py` — denies an executor's writes into a git repository (see [docs/roles.md](docs/roles.md)).
- `skill_gates.py` — denies a project's actions until their skills are loaded.
- `private_words.py` — fails if a tracked file, its path or a commit message holds a word from the local, untracked
  `.kit-private-words`; `install.sh` runs it from the `commit-msg` and `pre-push` git hooks.
- `roles.py` — shared code of the launcher and the hooks: panes, processes, labels, the revive list.

## Installation

```bash
git clone git@github.com:<owner>/claude-kit.git ~/claude-kit
~/claude-kit/install.sh
```

The script copies the kit's files into `~/.claude` (files that are not the kit's stay) and adds to `settings.json` only
what is not there yet: missing settings and the kit's missing hooks — it does not change your values or your hooks. If `~/.claude` does not exist yet, you can clone straight into it.

**macOS.** Needs tmux, jq and python3 ≥ 3.11 — `install.sh` checks and tells the command (`brew install tmux jq
python`), it installs nothing itself. The kit reads processes through `/proc` on Linux and through `ps` on macOS; the
liveness of a role is by the claude PID in the pane label `@claude_pid`, another process's environment is not needed.
What is fine on the machine and what is not — `claude-role doctor` (inside a claude session — `! claude-role doctor`:
that way it checks its own claude too).

**pult** (a tmux session manager) is not part of the kit, the kit does not depend on it: without pult sessions are
simply not handed to projects.

After installation what remains is to set up what is each machine's own:

- log in to the account: `claude`, then `/login`;
- connect MCP servers: `claude mcp add …`;
- optionally describe your organization in `autoMode.environment` in `settings.json` — these are hints for auto mode
  (which repositories and domains are trusted).

## Quality checks

They work as a ratchet: the current findings are recorded once as debt, then any new finding is an error, and a fixed
one must be struck from the list. Debt can only shrink.

```bash
cd my-project
python3 ~/.claude/tools/quality/gate.py all --init   # record the current state in .quality/
python3 ~/.claude/tools/quality/gate.py all          # then — check
```

Once per machine — `python3 ~/.claude/tools/quality/gate.py setup` (installs vulture and lizard into its own
environment, the project pulls in nothing); for JS/TS and duplicates in other languages Node.js is needed. Settings —
`.quality/config.toml` or `[tool.quality-gate]` in `pyproject.toml`; without them the script finds languages and what to
check by itself. What is measured by which tool — `skills/engineering/references/gates.md`.

Check that a test really catches an error:

```bash
python3 ~/.claude/tools/quality/sabotage.py src/price.py --find "return total" --replace "return 0" -- pytest -q tests/test_price.py
```

## Updating

`git pull` and `install.sh` again.

## What is not here

Conversation histories and project memory (`projects/`), keys and account data (`~/.claude.json`), the personal
`settings.json`, caches, plugins and skills that Claude syncs itself (`skills/synced/`).
