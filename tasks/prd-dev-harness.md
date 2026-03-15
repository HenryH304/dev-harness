# PRD: Dev Harness - Multi-Agent Task Management System

## Introduction

Dev Harness is a Trello-like task management system designed for autonomous multi-agent software development workflows. It visualizes tickets as cards moving through workflow states (columns) while different specialized agents automatically process tickets based on their current state. The system combines visual project management with intelligent agent orchestration to enable parallel, autonomous development workflows.

**Tech stack:** TypeScript + Vite (frontend) · FastAPI + Python (backend) · SQLite (database) · Redis (event broker) · Docker Compose (deployment)

## Goals

- Create a visual kanban board interface for tracking ticket progress through development workflow
- Enable autonomous multi-agent processing with specialized agents for development, review, testing, and merging
- Provide Ralph-compatible task structure for seamless integration with existing automation
- Implement event-driven agent triggering with dependency management and conflict resolution
- Support failure recovery flows with detailed commenting and state rollback capabilities
- Enable manual oversight through managing agent controls and workflow monitoring

## User Stories

### US-DH-001: Core ticket data model
**Description:** As a developer, I need a robust ticket data structure that supports workflow states, dependencies, and agent processing.

**Acceptance Criteria:**
- [ ] Create ticket schema with Ralph-compatible task structure (title, description, acceptance criteria, priority)
- [ ] Add `project` field to ticket (folder name of the Ralph project, e.g. `graph_business`)
- [ ] Add `branch_name` field to ticket (git branch name for the worktree, e.g. `ticket/US-DH-001`)
- [ ] Add `worktree_path` field to ticket (filesystem path to the git worktree)
- [ ] Add state field supporting: "to do", "in progress", "ready for review", "in review", "ready for test", "in test", "ready to merge", "done", "blocked"
- [ ] Add dependency tracking via a separate `ticket_dependencies` join table with fields: `ticket_id` (the blocked ticket), `depends_on_ticket_id` (the blocking ticket), `created_at`
- [ ] `blocked_by` and `blocks` are derived views of the join table — not stored directly on the ticket
- [ ] Cycle detection runs on insert to prevent circular dependencies
- [ ] Add agent assignment tracking (current_agent, assigned_at timestamp)
- [ ] Add `agent_attempts` counter to track total number of agent pickup attempts per ticket
- [ ] Add `timeout_count` counter per agent type on the ticket (e.g. `developer_timeouts`, `reviewer_timeouts`, `tester_timeouts`, `merger_timeouts`)
- [ ] Add `review_rejection_count` counter to track how many times a ticket has been sent back from review to development
- [ ] Add locking mechanism to prevent concurrent processing
- [ ] Database migration creates tickets table successfully
- [ ] Unit tests for ticket model validation
- [ ] Typecheck passes

### US-DH-002: Notes and comments system
**Description:** As an agent or manager, I want to add timestamped notes to tickets so I can track progress, failures, and decisions.

**Acceptance Criteria:**
- [ ] Create notes table linked to tickets (ticket_id, author, content, timestamp, note_type)
- [ ] Support note types: "progress", "failure", "review", "test_result", "general"
- [ ] Content supports markdown with links to images and references
- [ ] Notes ordered by timestamp (newest first)
- [ ] API endpoints for adding/retrieving notes
- [ ] Unit tests for notes creation and retrieval
- [ ] Golden path e2e test: create ticket, add multiple notes, verify chronological order
- [ ] Typecheck passes

### US-DH-003: Visual kanban board interface
**Description:** As a user, I want to see tickets organized in columns by state so I can track project progress at a glance.

**Acceptance Criteria:**
- [ ] Render 9 columns: To Do, In Progress, Ready for Review, In Review, Ready for Test, In Test, Ready to Merge, Done, Blocked
- [ ] Display tickets as cards within appropriate state columns
- [ ] Show ticket title, priority, assigned agent, and dependency count on cards
- [ ] Real-time updates when tickets move between states
- [ ] Responsive design works on desktop and tablet
- [ ] Professional styling suitable for project management
- [ ] Typecheck passes
- [ ] Verify in browser using dev-browser skill

