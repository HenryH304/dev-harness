// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { setupRealtimeUpdates, applyStateChange } from './realtime.js';
import type { TicketEvent } from './realtime.js';
import type { WsClient, MessageHandler, StatusHandler, ConnectionStatus } from './ws.js';
import type { Ticket } from './types.js';

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 1,
    project: 'test-project',
    title: 'Test ticket',
    description: 'desc',
    acceptance_criteria: [],
    priority: 1,
    state: 'to_do',
    branch_name: null,
    worktree_path: null,
    current_agent: null,
    assigned_at: null,
    agent_attempts: 0,
    developer_timeouts: 0,
    reviewer_timeouts: 0,
    tester_timeouts: 0,
    merger_timeouts: 0,
    review_rejection_count: 0,
    tester_rejection_count: 0,
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...overrides,
  };
}

function createMockWsClient(): WsClient & {
  _messageHandlers: MessageHandler[];
  _statusHandlers: StatusHandler[];
  _simulateMessage: (data: unknown) => void;
  _simulateStatus: (status: ConnectionStatus) => void;
} {
  const messageHandlers: MessageHandler[] = [];
  const statusHandlers: StatusHandler[] = [];

  return {
    _messageHandlers: messageHandlers,
    _statusHandlers: statusHandlers,
    _simulateMessage(data: unknown) {
      messageHandlers.forEach((h) => h(data));
    },
    _simulateStatus(status: ConnectionStatus) {
      statusHandlers.forEach((h) => h(status));
    },
    connect: vi.fn(),
    disconnect: vi.fn(),
    onMessage(handler: MessageHandler) {
      messageHandlers.push(handler);
    },
    onStatusChange(handler: StatusHandler) {
      statusHandlers.push(handler);
    },
    getStatus() {
      return 'disconnected' as ConnectionStatus;
    },
  };
}

describe('applyStateChange', () => {
  it('updates the state of the matching ticket', () => {
    const tickets = [makeTicket({ id: 1, state: 'to_do' }), makeTicket({ id: 2, state: 'to_do' })];
    const event: TicketEvent = {
      event_type: 'ticket_state_changed',
      ticket_id: 1,
      previous_state: 'to_do',
      new_state: 'in_progress',
      agent_id: 'dev-abc',
      timestamp: '2026-01-01T00:00:00',
    };

    const result = applyStateChange(tickets, event);
    expect(result[0].state).toBe('in_progress');
    expect(result[0].current_agent).toBe('dev-abc');
    expect(result[1].state).toBe('to_do');
  });

  it('does not mutate the original array', () => {
    const tickets = [makeTicket({ id: 1, state: 'to_do' })];
    const event: TicketEvent = {
      event_type: 'ticket_state_changed',
      ticket_id: 1,
      previous_state: 'to_do',
      new_state: 'in_progress',
      agent_id: null,
      timestamp: '2026-01-01T00:00:00',
    };

    const result = applyStateChange(tickets, event);
    expect(result).not.toBe(tickets);
    expect(tickets[0].state).toBe('to_do');
  });

  it('preserves current_agent when event agent_id is null', () => {
    const tickets = [makeTicket({ id: 1, current_agent: 'dev-123' })];
    const event: TicketEvent = {
      event_type: 'ticket_state_changed',
      ticket_id: 1,
      previous_state: 'in_progress',
      new_state: 'ready_for_review',
      agent_id: null,
      timestamp: '2026-01-01T00:00:00',
    };

    const result = applyStateChange(tickets, event);
    expect(result[0].current_agent).toBe('dev-123');
  });
});

