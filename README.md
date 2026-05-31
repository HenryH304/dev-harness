# DevHarness — Autonomous Multi-Agent Software Development Harness

DevHarness is a Kanban board where the workers are AI agents instead of people.
You file a ticket; a chain of specialised agents — developer, reviewer, tester,
merger — pick it up in turn, each running an autonomous "ralph" coding loop
inside an isolated git worktree, and advance the ticket through the board until
it is merged to main (or blocked for a human to look at).

**Stack at a glance:**

- **Frontend** : Vite + TypeScript single-page Kanban board (served by nginx)
- **Backend** : FastAPI (Python) + SQLAlchemy over SQLite
- **Bus/locks** : Redis pub/sub (events) + Redis `SET NX EX` (distributed locks)
- **Executor** : a small host-side Python process that actually runs `ralph`
- **Isolation** : one git worktree + branch (`ticket/<id>`) per ticket
- **Durable merge state** : beads (`bd`), backed by Dolt

---

## 1. Quick Setup & Install

### Prerequisites (host machine)

- **Docker + docker-compose** — frontend, backend, redis run in Docker
- **Python 3.11+** — for the host-side executor virtualenv
- **git** — worktrees are the unit of isolation
- **The `ralph` CLI on your PATH** — the agent loop the executor invokes
- **The `claude` CLI on your PATH** — ralph drives this; `--dangerously-skip-permissions` is used for unattended runs
- **dolt + bd (beads)** — durable merge checkpoints; see step 2
- **ngrok** — optional, only for `make up` public URL
- **The ralph project template at** `~/Projects/my-ralph-template/setup.sh` — copied into each new worktree

### Step 1 — Configure environment

```sh
cp .env.example .env
```

Edit `.env` and set at least:

```sh
PORT=9080                        # backend port (default fine)
REDIS_URL=redis://redis:6379     # leave as-is for Docker
DATABASE_URL=sqlite:///data/devharness.db
```

And, if you intend to use `make up` (ngrok) and git commits by agents:

```sh
AUTH_USER / AUTH_PASSWORD            # basic-auth for the ngrok tunnel
GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL   # also used as committer identity
```

And, if your git projects do not live under `/home/henry/Projects`:

```sh
PROJECTS_DIR=/path/to/your/Projects   # host dir holding your git repos
HOME_DIR=/path/to/your/Projects/..    # container HOME (optional)
```

> **NOTE:** `docker-compose.yml` bind-mounts `PROJECTS_DIR` into the backend container
> at the SAME absolute path (default `/home/henry/Projects`) and sets `HOME` from
> `HOME_DIR` (default `/home/henry`). Both default if unset, so you only need to set
> them when your repos live elsewhere. The executor runs ralph using the SAME
> absolute paths the container stores on each ticket, so `PROJECTS_DIR` must
> resolve identically on the host and inside the container.

### Step 2 — Install host dependencies (dolt + beads)

```sh
./scripts/install-deps.sh          # idempotent; installs dolt and bd
```

(Optional) pre-create the beads Dolt remote for a project — the merger agent
does this automatically on first run, so this is only needed up front:

```sh
bash scripts/init-beads-remote.sh ~/Projects/my-app
```

### Step 3 — Create the executor virtualenv

The executor runs on the HOST (not in Docker) because it needs to launch
`ralph`/`claude` against real worktrees on your filesystem.

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
# (the executor only strictly needs `redis`, but installing the full set
#  is simplest and lets you run the backend test-suite locally too)
```

### Step 4 — Start everything

```sh
make start        # build + start Docker services AND the host executor,
                  # then tail logs
```

or

```sh
make up           # same as `make start` plus an ngrok tunnel (uses
                  # AUTH_USER/AUTH_PASSWORD from .env) and prints a public URL