### US-DH-004: Manual drag-and-drop state changes
**Description:** As a managing agent or user, I want to manually move tickets between states for workflow overrides.

**Acceptance Criteria:**
- [ ] Drag and drop tickets between columns to change state
- [ ] Validate state transitions (prevent invalid moves)
- [ ] Release agent lock when manually moved out of "in progress" states
- [ ] Auto-generate note explaining manual state change with timestamp
- [ ] Visual feedback during drag operation (ghost card, valid drop zones)
- [ ] Undo capability for accidental moves
- [ ] Typecheck passes
- [ ] Verify in browser using dev-browser skill

### US-DH-005: Agent type definitions and prompts
**Description:** As a system administrator, I need predefined agent types with specialized prompts for different workflow stages.

**Acceptance Criteria:**
- [ ] Define 4 agent types: Developer, Reviewer, Tester, Merger
- [ ] Create prompt templates for each agent type stored in configuration
- [ ] Developer prompt: loaded from `/home/henry/Projects/my-ralph-template/prompt.md` — focuses on code implementation, testing, documentation
- [ ] Reviewer prompt: focuses on code quality, standards, design review
- [ ] Tester prompt: focuses on functionality validation, edge cases, bug detection
- [ ] Merger prompt: focuses on integration safety, conflict resolution, deployment
- [ ] Prompts configurable via environment variables or config files
- [ ] Unit tests for prompt loading and validation
- [ ] Typecheck passes

### US-DH-006: Event-driven state transition system
**Description:** As a system, I need automatic event triggering when tickets change states to notify appropriate agents.

**Acceptance Criteria:**
- [ ] Create event system that triggers on state changes
- [ ] Events include: ticket_ready_for_pickup, ticket_completed, ticket_failed
- [ ] Events carry ticket data, previous state, new state, and timestamp
- [ ] Event handlers can be registered for specific state transitions
- [ ] Failed event processing doesn't break the workflow (error handling)
- [ ] Event log for debugging and audit trail
- [ ] Unit tests for event generation and handling
- [ ] Golden path e2e test: state change triggers event, verify event data
- [ ] Typecheck passes

### US-DH-007: Agent work pickup system
**Description:** As an agent, I want to automatically receive work when tickets enter my responsibility state.

**Acceptance Criteria:**
- [ ] Agent registration system (agent_id, type, status: available/busy)
- [ ] Automatic assignment when tickets enter agent-specific states
- [ ] Ticket locking prevents multiple agents from picking up same work
- [ ] Agent receives ticket context, requirements, and previous notes
- [ ] Timeout mechanism releases locked tickets if agent becomes unresponsive
- [ ] Queue system for multiple available agents of same type
- [ ] Unit tests for agent assignment logic
- [ ] Golden path e2e test: ticket moves to "to do", developer agent picks it up automatically
- [ ] Typecheck passes

### US-DH-008: Agent work completion flow
**Description:** As an agent, I want to complete my work and move tickets to the next appropriate state with progress notes.

**Acceptance Criteria:**
- [ ] Agents can mark work as completed (success) or failed (with reason)
- [ ] Successful completion moves ticket to next workflow state
- [ ] Failed completion moves ticket back to "to do" with failure notes
- [ ] Completion includes agent's work summary and next steps
- [ ] Release agent lock and update agent status to available
- [ ] Validate work completion before state transition
- [ ] Unit tests for completion workflows (success and failure paths)
- [ ] Golden path e2e test: agent completes work, ticket advances, lock released
- [ ] Typecheck passes

### US-DH-009: Dependency management system
**Description:** As a project manager, I want tickets to respect dependencies so dependent work doesn't start until prerequisites are completed.