describe('setupRealtimeUpdates', () => {
  let boardEl: HTMLElement;
  let dotEl: HTMLElement;
  let labelEl: HTMLElement;
  let wsClient: ReturnType<typeof createMockWsClient>;

  beforeEach(() => {
    boardEl = document.createElement('div');
    dotEl = document.createElement('span');
    dotEl.className = 'dot';
    labelEl = document.createElement('span');
    labelEl.textContent = 'Disconnected';
    wsClient = createMockWsClient();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls wsClient.connect()', () => {
    setupRealtimeUpdates(wsClient, boardEl, dotEl, labelEl, []);
    expect(wsClient.connect).toHaveBeenCalled();
  });

  it('updates dot and label on connected status', () => {
    setupRealtimeUpdates(wsClient, boardEl, dotEl, labelEl, []);
    wsClient._simulateStatus('connected');

    expect(dotEl.classList.contains('connected')).toBe(true);
    expect(labelEl.textContent).toBe('Connected');
  });

  it('updates dot and label on reconnecting status', () => {
    setupRealtimeUpdates(wsClient, boardEl, dotEl, labelEl, []);
    wsClient._simulateStatus('reconnecting');

    expect(dotEl.classList.contains('reconnecting')).toBe(true);
    expect(labelEl.textContent).toBe('Reconnecting...');
  });

  it('updates dot and label on disconnected status', () => {
    setupRealtimeUpdates(wsClient, boardEl, dotEl, labelEl, []);
    wsClient._simulateStatus('connected');
    wsClient._simulateStatus('disconnected');

    expect(dotEl.classList.contains('connected')).toBe(false);
    expect(dotEl.classList.contains('reconnecting')).toBe(false);
    expect(labelEl.textContent).toBe('Disconnected');
  });

  it('re-renders board on state_change event (fallback path)', async () => {
    // Mock apiGet to fail so we test the fallback local update
    const api = await import('./api.js');
    vi.spyOn(api, 'apiGet').mockRejectedValue(new Error('no backend'));

    const tickets = [makeTicket({ id: 1, state: 'to_do' })];
    setupRealtimeUpdates(wsClient, boardEl, dotEl, labelEl, tickets);

    const event: TicketEvent = {
      event_type: 'ticket_state_changed',
      ticket_id: 1,
      previous_state: 'to_do',
      new_state: 'in_progress',
      agent_id: 'dev-abc',
      timestamp: '2026-01-01T00:00:00',
    };

    wsClient._simulateMessage(event);
    // Wait for async handler
    await new Promise((r) => setTimeout(r, 10));

    // Board should have re-rendered — check that ticket is in in_progress column
    const inProgressCol = boardEl.querySelector('[data-column="in_progress"]');
    expect(inProgressCol).not.toBeNull();
    const card = inProgressCol?.querySelector('[data-ticket-id="1"]');
    expect(card).not.toBeNull();
  });

  it('ignores events with no ticket_id', async () => {
    const api = await import('./api.js');
    const spy = vi.spyOn(api, 'apiGet');

    setupRealtimeUpdates(wsClient, boardEl, dotEl, labelEl, []);
    wsClient._simulateMessage({ event_type: 'developer_work_available' });

    await new Promise((r) => setTimeout(r, 10));
    expect(spy).not.toHaveBeenCalled();
  });

  it('re-renders board on agent_assigned event', async () => {
    const api = await import('./api.js');
    const updatedTicket = makeTicket({ id: 1, state: 'in_progress', current_agent: 'developer-abc' });
    vi.spyOn(api, 'apiGet').mockResolvedValue({ ok: true, data: [updatedTicket], status: 200 });

    const tickets = [makeTicket({ id: 1, state: 'to_do' })];
    setupRealtimeUpdates(wsClient, boardEl, dotEl, labelEl, tickets);

    wsClient._simulateMessage({ event_type: 'agent_assigned', ticket_id: 1, new_state: 'in_progress', agent_id: 'developer-abc', timestamp: '2026-01-01T00:00:00' });
    await new Promise((r) => setTimeout(r, 10));

    const inProgressCol = boardEl.querySelector('[data-column="in_progress"]');
    const card = inProgressCol?.querySelector('[data-ticket-id="1"]');
    expect(card).not.toBeNull();
  });

  it('re-renders board with fresh data from API on state change', async () => {
    const api = await import('./api.js');
    const updatedTicket = makeTicket({ id: 1, state: 'in_progress', current_agent: 'dev-xyz' });
    vi.spyOn(api, 'apiGet').mockResolvedValue({ ok: true, data: [updatedTicket], status: 200 });

    const tickets = [makeTicket({ id: 1, state: 'to_do' })];
    setupRealtimeUpdates(wsClient, boardEl, dotEl, labelEl, tickets);

    const event: TicketEvent = {
      event_type: 'ticket_state_changed',
      ticket_id: 1,
      previous_state: 'to_do',
      new_state: 'in_progress',
      agent_id: 'dev-xyz',
      timestamp: '2026-01-01T00:00:00',
    };

    wsClient._simulateMessage(event);
    await new Promise((r) => setTimeout(r, 10));

    const inProgressCol = boardEl.querySelector('[data-column="in_progress"]');
    const card = inProgressCol?.querySelector('[data-ticket-id="1"]');
    expect(card).not.toBeNull();
  });
});