```

- Open the board: <http://localhost:8080>
- Backend API: <http://localhost:9080> (health: `/api/health`)

### Common make targets

| Target | Description |
| --- | --- |
| `make start` | Build + start Docker services and the executor (tails logs) |
| `make up` | Same as start, plus ngrok public URL |
| `make stop` | Stop the executor and Docker services |
| `make down` | Stop ngrok, the executor, and Docker services |
| `make restart` | stop then start |
| `make logs` | Tail Docker service logs |
| `make executor` | Run the executor in the foreground (Ctrl-C to stop) |
| `make start-ngrok` | Start just the ngrok tunnel (prints the URL) |
| `make stop-ngrok` | Stop ngrok |
| `make help` | Show all targets |

- Executor logs: `/tmp/executor.log` (pid file: `/tmp/executor.pid`)
- ngrok logs: `/tmp/ngrok.log`

> **IMPORTANT:** the executor is not optional. If it is not running, the backend will
> publish spawn requests that nobody answers; pickups will time out after ~30s
> with "No ACK from executor" and tickets will be returned to their input column.

---

## 2. Using the Dev-Harness

The mental model: the board is a pipeline. You put work in at the left
(`to_do`); agents pull it rightward automatically. You rarely "drive" an agent —
you create tickets and watch the board, intervening only on blocked tickets.

### 2.1 Register a project

A "project" is just a name pointing at a git repository path on disk (the path
as the container sees it, i.e. under the mounted projects directory). Create
one from the board UI (Projects / Create Project). If the target directory is
not yet a git repo, the harness will `git init` it and make an initial commit
the first time a developer agent needs a worktree.

### 2.2 Get tickets onto the board — three ways

1. **Manual:** create a ticket directly (title, description, acceptance
   criteria, priority). It lands in `to_do`.

2. **Feature generation:** type a one-line feature description. A story-writer
   agent turns it into a `prd.json` of small, single-iteration user stories,
   which are then imported as tickets (with dependencies between them where
   needed).

3. **Spec generation:** type a description; a spec-writer agent first produces a
   specification document, then a story-writer agent converts that spec into
   tickets. Use this for larger features where you want a reviewable spec
   before any code is written.

### 2.3 Let the agents run

Once tickets are in `to_do`, the harness dispatches agents on its own:

```
to_do            -> developer -> in_progress      -> ready_for_review
ready_for_review -> reviewer  -> in_review        -> ready_for_test
ready_for_test   -> tester    -> in_test          -> ready_for_merge
ready_for_merge  -> merger    -> in_merge         -> done
```

Each agent runs ralph inside that ticket's own worktree/branch, so multiple
tickets progress in parallel without stepping on each other. The board updates
live over a WebSocket as states change.

### 2.4 When an agent rejects work

Reviewer and tester agents don't just pass/fail — when they reject, they write
structured feedback (`review-failures.json` / `test-failures.json`) into the
worktree. The harness reads it, appends a "Rework Required" / "Test Failures"
section to the ticket description, and adds a note to the ticket timeline. The
ticket returns to `to_do`, and on the next developer pickup the agent sees
exactly what to fix. This is the core self-correction loop.

### 2.5 Blocked tickets (your cue to step in)

A ticket moves to `blocked` when a stage exhausts its retries (e.g. the
reviewer rejects 3 times) or when the merger hits a genuine, unresolvable
conflict. Blocked tickets are the only ones that need a human. Read the failure
notes, fix whatever is wrong, then use the board's manual-override transition to
push the ticket back into the pipeline. Unblocking a ticket resets the relevant
failure counter so the agents get a fresh set of retries.

### 2.6 Tuning behaviour (Settings)

From the Settings panel you can change, at runtime (stored in the DB, highest
precedence over `config.json` and env vars):

- `max_agents_system` — total concurrent agents (default 10)
- `max_agents` per type — developer 3 / reviewer 2 / tester 2 / merger 1
- per-agent timeouts — dev 1200s / reviewer 600s / tester 600s / merger 300s
- rejection/failure thresholds — developer / review / tester (default 3 each)
- `active_priority_project` — jump one project's tickets to the front of the queue
- `agent_dispatch_enabled` — global kill-switch — pause all new pickups

---

## 3. Design Overview

### 3.1 How tickets are tracked per state

A ticket is a single row (see `backend/app/models.py` :: `Ticket`). Its `state`
column is the source of truth for where it sits on the board. States fall into
three groups:

- **WAITING** (an agent's input column — eligible for pickup):
  `to_do`, `ready_for_review`, `ready_for_test`, `ready_for_merge`

- **ACTIVE** (an agent is currently working — not eligible for pickup):
  `in_progress`, `in_review`, `in_test`, `in_merge`

- **TERMINAL / EXCEPTION:**
  - `done` — merged, pipeline complete
  - `blocked` — needs a human; no automatic transitions out

Each WAITING state is bound to exactly one agent type (`agents.py` ::
`AGENT_TYPES.column_binding`, and the inverse map `agent_loop.py` :: `STATE_TO_AGENT`):

```
to_do            -> developer
ready_for_review -> reviewer
ready_for_test   -> tester
ready_for_merge  -> merger
```

Alongside `state`, each ticket carries the bookkeeping that makes the pipeline
recoverable and bounded:

- `previous_state` — where it came from (for crash recovery / unblock)
- `current_agent`, `assigned_at` — who holds it now and since when (timeout basis)
- `branch_name`, `worktree_path` — its isolated git workspace
- `agent_attempts` — total pickups
- `*_failure_count` / `*_rejection_count` — per-stage retry budgets
- `*_timeouts` — per-stage timeout tallies
- `merger_resume_count` — merger-specific resumable-retry counter

Every meaningful change is also written to an append-only `events` table (an
audit trail) and broadcast on Redis. Per-ticket `notes` capture human-readable
history (rejections, blocks, transitions) shown in the ticket timeline.

State persistence is split by durability:

- **SQLite** : the durable system of record (tickets, notes, events, registry,
  settings, projects, dependencies, feature/spec jobs).
- **Redis** : ephemeral only — pub/sub event bus and short-TTL pickup locks.
- **Git** : per-ticket worktree + branch; `progress.txt`, `ralph.log` and commit
  history act as the agent's working memory across ralph iterations.
- **Dolt/bd** : a durable, resumable checkpoint graph for the merge stage.

### 3.2 How agents are spawned

Dispatch is event-driven with two safety nets, all in `agent_loop.py`:

1. **Event-driven (primary):** a background task subscribes to the Redis
   `ticket:events` channel. When a ticket lands in a waiting column
   (`ticket_state_changed` / `agent_failed` / `agent_completed` /
   `developer_work_available`), `STATE_TO_AGENT` maps the new state to an agent
   type and a pickup is scheduled immediately.
2. **Startup scan:** on boot, sweep every input column once (so work queued while
   the backend was down is picked up).
3. **Heartbeat:** every 5 minutes, sweep again AND run the timeout checker — this
   catches any event that was missed and reclaims stuck agents.

A scheduled pickup runs `try_pickup_and_run(agent_type)`, which does:

**STEP 1 — claim a ticket** (`routers/agents.py` :: `pickup_ticket`):

- Reject if the global dispatch kill-switch is off → 429
- Enforce capacity: system-wide cap, a WIP rule that reserves
  the last free slot for higher-priority (later-stage) agents,
  and a per-agent-type concurrency cap → 429
- Select candidates: tickets in this agent's `column_binding`,
  unassigned (`current_agent IS NULL`), with no dependency
  currently `blocked`; ordered by priority-project then priority.
- Acquire a Redis lock per candidate (`SET NX EX 30`) to make pickup
  safe under concurrency; the first lock won is the claimed ticket.
- For a developer with no worktree yet, create the git worktree and
  branch (`ticket/<id>`) off main.
- Transition WAITING → ACTIVE (`PICKUP_NEXT_STATE`), stamp
  `current_agent` + `assigned_at`, bump `agent_attempts`, insert a `busy`
  row into `agent_registry`, and publish `agent_assigned`.

**STEP 2 — run ralph** (`ralph_runner.py` :: `spawn_agent`):

- Write `prd.json` (ticket + prior notes + agent type) and the agent's
  `prompt.md` into the worktree.
- The backend runs in Docker but ralph must run on the host, so execution
  is an RPC over Redis: the backend publishes a request on `ralph:spawn`
  and waits on `ralph:result:<id>`.
- The host executor (`executor.py`) receives it, launches
  `ralph -timeout <N>m` in the worktree, immediately publishes an `ack`
  (with the pid), and publishes the exit code when ralph finishes.
- The backend fails fast if no ack arrives within 30s (executor down), and
  otherwise waits up to the agent timeout + buffer for the result.

**STEP 3 — report the outcome** (state transition, below).

Concurrency is therefore bounded at three levels — system cap, per-type cap,
and the per-ticket Redis lock — so "50 agents in parallel" degrades gracefully:
excess pickups get a 429 and are simply retried on the next event/heartbeat
rather than overrunning the machine.

### 3.3 How state transitions are managed

There are two transition paths.

**A) Agent-driven (the normal flow), in `routers/agents.py`:**

- `pickup_ticket` : WAITING → ACTIVE (`PICKUP_NEXT_STATE`)
- `complete_ticket`: ACTIVE → next WAITING (`COMPLETE_NEXT_STATE`):
  ```
  in_progress -> ready_for_review
  in_review   -> ready_for_test
  in_test     -> ready_for_merge
  in_merge    -> done   (and the worktree is deleted in the background)
  ```
  On completion the agent is released (registry row freed,
  `current_agent`/`assigned_at` cleared) and an `agent_completed` event fires,
  which in turn triggers the next stage's pickup.
- `fail_ticket` : ACTIVE → `to_do` (rework) OR → `blocked` (threshold hit).

Who calls complete vs fail is decided in `agent_loop.py` from the ralph exit
code AND side-channel signals:

- **reviewer/tester:** presence of `review-failures.json` / `test-failures.json`
  means "reject" even if ralph exited 0; the structured issues are folded
  into the ticket description and notes before it returns to `to_do`.
- **merger:** outcome is read from beads state, not an exit code
  (`_classify_merger_outcome`): no open beads ⇒ complete; open beads with
  a `blocker` ⇒ fail/block; open beads without a blocker ⇒ transient
  retry (return to `ready_for_merge` and re-dispatch).

**B) Human-driven (manual), in `routers/transitions.py`:**

A strict state machine (`ALLOWED_TRANSITIONS`) validates every manual move;
each state may only advance one step or go to `blocked`. Transitions past
`to_do` are refused while the ticket has unresolved (not `done`)
dependencies. `blocked` is a trap state: leaving it requires
`manual_override`, and doing so resets the failure counter for whichever
stage caused the block, so the agents resume with a fresh retry budget.

Every transition (either path) is persisted, written to the `events` audit
table and/or a note, and published on `ticket:events` so the board and the
dispatcher both react in real time.

### 3.4 How retries are managed

Retries are layered, from cheapest/most-local to most-expensive, so transient
noise self-heals while genuine failures eventually stop and ask for a human.

**Layer 0 — inside ralph (`ralph.sh`):**
A single agent run retries up to `MAX_RETRIES=3` on transient API errors
(rate limit, `ECONNRESET`/`ETIMEDOUT`, 502/503, "No messages returned") with a
10s backoff, before giving the iteration back to the harness.

**Layer 1 — rework loop (per stage, bounded):**
A reviewer/tester rejection or a developer failure returns the ticket to
`to_do` and increments that stage's counter (`review_rejection_count`,
`tester_rejection_count`, `developer_failure_count`). The structured feedback is
attached so the next attempt is informed, not blind. When a counter reaches
its threshold (default 3), the ticket is moved to `blocked` instead of being
retried again — this is the guard against an agent looping forever on work
it cannot do.

**Layer 2 — timeout reclamation** (`check_agent_timeouts`, every heartbeat + on
startup):
If an agent has held a ticket past its per-type timeout, it is reclaimed.
But before failing it, the harness checks the worktree's `ralph.log` for the
`<promise>COMPLETE</promise>` marker: if ralph actually finished and only
the result message was lost (e.g. the backend restarted mid-run), the
ticket is advanced as a success rather than retried. Otherwise the stage's
timeout counter is bumped; developer timeouts also count toward the
developer failure threshold, so repeated hangs eventually block too.

**Layer 3 — merger resumability (beads-backed):**
The merge is modelled as a beads "molecule" (fetch → rebase → test →
push → cleanup) whose progress is checkpointed in Dolt. On a merger
timeout the harness inspects beads state:

- partial progress, no blocker, `merger_resume_count < 3` ⇒ **RESUME:**
  bump the counter, return the ticket to `ready_for_merge`, re-dispatch the
  merger so it continues from the last completed phase instead of
  restarting.
- partial progress but resume cap reached ⇒ **BLOCK.**
- a bead explicitly marked `blocker` ⇒ **BLOCK** (a real conflict; humans
  only).

This is why a crash or timeout mid-merge does not redo a successful rebase —
the checkpoint graph survives the process.

**Reset on unblock:**
Because a manual unblock clears the offending counter, human intervention
cleanly re-arms all of the above for another full set of attempts.

**Net effect:** transient infrastructure errors are absorbed silently (Layer 0),
honest "the code is wrong" failures get a bounded, feedback-driven retry budget
(Layer 1), lost/crashed runs are reconciled rather than blindly retried
(Layer 2), and long stateful operations resume from their last good checkpoint
(Layer 3) — with `blocked` as the single, deliberate place where the system
stops and asks a person for help.

---

## 4. Repository Map

```
Makefile                      orchestration targets (start/stop/up/down/ngrok)
docker-compose.yml            frontend + backend + redis services
executor.py                   HOST-side ralph runner (Redis ralph:spawn -> ralph)
ralph.sh / prompt.md          the autonomous agent loop and its base prompt
.env.example                  environment template (copy to .env)
scripts/install-deps.sh       install dolt + bd (beads) on the host
scripts/init-beads-remote.sh  optionally pre-create a project's Dolt remote
.beads/formulas/              the merge-molecule workflow template (beads)

backend/app/
  main.py                     FastAPI app; starts the dispatcher background tasks
  models.py                   SQLAlchemy schema (Ticket, Note, Event, ...)
  config.py                   layered config (defaults < json < env < DB)
  agents.py                   agent type registry (column binding, timeout, prompt)
  agent_loop.py               dispatcher: event listener, startup scan, heartbeat
  ralph_runner.py             spawn_agent + Redis RPC to the host executor
  worktree.py                 git worktree create/delete per ticket
  redis_client.py             pub/sub + event helpers
  routers/agents.py           pickup / complete / fail / timeout logic
  routers/transitions.py      manual state-machine transitions + validation
  routers/{tickets,projects,features,specs,settings,...}.py   board + UI APIs
backend/prompts/              per-agent prompts (developer/reviewer/tester/merger/...)
backend/tests/                pytest suite (one file per user story)

frontend/src/                 Vite + TS Kanban board, real-time over WebSocket
```