**Acceptance Criteria:**
- [ ] Create dependency relationships (ticket A blocks ticket B)
- [ ] Prevent tickets from entering "in progress" if dependencies aren't in "done" state
- [ ] Visual indicators on board showing blocked tickets
- [ ] Dependency cycle detection and prevention
- [ ] Automatic unblocking when dependencies complete
- [ ] Dependency graph visualization for complex relationships
- [ ] Unit tests for dependency validation and cycle detection
- [ ] Golden path e2e test: create dependent tickets, verify blocking behavior
- [ ] Typecheck passes
- [ ] Verify in browser using dev-browser skill

### US-DH-010: Ralph integration and task compatibility
**Description:** As a developer, I want to import existing Ralph tasks as tickets and export tickets as Ralph-compatible tasks.

**Acceptance Criteria:**
- [ ] Import function converts Ralph prd.json user stories to board tickets
- [ ] Export function generates Ralph-compatible task definitions
- [ ] Preserve acceptance criteria, priorities, and user story structure
- [ ] Map Ralph task status to appropriate board states
- [ ] Batch import/export capabilities for multiple tasks
- [ ] Validation ensures data integrity during conversion
- [ ] Unit tests for import/export functions with sample Ralph data
- [ ] Golden path e2e test: import Ralph tasks, process through workflow, export results
- [ ] Typecheck passes

### US-DH-011: Real-time board updates
**Description:** As a user, I want to see live updates on the board when agents or other users modify tickets.

**Acceptance Criteria:**
- [ ] WebSocket connection for real-time updates
- [ ] Update UI immediately when ticket states change
- [ ] Show agent activity indicators (which agents are working on what)
- [ ] Live notes/comments appearing without page refresh
- [ ] Connection status indicator and auto-reconnect on failure
- [ ] Batch updates to prevent UI flooding during high activity
- [ ] Unit tests for WebSocket message handling
- [ ] Verify in browser using dev-browser skill
- [ ] Typecheck passes

### US-DH-012: Administrative dashboard
**Description:** As a managing agent, I want a dashboard to monitor agent performance, workflow bottlenecks, and system health.

**Acceptance Criteria:**
- [ ] Dashboard showing active agents and their current work
- [ ] Workflow metrics: average time in each state, bottleneck identification
- [ ] Failed ticket analysis and common failure patterns
- [ ] Agent performance metrics: completion rate, average time per task
- [ ] System health indicators: event processing lag, database performance
- [ ] Manual controls: pause/resume agents, force unlock stuck tickets
- [ ] Settings panel: adjust per-agent-type timeouts, max concurrency per column, and escalation thresholds
- [ ] Timeout analytics: show timeout counts per agent type across all tickets to inform timeout tuning
- [ ] Export workflow analytics as reports
- [ ] Typecheck passes
- [ ] Verify in browser using dev-browser skill

## Functional Requirements

### Core Data Model
- **FR-1:** Tickets must contain Ralph-compatible structure with title, description, acceptance criteria, priority, and custom workflow state
- **FR-2:** State transitions must follow defined workflow: to do → in progress → ready for review → in review → ready for test → in test → ready to merge → done. Any ticket can transition to "blocked" when escalation threshold is hit or hard dependencies prevent progress. "Blocked" tickets require manual intervention to resume.
- **FR-3:** Failed tickets must return to "to do" state with failure reason and suggested fixes in notes
- **FR-4:** Dependency relationships must prevent dependent tickets from progressing until prerequisites complete

