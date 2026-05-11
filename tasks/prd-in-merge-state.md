# PRD: Add `in_merge` State and Rename `ready_to_merge` → `ready_for_merge`

## Introduction

Every active agent in the dev-harness pipeline has a visible "in-flight" state that lets the board reflect what is actually happening: the developer works in `in_progress`, the reviewer works in `in_review`, the tester works in `in_test`. The merger agent is the only exception — it picks up a ticket from `ready_to_merge` and the ticket stays at `ready_to_merge` while the merge is executing, making it impossible to distinguish "waiting" from "actively merging" at a glance.

This feature closes that gap by introducing `in_merge` as the active merger state, and renames the queue state to `ready_for_merge` for naming consistency with the other queue states (`ready_for_review`, `ready_for_test`).

Final pipeline:
```
to_do → in_progress → ready_for_review → in_review → ready_for_test → in_test → ready_for_merge → in_merge → done
```
Any state can also transition to `blocked`.

---

## Goals

- Introduce `in_merge` as the active state while the merger agent is running
- Rename `ready_to_merge` → `ready_for_merge` for naming consistency across all queue states
- Migrate any existing DB rows using `ready_to_merge` to `ready_for_merge`
- Update the board, dashboard, and drag-drop logic to reflect the new states
- Ensure force-unlock of an `in_merge` ticket returns it to `ready_for_merge`

---

## User Stories

### US-001: Migrate existing database rows
**Description:** As a system operator, I want existing tickets in `ready_to_merge` automatically migrated to `ready_for_merge` on server startup so no manual intervention is required.

**Acceptance Criteria:**
- [ ] `_migrate_schema()` in `backend/app/database.py` runs `UPDATE tickets SET state = 'ready_for_merge' WHERE state = 'ready_to_merge'`
- [ ] Same migration runs for `previous_state` column
- [ ] Migration is idempotent (safe to re-run — no rows match after first execution)
- [ ] Typecheck passes

---

### US-002: Update backend state machine constants
**Description:** As a developer, I need the backend state machine to route the merger agent through `ready_for_merge → in_merge → done` so the ticket state accurately reflects agent activity.

**Acceptance Criteria:**
- [ ] `backend/app/agents.py`: `AGENT_TYPES["merger"]["column_binding"]` is `"ready_for_merge"`
- [ ] `backend/app/agent_loop.py`: `STATE_TO_AGENT` maps `"ready_for_merge"` (not `"ready_to_merge"`) to `"merger"`
- [ ] `backend/app/routers/agents.py`: `PICKUP_NEXT_STATE["merger"]` is `"in_merge"` (ticket moves to `in_merge` on pickup)
- [ ] `backend/app/routers/agents.py`: `COMPLETE_NEXT_STATE["in_merge"]` is `"done"` (replaces old `"ready_to_merge": "done"`)
- [ ] `check_agent_timeouts` auto-recovery still works for `in_merge` tickets (uses `COMPLETE_NEXT_STATE` lookup — no explicit change needed beyond the dict update)
- [ ] Typecheck passes
- [ ] Golden path e2e test: POST pickup for merger → ticket moves to `in_merge`; POST complete → ticket moves to `done` and worktree is cleaned up

---

### US-003: Update allowed transitions
**Description:** As a developer, I need the transitions router to allow the new state sequence so manual drags and internal transitions are validated correctly.

**Acceptance Criteria:**
- [ ] `backend/app/routers/transitions.py` `ALLOWED_TRANSITIONS`:
  - `in_test` allows `{"ready_for_merge", "blocked"}` (was `"ready_to_merge"`)
  - `ready_for_merge` allows `{"in_merge", "blocked"}` (new entry)
  - `in_merge` allows `{"done", "blocked"}` (new entry)
  - `ready_to_merge` entry removed
- [ ] Typecheck passes

---

### US-004: Update dashboard metrics and force-unlock
**Description:** As an operator, I want the dashboard to display `ready_for_merge` and `in_merge` ticket counts and to correctly return an `in_merge` ticket to the queue when force-unlocked.

**Acceptance Criteria:**
- [ ] `backend/app/routers/dashboard.py` `ColumnCounts` Pydantic model: field renamed to `ready_for_merge`, new field `in_merge: int = 0`
- [ ] `all_states` list in `get_metrics` endpoint contains `"ready_for_merge"` and `"in_merge"` (not `"ready_to_merge"`)
- [ ] `_UNLOCK_TARGET` dict: `"ready_for_merge": "ready_for_merge"` (was `"ready_to_merge"`), new entry `"in_merge": "ready_for_merge"`
- [ ] Force-unlocking a ticket in `in_merge` returns it to `ready_for_merge`
- [ ] `GET /api/dashboard/metrics` response contains `ready_for_merge` and `in_merge` fields
- [ ] Typecheck passes
- [ ] Golden path e2e test: force-unlock a ticket in `in_merge` → verify it is returned to `ready_for_merge`

---

### US-005: Update frontend board columns
**Description:** As a board user, I want to see two separate columns — "Ready for Merge" and "In Merge" — replacing the old single "Ready to Merge" column, so I can distinguish tickets waiting for the merger from tickets actively being merged.

**Acceptance Criteria:**
- [ ] `frontend/src/types.ts` `COLUMNS` array: `ready_to_merge` entry replaced by `{ key: 'ready_for_merge', label: 'Ready for Merge' }` followed by `{ key: 'in_merge', label: 'In Merge' }` (positioned before `done`)
- [ ] Board displays both new columns in the correct pipeline order
- [ ] Tickets in `ready_for_merge` appear in the "Ready for Merge" column
- [ ] Tickets in `in_merge` appear in the "In Merge" column
- [ ] Typecheck passes
- [ ] Verify in browser using dev-browser skill

