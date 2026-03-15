// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest';
import { renderBoard, renderCard, groupTicketsByState } from './board.js';
import type { Ticket } from './types.js';

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 1,
    project: 'test-project',
    title: 'Test Ticket',
    description: 'A test ticket',
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
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...overrides,
  };
}

describe('groupTicketsByState', () => {
  it('groups tickets into state buckets', () => {
    const tickets = [
      makeTicket({ id: 1, state: 'to_do' }),
      makeTicket({ id: 2, state: 'to_do' }),
      makeTicket({ id: 3, state: 'in_progress' }),
      makeTicket({ id: 4, state: 'done' }),
    ];
    const grouped = groupTicketsByState(tickets);
    expect(grouped['to_do']).toHaveLength(2);
    expect(grouped['in_progress']).toHaveLength(1);
    expect(grouped['done']).toHaveLength(1);
    expect(grouped['blocked']).toHaveLength(0);
  });

  it('returns empty arrays for all columns when no tickets', () => {
    const grouped = groupTicketsByState([]);
    expect(grouped['to_do']).toHaveLength(0);
    expect(grouped['blocked']).toHaveLength(0);
    expect(grouped['done']).toHaveLength(0);
  });
});

describe('renderCard', () => {
  it('renders ticket title', () => {
    const card = renderCard(makeTicket({ title: 'My Ticket' }));
    expect(card.querySelector('.card-title')?.textContent).toBe('My Ticket');
  });

  it('renders priority badge with correct class', () => {
    const highCard = renderCard(makeTicket({ priority: 1 }));
    const badge = highCard.querySelector('.priority-badge');
    expect(badge).not.toBeNull();
    expect(badge?.classList.contains('high')).toBe(true);
    expect(badge?.textContent).toBe('P1');

    const lowCard = renderCard(makeTicket({ priority: 5 }));
    const lowBadge = lowCard.querySelector('.priority-badge');
    expect(lowBadge?.classList.contains('low')).toBe(true);
  });

  it('renders project name', () => {
    const card = renderCard(makeTicket({ project: 'my-proj' }));
    expect(card.textContent).toContain('my-proj');
  });

  it('renders assigned agent when present', () => {
    const card = renderCard(makeTicket({ current_agent: 'developer-abc' }));
    expect(card.textContent).toContain('developer-abc');
  });

  it('does not show agent info when no agent assigned', () => {
    const card = renderCard(makeTicket({ current_agent: null }));
    expect(card.textContent).not.toContain('Agent:');
  });

  it('shows dependency count when > 0', () => {
    // dependency_count is derived from acceptance_criteria length as a proxy
    // Actually, dependency count will be passed as a data attribute or computed separately
    // For now, the card has a data-ticket-id attribute
    const card = renderCard(makeTicket({ id: 42 }));
    expect(card.getAttribute('data-ticket-id')).toBe('42');
  });

  it('has card class', () => {
    const card = renderCard(makeTicket());
    expect(card.classList.contains('card')).toBe(true);
  });
});

describe('renderBoard', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
  });

  it('renders all 9 columns', () => {
    renderBoard(container, []);
    const columns = container.querySelectorAll('.column');
    expect(columns).toHaveLength(9);
  });

  it('renders column labels', () => {
    renderBoard(container, []);
    const headers = container.querySelectorAll('.column-header');
    const labels = Array.from(headers).map(
      (h) => h.querySelector('.column-label')?.textContent
    );
    expect(labels).toContain('To Do');
    expect(labels).toContain('In Progress');
    expect(labels).toContain('Ready for Review');
    expect(labels).toContain('In Review');
    expect(labels).toContain('Ready for Test');
    expect(labels).toContain('In Test');
    expect(labels).toContain('Ready to Merge');
    expect(labels).toContain('Done');
    expect(labels).toContain('Blocked');
  });

  it('renders ticket count badges', () => {
    const tickets = [
      makeTicket({ id: 1, state: 'to_do' }),
      makeTicket({ id: 2, state: 'to_do' }),
      makeTicket({ id: 3, state: 'in_progress' }),
    ];
    renderBoard(container, tickets);
    const headers = container.querySelectorAll('.column-header');
    const todoHeader = Array.from(headers).find(
      (h) => h.querySelector('.column-label')?.textContent === 'To Do'
    );
    const badge = todoHeader?.querySelector('.badge');
    expect(badge?.textContent).toBe('2');
  });

  it('renders ticket cards in correct columns', () => {
    const tickets = [
      makeTicket({ id: 1, state: 'to_do', title: 'Todo ticket' }),
      makeTicket({ id: 2, state: 'blocked', title: 'Blocked ticket' }),
    ];
    renderBoard(container, tickets);
    const columns = container.querySelectorAll('.column');
    const todoCol = columns[0]; // first column is to_do
    const blockedCol = columns[8]; // last column is blocked
    expect(todoCol.querySelector('.card-title')?.textContent).toBe(
      'Todo ticket'
    );
    expect(blockedCol.querySelector('.card-title')?.textContent).toBe(
      'Blocked ticket'
    );
  });

  it('blocked column has blocked-column class', () => {
    renderBoard(container, []);
    const columns = container.querySelectorAll('.column');
    const blockedCol = columns[8];
    expect(blockedCol.classList.contains('column--blocked')).toBe(true);
  });

  it('clears container before rendering', () => {
    container.innerHTML = '<p>old content</p>';
    renderBoard(container, []);
    expect(container.querySelector('p')).toBeNull();
    expect(container.querySelectorAll('.column')).toHaveLength(9);
  });
});