### Agent System
- **FR-5:** Four predefined agent types (Developer, Reviewer, Tester, Merger) with specialized prompts for their workflow stage
- **FR-6:** Event-driven agent triggering when tickets enter states requiring their expertise
- **FR-7:** Simple ticket locking ensures only one agent processes a ticket at a time
- **FR-8:** Agent timeout mechanism (configurable per agent type; defaults: Developer 20min, Reviewer 10min, Tester 10min, Merger 5min) releases abandoned tickets and increments `agent_attempts`
- **FR-9:** Agents must add progress notes when completing or failing tickets
- **FR-10:** Track `agent_attempts` per ticket; flag tickets with repeated timeouts or failures for review
- **FR-11:** Track `review_rejection_count` per ticket; when threshold of 3 is reached, halt processing, move ticket to "blocked" state, and alert Henry to notify Derrick
- **FR-12:** On ticket creation, automatically create a git worktree branched from `main` for the associated project. The worktree persists until the ticket is merged. On merge, delete the worktree and branch.
- **FR-13:** All agent work (development, review, testing) is performed within the ticket's dedicated worktree — never directly on `main`
- **FR-14:** Each agent is instantiated with a fresh context scoped only to its assigned task. Agent lifecycle begins at task pickup and ends at task completion, failure, or timeout. No state persists between agent runs.
- **FR-15:** Each worktree gets its own `progress.txt` and `ralph.log` files scoped to that agent run. These are listed in `.gitignore` and never committed to any branch.
- **FR-16:** `AGENTS.md` is committed to `main` and inherited by all worktrees — it defines the agent context and instructions that each agent receives on startup.

### User Interface
- **FR-17:** Visual kanban board with 9 columns representing workflow states (including Blocked)
- **FR-18:** Real-time updates via WebSocket for live collaboration
- **FR-19:** Manual drag-and-drop state changes with validation and automatic note generation
- **FR-20:** Dependency visualization showing blocked tickets and relationships

### Integration
- **FR-21:** Ralph task import/export maintaining data fidelity and task structure
- **FR-22:** RESTful API for external integrations and agent communication
- **FR-23:** Event system supports Redis Pub/Sub for agent coordination and WebSocket broadcast to UI
- **FR-24:** System-wide agent cap (default 10, configurable). When at capacity, new agents are prioritised by column proximity to "done" (Merger > Tester > Reviewer > Developer) to minimise WIP.

## Non-Goals (Out of Scope)

- No time tracking or detailed productivity analytics beyond basic workflow metrics
- No user authentication system (single-user or trusted environment assumed)
- No custom workflow configuration (fixed 8-state workflow)
- No integration with external issue trackers (GitHub, Jira) in initial version
- No file attachment system beyond links in notes
- No advanced agent marketplace or custom agent creation
- No separate board per project — all projects share a single board, filtered by project
- No mobile app development (responsive web interface only)

## Design Considerations

### User Interface
- **Modern kanban design:** Clean, card-based interface similar to Trello with professional styling
- **Agent activity indicators:** Visual cues showing which agents are actively working
- **Dependency visualization:** Clear indicators for blocked tickets and dependency chains
- **Real-time feedback:** Immediate visual updates for state changes and agent actions
- **Accessibility:** Keyboard navigation and screen reader support for workflow management

### Server Configuration
- **Default port:** `9080` (configurable via `config.json` or `PORT` environment variable)
- **Deployment:** Fully Dockerised. The system runs as a multi-container Docker Compose setup:
  - `frontend` — TypeScript/Vite static build served via nginx
  - `backend` — FastAPI application
  - `redis` — Redis message broker
  - `db` — SQLite volume mount (or optionally PostgreSQL for production)
  - A single `docker-compose up` starts the full stack. All configuration via environment variables in `.env` file.

### Technical Architecture
- **Frontend:** Lightweight TypeScript (Vite + React or vanilla TS)
- **Backend:** FastAPI (Python) for REST API, WebSockets, and database interaction
- **Database:** SQLite via SQLAlchemy or Tortoise ORM
- **Event-driven backbone:** Redis Pub/Sub — agents publish events to Redis channels, FastAPI subscribes and broadcasts state changes to connected UI clients via WebSocket
- **WebSocket real-time:** FastAPI WebSocket endpoints push Redis events to the UI in real-time
- **Simple locking:** Prevent race conditions with straightforward ticket locks in SQLite
- **Ralph compatibility:** Seamless integration with existing Ralph automation workflows
- **Git worktree per ticket:** Each ticket creates a dedicated git worktree branched from `main`. The worktree and branch persist through the full workflow (development → review → testing) and are only merged back into `main` and deleted once the ticket passes testing and reaches "ready to merge". This ensures each agent works in an isolated environment and changes don't interfere with other in-flight tickets.
- **Worktree file management:** `progress.txt` and `ralph.log` are generated per worktree and excluded via `.gitignore` — never committed. `AGENTS.md` lives on `main` and is inherited by all worktrees, providing consistent agent instructions across all runs.