---

### US-006: Update frontend drag-drop transition rules
**Description:** As a board user, I want drag-and-drop to enforce the new state transitions so manual moves follow the same rules as agent-driven moves.

**Acceptance Criteria:**
- [ ] `frontend/src/drag-drop.ts` `ALLOWED_TRANSITIONS`:
  - `in_test` allows `['ready_for_merge', 'blocked']` (was `'ready_to_merge'`)
  - `ready_for_merge` allows `['in_merge', 'blocked']` (new)
  - `in_merge` allows `['done', 'blocked']` (new)
  - `ready_to_merge` entry removed
  - `blocked` target list updated to replace `'ready_to_merge'` with `'ready_for_merge'` and add `'in_merge'`
- [ ] Dragging a ticket from `in_test` to `ready_for_merge` is accepted
- [ ] Dragging a ticket from `ready_for_merge` to `in_merge` is accepted
- [ ] Dragging a ticket from `in_merge` to `done` is accepted
- [ ] Typecheck passes
- [ ] Verify in browser using dev-browser skill

---

### US-007: Update dashboard column labels
**Description:** As an operator viewing the dashboard, I want the column labels to show the new state names so the dashboard matches the board.

**Acceptance Criteria:**
- [ ] `frontend/src/dashboard.ts` `COLUMN_LABELS` (or equivalent label map): `ready_to_merge` removed, `ready_for_merge: 'Ready for Merge'` added, `in_merge: 'In Merge'` added
- [ ] Typecheck passes
- [ ] Verify in browser using dev-browser skill

---

### US-008: Update frontend test fixtures
**Description:** As a developer, I need test fixtures updated to use the new state names so the TypeScript compile and test suite stay green.

**Acceptance Criteria:**
- [ ] `frontend/src/drag-drop.test.ts`: `ready_to_merge` references updated to `ready_for_merge`; `in_merge` transition test cases added
- [ ] `frontend/src/dashboard.test.ts`: fixture field `ready_to_merge: 0` replaced with `ready_for_merge: 0` and `in_merge: 0`
- [ ] `npm test` passes with no skips or warnings
- [ ] Typecheck passes

---

## Functional Requirements

- **FR-1:** On backend startup, the DB migration must rename `state = 'ready_to_merge'` → `'ready_for_merge'` and same for `previous_state`; migration must be idempotent.
- **FR-2:** The merger agent's column binding must be `ready_for_merge`; pickup must transition ticket to `in_merge`.
- **FR-3:** Completing a ticket from `in_merge` must transition it to `done` and trigger worktree cleanup (existing behavior — no separate logic change required).
- **FR-4:** `ALLOWED_TRANSITIONS` (backend) must include `in_test → ready_for_merge`, `ready_for_merge → in_merge`, `in_merge → done`.
- **FR-5:** `GET /api/dashboard/metrics` `ColumnCounts` response must include `ready_for_merge` and `in_merge` fields (not `ready_to_merge`).
- **FR-6:** Force-unlocking a ticket in `in_merge` must return it to `ready_for_merge` and reset the merger failure counter.
- **FR-7:** The board must display "Ready for Merge" and "In Merge" as separate columns positioned after "In Test" and before "Done".
- **FR-8:** Drag-and-drop must enforce the new transition rules; dragging to/from `ready_to_merge` must no longer be possible.
- **FR-9:** All frontend TypeScript types must use `ready_for_merge` and `in_merge`; `ready_to_merge` must not appear anywhere.

---

## Non-Goals

- No change to the merger agent's prompt, worktree, or merge logic itself — only the surrounding state tracking changes.
- No new UI controls — this is purely a state rename + addition.
- No change to how `done` tickets are handled after the merger completes.
- No change to `blocked` semantics or the force-unlock flow for states other than `in_merge`/`ready_for_merge`.

---

## Technical Considerations

- **Execution order matters:** DB migration (US-001) must run before the backend state machine changes take effect. The existing `_migrate_schema()` hook handles this on startup.
- **`check_agent_timeouts` auto-recovery:** The heartbeat reads `ralph.log` and calls `complete_ticket` which uses `COMPLETE_NEXT_STATE`. Updating that dict (US-002) is sufficient — no separate recovery logic needed.
- **Frontend build:** TypeScript compile catches any missed renames. `make restart` rebuilds the frontend bundle — required after any TypeScript changes.
- **Files to modify:**
  - `backend/app/agents.py`
  - `backend/app/agent_loop.py`
  - `backend/app/routers/agents.py`
  - `backend/app/routers/transitions.py`
  - `backend/app/routers/dashboard.py`
  - `backend/app/database.py`
  - `frontend/src/types.ts`
  - `frontend/src/drag-drop.ts`
  - `frontend/src/dashboard.ts`
  - `frontend/src/drag-drop.test.ts`
  - `frontend/src/dashboard.test.ts`

---

## Success Metrics

- Board shows two distinct columns: "Ready for Merge" and "In Merge"
- A ticket picked up by the merger agent immediately moves from "Ready for Merge" to "In Merge" — no ticket stays in "Ready for Merge" while the agent is running
- `GET /api/dashboard/metrics` returns `ready_for_merge` and `in_merge` counts
- Force-unlocking an `in_merge` ticket returns it to `ready_for_merge`
- TypeScript compile produces zero errors
- No existing tickets are lost during the DB migration

---

## Open Questions

- None — implementation plan is fully specified.
