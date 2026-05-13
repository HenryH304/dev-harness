# PRD: Beads Merger Integration

## Introduction

The merger agent currently runs as a single monolithic ralph session that does everything in one shot: fetch → rebase → resolve conflicts → run tests → merge → push. If the agent crashes or exceeds its 5-minute timeout at any point, all progress is lost and the ticket lands in `blocked` — requiring manual intervention even for transient failures (network hiccup, timeout under load).

This PRD integrates [beads](https://github.com/gastownhall/beads) (`bd`) — a Dolt-backed durable task graph — into the merger pipeline. The merger agent still performs all the actual git work. Beads acts as a checkpoint layer: each phase of the merge becomes a bead, persisted to a local Dolt remote shared across all worktrees for the project. If the agent crashes, a new instance syncs from the local remote and resumes from the last closed bead. The backend gains the ability to distinguish transient failures (retry) from genuine blockers (block), rather than always blocking on any failure.

---

## Goals

- Make the merger resumable: a crashed or timed-out merger restarts from where it stopped, not from scratch
- Give each conflicting file its own bead for granular visibility and future parallel resolution
- Replace `merge-failures.json` as the failure signal with beads state — enabling the backend to distinguish transient vs genuine blockers
- Enable automatic retry of transient merger failures instead of immediately sending tickets to `blocked`
- Design for a local-filesystem Dolt remote shared across all worktrees for a project on the same box

---

## User Stories

### US-001: Install beads and Dolt on the host
**Description:** As a developer, I need `bd` and `dolt` available on the host machine so the merger agent can use them when ralph runs.

**Acceptance Criteria:**
- [ ] `dolt` binary is installed and `dolt --version` succeeds in the shell where executor.py runs
- [ ] `bd` CLI is installed and `bd --version` succeeds in the same shell
- [ ] Installation is documented in the project README or a `scripts/install-deps.sh` script
- [ ] `make start` still works after installation with no regressions

---

### US-002: Initialize local Dolt remote for the project
**Description:** As a developer, I need a shared local Dolt remote on the filesystem so all worktrees for the dev-harness project can push and pull beads state to a common location.

**Acceptance Criteria:**
- [ ] A `scripts/init-beads-remote.sh` script creates the local Dolt remote at a configurable path (default: `<project-root>/.beads-remote/`)
- [ ] The remote path is stored in `.env` as `BEADS_REMOTE_PATH`
- [ ] Running the script twice is idempotent (no error on second run)
- [ ] The `.beads-remote/` directory is added to `.gitignore`
- [ ] Merger agent can `dolt remote add origin $BEADS_REMOTE_PATH` and `bd dolt push` successfully from a worktree

---

### US-003: Define the merge molecule template
**Description:** As a developer, I need a beads molecule template that represents the phases of a merge job so the merger agent can spawn it at the start of each merge.

**Acceptance Criteria:**
- [ ] A molecule file exists at `backend/beads/merge-molecule.yml` (or equivalent beads format)
- [ ] Molecule defines top-level phase beads with explicit dependencies:
  - `fetch-main`
  - `rebase` (depends: `fetch-main`)
  - `run-tests` (depends: `rebase` — conflict sub-beads are added dynamically between rebase and tests)
  - `merge-push` (depends: `run-tests`)
  - `cleanup` (depends: `merge-push`)
- [ ] Molecule includes metadata: `execution_agent_type: merger`
- [ ] `bd molecule spawn merge-workflow` produces the expected bead graph in a test worktree
- [ ] Unit test: spawn the molecule, verify expected bead IDs and dependency edges exist in `bd list --json` output

---

### US-004: Update merger.md — beads initialization and phase loop
**Description:** As the merger agent, I need to initialize beads at the start of a merge and work through phase beads using `bd ready`, so my progress is checkpointed after every phase.

**Acceptance Criteria:**
- [ ] `merger.md` instructs the agent to run `bd init` and `bd dolt remote add origin $BEADS_REMOTE_PATH` at the start if no `.beads/` directory exists in the worktree
- [ ] If `.beads/` already exists, the agent runs `bd dolt pull` to restore prior progress before calling `bd ready`
- [ ] Agent spawns the merge molecule if no beads exist yet, otherwise skips molecule creation
- [ ] For each phase bead returned by `bd ready --json --limit 1`, the agent performs the corresponding git work, then calls `bd close <id>` and `bd dolt push` before moving to the next bead
- [ ] The `<promise>COMPLETE</promise>` signal is only written after the `cleanup` bead is closed
- [ ] A fresh merge (no prior beads) completes successfully end-to-end and the ticket reaches `done`
- [ ] A simulated resume (manually close `fetch-main` bead, run merger) skips fetch and begins at `rebase`

---

### US-005: Create and clean up per-file conflict sub-beads
**Description:** As the merger agent, I need to create one child bead per conflicting file during rebase so each file's resolution is tracked individually, and clean them up after a successful merge.

**Acceptance Criteria:**
- [ ] After `git rebase origin/main` reports conflicts, the agent runs `git status --short` to find all conflicted files
- [ ] For each conflicted file, the agent creates a child bead under `rebase`: `bd create "resolve-conflict:<filename>" --parent <rebase-bead-id>`
- [ ] The agent resolves each file, then calls `bd close <conflict-bead-id>` and `bd dolt push` per file
- [ ] The `run-tests` bead only becomes "ready" (unblocked) after all conflict sub-beads are closed
- [ ] After `cleanup` bead is closed, the agent calls `bd dolt push` then removes the `.beads/` directory from the worktree (the worktree itself is deleted by the system, but beads data is not needed after merge)
- [ ] A merge with 3 conflicting files shows 3 `resolve-conflict:*` beads in `bd list --json` during the run, and none after cleanup
- [ ] If no conflicts occur, no conflict sub-beads are created

---

### US-006: Replace merge-failures.json with beads state in the backend
**Description:** As the backend, I need to read beads state to determine merge outcome — distinguishing transient failures (open beads remain, agent crashed) from genuine blockers (a bead is marked with blocker metadata) — instead of relying on `merge-failures.json`.

**Acceptance Criteria:**
- [ ] `merger.md` no longer instructs the agent to write `merge-failures.json`; genuine blockers are recorded by setting bead metadata: `bd update <id> --metadata '{"blocker": true, "category": "...", "detail": "..."}'`
- [ ] `backend/app/agent_loop.py` has a `_read_beads_state(worktree_path)` function that runs `bd list --json` in the worktree and returns parsed output (returns `None` if beads is not initialized)
- [ ] In `try_pickup_and_run()`, after ralph exits, the merger branch reads beads state instead of `merge-failures.json`:
  - Exit 0 + no open beads → success → `complete_ticket()`
  - Exit non-zero + open beads with no blocker metadata → transient failure (agent crashed mid-run) → retry (re-dispatch, do not block)
  - Any exit + a bead with `blocker: true` → genuine blocker → `fail_ticket()` → `blocked`
- [ ] The stale `merge-failures.json` cleanup in `agent_loop.py:104-118` is removed for the merger case (no longer needed)
- [ ] Unit tests cover all three outcome branches using a mocked `bd list` response
- [ ] Typecheck passes (`mypy` or `pyright`) on modified files

---

### US-007: Merger resumability in the timeout handler
**Description:** As the backend, when the merger agent times out, I need to check whether beads has partial progress and retry rather than always returning the ticket to a manual state.

**Acceptance Criteria:**
- [ ] In `backend/app/routers/agents.py`, the merger timeout handler (around line 637) reads beads state from the worktree after a timeout
- [ ] If beads shows partial progress (at least one bead is closed, at least one is open, none are blockers) → the handler re-dispatches the merger by calling `_schedule_pickup("merger")` and does NOT transition the ticket out of `in_merge`
- [ ] If beads shows no progress (all beads open) or a genuine blocker bead → the existing timeout logic runs (ticket returns to `to_do` or `blocked`)
- [ ] If beads is not initialized in the worktree (no `.beads/` dir) → fall back to existing `<promise>COMPLETE</promise>` log-check behavior
- [ ] A `merger_resume_count` field is added to the `Ticket` model to track how many times the merger was auto-resumed; if it exceeds 3, stop retrying and block instead
- [ ] Unit tests cover: partial-progress retry, no-progress fallback, blocker fallback, resume-count cap
- [ ] Typecheck passes on modified files

---

## Functional Requirements

- FR-1: `bd` and `dolt` CLIs must be installed and available in the PATH used by executor.py
- FR-2: A shared local Dolt remote at `<project-root>/.beads-remote/` is initialized once per project; path configured via `BEADS_REMOTE_PATH` env var
- FR-3: Each merge job initializes a local beads DB in `<worktree>/.beads/` and pushes to the shared remote after every bead close
- FR-4: The merge molecule defines five top-level phase beads with explicit dependencies: `fetch-main` → `rebase` → `run-tests` → `merge-push` → `cleanup`
- FR-5: During rebase, one child bead is created per conflicting file under the `rebase` bead; all must be closed before `run-tests` becomes ready
- FR-6: After cleanup bead is closed, the `.beads/` directory is deleted from the worktree
- FR-7: The backend reads `bd list --json` output (not `merge-failures.json`) to classify merge outcomes
- FR-8: Genuine blockers are written to a bead's metadata with `blocker: true`, not to a separate file
- FR-9: The merger timeout handler retries (re-dispatches) when beads shows partial progress, up to a maximum of 3 auto-resumes per ticket
- FR-10: All existing merge lifecycle events (`agent_assigned`, `agent_completed`, `ticket_blocked`) continue to fire correctly

---

## Non-Goals

- No Dolt Hub or network-remote sync — local filesystem only in this phase
- No parallel conflict resolution by multiple sub-agents (beads structure supports it, but orchestration is not in scope)
- No beads integration for developer, reviewer, or tester agents — merger only
- No UI changes to show beads progress in the board
- No changes to worktree creation or deletion logic
- No changes to the state machine (`ready_for_merge` → `in_merge` → `done`/`blocked`)

---

## Technical Considerations

- **Key files to modify:**
  - `backend/prompts/merger.md` — primary change (US-004, US-005)
  - `backend/app/agent_loop.py` — outcome classification (US-006)
  - `backend/app/routers/agents.py` — timeout handler resumability (US-007)
  - `backend/app/models.py` — add `merger_resume_count` field (US-007)
  - `.gitignore` — add `.beads-remote/` (US-002)
  - `.env` / `.env.example` — add `BEADS_REMOTE_PATH` (US-002)

- **New files:**
  - `scripts/init-beads-remote.sh` (US-002)
  - `backend/beads/merge-molecule.yml` (US-003)

- **Beads state read in backend** runs `bd list --json` as a subprocess from Python in the worktree directory; ensure `bd` is on PATH in the same environment executor.py uses

- **Dolt remote design:** one shared remote per project at a fixed path on the local filesystem. Worktrees push after every bead close; on resume, they pull before calling `bd ready`. No cross-ticket coordination needed.

- **Backward compatibility:** The `merger_timeouts` counter on `Ticket` remains; `merger_resume_count` is a new separate field. Existing timeout logic runs as fallback if `.beads/` is absent.

---

## Success Metrics

- A merger that crashes mid-rebase resumes from the correct conflict bead on retry (zero repeated git operations)
- Transient timeouts no longer send tickets to `blocked` — they retry automatically
- `blocked` state is only reached for genuine, human-resolvable blockers (auth failures, irresolvable business logic conflicts)
- No regression in merge success rate for clean merges (no conflicts)

---

## Open Questions

- Should `BEADS_REMOTE_PATH` default relative to the project root (`.beads-remote/`) or to an absolute system path (e.g. `/var/lib/dev-harness/beads-remote/`)? The latter survives worktree moves; the former is easier for local dev.
- Should the `merger_resume_count` cap (3) be configurable via `.env`, or is a hardcoded default sufficient for now?
- When a resume reaches the cap and blocks, should the blocker note include the full beads phase progress (which bead it got stuck on) to help human triage?