## Technical Considerations

### Database Design
- **Tickets table:** Core entity with state, assignments, attempt counters, branch/worktree info, timestamps
- **Ticket dependencies table:** Join table (`ticket_id`, `depends_on_ticket_id`, `created_at`) representing hard block relationships. `blocked_by` and `blocks` are derived from this table, not stored on the ticket itself. Cycle detection enforced on insert.
- **Notes table:** Timestamped comments linked to tickets with markdown support
- **Events table:** Audit trail for all state changes and agent actions
- **Agent registry:** Track agent availability and work assignments
- **Settings table:** Key-value store for configurable system settings including per-agent-type timeouts, max concurrency per column, and escalation thresholds. Editable via the admin dashboard UI or a config file (e.g. `config.json` in the project root). Config file takes precedence over database settings on startup.
- **Redis:** Message broker for event-driven agent coordination. Agents publish to Redis channels (e.g. `ticket:state_change`, `agent:completed`, `agent:failed`). FastAPI subscribes and broadcasts to WebSocket clients. Also used for distributed locking to prevent concurrent agent pickup of the same ticket.

### Agent Integration
- **Event-driven coordination:** Agents subscribe to relevant state change events
- **Configurable prompts:** Agent behavior customizable via environment variables
- **Error resilience:** Failed agent processing doesn't break workflow progression
- **Timeout handling:** Automatic cleanup for unresponsive agents

### Performance Requirements
- **Real-time responsiveness:** State changes visible within 100ms
- **Concurrent agent support:** Maximum 10 agents per column processing tickets simultaneously (configurable, default 10)
- **Dependency resolution:** Cycle detection completes within 1 second for complex graphs
- **Board loading:** Initial board render under 2 seconds for 100+ tickets

### Ralph Integration
- **Task compatibility:** Preserve all Ralph user story fields and acceptance criteria
- **Bidirectional sync:** Import Ralph projects and export completed work
- **State mapping:** Intelligent conversion between Ralph task states and board workflow

## Success Metrics

### Workflow Efficiency
- **Agent utilization:** 80%+ of agent time spent on productive work (not waiting)
- **Ticket cycle time:** Average time from "to do" to "done" under 24 hours for typical tasks
- **Failure rate:** Less than 20% of tickets require rework due to failed reviews/tests
- **Dependency resolution:** Blocked tickets unblocked within 1 hour of dependency completion

### System Performance
- **Real-time updates:** 99%+ of state changes reflected in UI within 100ms
- **Agent responsiveness:** Agents pick up available work within 30 seconds
- **System uptime:** 99.5% availability with graceful degradation during failures
- **Data integrity:** Zero data loss or corruption during concurrent agent operations

### User Experience
- **Manual override usage:** Less than 10% of state changes require manual intervention
- **Dashboard usefulness:** Managing agents can identify bottlenecks within 5 minutes
- **Ralph integration:** 100% fidelity for imported/exported task data
- **Learning curve:** New users can understand board status within 2 minutes

## Open Questions

### Agent Coordination — Resolved

- **Context:** Agents receive a single task and operate without additional context or clarification. Each agent is a single Ralph loop with a configurable timeout — same execution model as a Ralph loop.
- **Agent lifecycle:** Each agent is spun up fresh with a new context for a single task. Once the task is complete (or times out/fails), the agent is torn down. Agents have no memory or state between tasks — they are stateless and single-purpose.
- **Agent prompts:** Each agent type receives a different base prompt based on their role:
  - **Developer:** Uses `prompt.md` from `/home/henry/Projects/my-ralph-template/prompt.md` as the base prompt
  - **Reviewer:** Custom prompt to be developed — focused on code quality, standards, design review
  - **Tester:** Custom prompt to be developed — focused on functionality validation, edge cases, bug detection
  - **Merger:** Custom prompt to be developed — focused on integration safety, conflict resolution, deployment
- **Conflicting recommendations / review failures:** When a reviewer finds issues:
  - All issues are noted on the **original ticket** as failure notes
  - The original acceptance criteria is marked as completed (work was done)
  - New acceptance criteria / change notes are appended to the ticket describing required fixes
  - Ticket is returned to **"to do"** for a developer agent to pick up and implement the changes
  - This creates a clean audit trail while keeping the full history on one ticket
- **Timeouts:** Configurable per agent type, defaults:
  - Developer: 20 minutes
  - Reviewer: 10 minutes
  - Tester: 10 minutes
  - Merger: 5 minutes

### Workflow Optimization — Resolved

- **Parallel agents per column:** Multiple agents of the same type can work concurrently within their column. For example, 3 reviewer agents can each process a different ticket in "ready for review" simultaneously.
- **Agent concurrency is configurable:** A user (or later a manager agent) can adjust the number of agents allowed to process tickets in a particular column. Each column has a max concurrency setting with a hard cap of 10 agents per column.
- **Agent-to-column binding:** Agent types are bound to specific columns — Developer agents only pick up from "to do", Reviewer agents only from "ready for review", etc. Agents never cross column boundaries.
- **Flow control:** The workflow stages themselves control overall throughput — concurrency within a column doesn't bypass the sequential stage progression (e.g. a ticket must pass review before entering testing).
- **Future:** A manager agent could dynamically adjust concurrency per column based on queue depth and bottleneck detection.

- **Failure and retry tracking:** Each ticket tracks:
  - `agent_attempts` — total number of times an agent has attempted the ticket (incremented on each pickup). Repeated timeouts or failures on the same ticket by different agents signals a systemic problem.
  - `review_rejection_count` — number of times a ticket has been sent back from review to development.
  - **Threshold:** If `review_rejection_count` reaches 3, processing halts automatically, an alert is raised, and Henry is notified to flag it for Derrick's attention. The ticket is moved to the "blocked" column and no further agents pick it up until manually unblocked.
- How can we automatically detect and resolve common workflow bottlenecks? *(open)*
- **Dependency type:** Hard blocks only for now. A ticket cannot progress past "to do" if any of its dependencies are not in "done" state. Soft dependencies are out of scope for the initial version.

### Scaling Considerations — Resolved

- **System-wide agent cap:** Maximum 10 concurrent agents across the entire system (not per column). This cap is configurable.
- **Agent priority — WIP reduction first:** When spinning up a new agent and the system is at or near capacity, priority is given to columns further down the workflow (closer to "done"). This minimises Work In Progress and ensures tickets already in flight are completed before new work is started. Priority order (highest to lowest): Merger → Tester → Reviewer → Developer.
- **Overload prevention:** No new agents are spun up for "to do" if tickets are already waiting in downstream columns (ready for review, ready for test, ready to merge). The system always aims to reduce WIP before pulling in new work.
- Agent priority levels for critical vs routine work — deferred to future version.
- Peak period throttling beyond the system-wide cap — deferred to future version.

### Ralph Integration — Partially Resolved

- **Multiple projects:** The system supports multiple Ralph projects simultaneously. Each ticket is associated with a project identified by its folder name (e.g. `graph_business`, `dev-harness`).
- **Priority:** One project is designated as the active priority project at a time. Agents preferentially pick up tickets from the priority project before processing tickets from other projects. A user (or later a manager agent) can change the active priority project.
- How can we maintain sync with Ralph projects that continue evolving? *(deferred — out of scope for initial version)*
- **Partial import:** Out of scope for initial version — full PRD import only.

---

*PRD Version 1.0 - Created: March 5, 2026*
*Target Implementation: Q1 2026*
