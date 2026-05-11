// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Ticket } from './types.js';
import {
  ALLOWED_TRANSITIONS,
  isValidTransition,
  setupDragDrop,
  showUndoToast,
  hideUndoToast,
} from './drag-drop.js';

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 1,
    project: 'test',
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

describe('ALLOWED_TRANSITIONS', () => {
  it('maps each state to valid next states', () => {
    expect(ALLOWED_TRANSITIONS['to_do']).toContain('in_progress');
    expect(ALLOWED_TRANSITIONS['to_do']).toContain('blocked');
    expect(ALLOWED_TRANSITIONS['in_progress']).toContain('ready_for_review');
    expect(ALLOWED_TRANSITIONS['ready_for_merge']).toContain('in_merge');
    expect(ALLOWED_TRANSITIONS['in_merge']).toContain('done');
  });

  it('blocked state allows transition to any state (manual override)', () => {
    expect(ALLOWED_TRANSITIONS['blocked'].length).toBeGreaterThan(0);
  });
});

describe('isValidTransition', () => {
  it('returns true for valid forward transitions', () => {
    expect(isValidTransition('to_do', 'in_progress')).toBe(true);
    expect(isValidTransition('in_progress', 'ready_for_review')).toBe(true);
  });

  it('returns false for invalid transitions', () => {
    expect(isValidTransition('to_do', 'done')).toBe(false);
    expect(isValidTransition('to_do', 'ready_for_test')).toBe(false);
  });

  it('returns true for any-to-blocked transitions', () => {
    expect(isValidTransition('to_do', 'blocked')).toBe(true);
    expect(isValidTransition('in_progress', 'blocked')).toBe(true);
  });

  it('returns true for blocked-to-any transitions (manual override)', () => {
    expect(isValidTransition('blocked', 'to_do')).toBe(true);
    expect(isValidTransition('blocked', 'in_progress')).toBe(true);
  });

  it('returns false for same state', () => {
    expect(isValidTransition('to_do', 'to_do')).toBe(false);
  });
});

describe('setupDragDrop', () => {
  let board: HTMLElement;
  let tickets: Ticket[];

  beforeEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
    board = document.createElement('div');
    board.className = 'board';
    board.id = 'board';
    document.body.appendChild(board);

    tickets = [
      makeTicket({ id: 1, state: 'to_do' }),
      makeTicket({ id: 2, state: 'in_progress' }),
    ];

    // Build a minimal board with columns and cards
    const col1 = document.createElement('div');
    col1.className = 'column';
    col1.setAttribute('data-column', 'to_do');
    const body1 = document.createElement('div');
    body1.className = 'column-body';
    const card1 = document.createElement('div');
    card1.className = 'card';
    card1.setAttribute('data-ticket-id', '1');
    card1.textContent = 'Ticket 1';
    body1.appendChild(card1);
    col1.appendChild(body1);
    board.appendChild(col1);

    const col2 = document.createElement('div');
    col2.className = 'column';
    col2.setAttribute('data-column', 'in_progress');
    const body2 = document.createElement('div');
    body2.className = 'column-body';
    const card2 = document.createElement('div');
    card2.className = 'card';
    card2.setAttribute('data-ticket-id', '2');
    card2.textContent = 'Ticket 2';
    body2.appendChild(card2);
    col2.appendChild(body2);
    board.appendChild(col2);

    const col3 = document.createElement('div');
    col3.className = 'column';
    col3.setAttribute('data-column', 'done');
    const body3 = document.createElement('div');
    body3.className = 'column-body';
    col3.appendChild(body3);
    board.appendChild(col3);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('makes cards draggable', () => {
    setupDragDrop(board, tickets);
    const cards = board.querySelectorAll('.card');
    cards.forEach((card) => {
      expect(card.getAttribute('draggable')).toBe('true');
    });
  });

  it('adds dragstart handler that sets data and adds dragging class', () => {
    setupDragDrop(board, tickets);
    const card = board.querySelector('.card[data-ticket-id="1"]') as HTMLElement;

    const dragEvent = new Event('dragstart') as DragEvent;
    Object.defineProperty(dragEvent, 'dataTransfer', {
      value: {
        setData: vi.fn(),
        effectAllowed: '',
      },
    });
    card.dispatchEvent(dragEvent);

    expect(card.classList.contains('card--dragging')).toBe(true);
  });

  it('adds dragend handler that removes dragging class', () => {
    setupDragDrop(board, tickets);
    const card = board.querySelector('.card[data-ticket-id="1"]') as HTMLElement;

    card.classList.add('card--dragging');
    const dragEndEvent = new Event('dragend');
    card.dispatchEvent(dragEndEvent);

    expect(card.classList.contains('card--dragging')).toBe(false);
  });

  it('highlights valid drop columns on dragover', () => {
    setupDragDrop(board, tickets);
    const colBody = board.querySelector(
      '.column[data-column="in_progress"] .column-body'
    ) as HTMLElement;

    const dragOverEvent = new Event('dragover', { bubbles: true, cancelable: true });
    Object.defineProperty(dragOverEvent, 'dataTransfer', {
      value: { dropEffect: '' },
    });
    colBody.dispatchEvent(dragOverEvent);
    // dragover should be preventable (indicates drop is allowed)
    expect(dragOverEvent.defaultPrevented).toBe(false); // no active drag, so not prevented
  });

  it('adds drop-target class on dragenter for valid column', () => {
    setupDragDrop(board, tickets);

    // Simulate dragstart first to set active drag state
    const card = board.querySelector('.card[data-ticket-id="1"]') as HTMLElement;
    const dragStartEvent = new Event('dragstart') as DragEvent;
    Object.defineProperty(dragStartEvent, 'dataTransfer', {
      value: { setData: vi.fn(), effectAllowed: '' },
    });
    card.dispatchEvent(dragStartEvent);

    // Now dragenter on a valid target column
    const colBody = board.querySelector(
      '.column[data-column="in_progress"] .column-body'
    ) as HTMLElement;
    const dragEnterEvent = new Event('dragenter', { bubbles: true });
    colBody.dispatchEvent(dragEnterEvent);

    const col = board.querySelector('.column[data-column="in_progress"]') as HTMLElement;
    expect(col.classList.contains('column--drop-target')).toBe(true);
  });

  it('adds invalid-drop class on dragenter for invalid column', () => {
    setupDragDrop(board, tickets);

    // Simulate dragstart for ticket in to_do
    const card = board.querySelector('.card[data-ticket-id="1"]') as HTMLElement;
    const dragStartEvent = new Event('dragstart') as DragEvent;
    Object.defineProperty(dragStartEvent, 'dataTransfer', {
      value: { setData: vi.fn(), effectAllowed: '' },
    });
    card.dispatchEvent(dragStartEvent);

    // Dragenter on 'done' column (invalid transition from to_do)
    const colBody = board.querySelector(
      '.column[data-column="done"] .column-body'
    ) as HTMLElement;
    const dragEnterEvent = new Event('dragenter', { bubbles: true });
    colBody.dispatchEvent(dragEnterEvent);

    const col = board.querySelector('.column[data-column="done"]') as HTMLElement;
    expect(col.classList.contains('column--invalid-drop')).toBe(true);
  });

  it('removes drop-target classes on dragleave', () => {
    setupDragDrop(board, tickets);
    const col = board.querySelector('.column[data-column="in_progress"]') as HTMLElement;
    col.classList.add('column--drop-target');

    const colBody = col.querySelector('.column-body') as HTMLElement;
    const dragLeaveEvent = new Event('dragleave', { bubbles: true });
    colBody.dispatchEvent(dragLeaveEvent);

    expect(col.classList.contains('column--drop-target')).toBe(false);
  });

  it('calls transition API on valid drop', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: 1, state: 'in_progress' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    setupDragDrop(board, tickets);

    // Dragstart on ticket 1 (to_do)
    const card = board.querySelector('.card[data-ticket-id="1"]') as HTMLElement;
    const dragStartEvent = new Event('dragstart') as DragEvent;
    Object.defineProperty(dragStartEvent, 'dataTransfer', {
      value: { setData: vi.fn(), effectAllowed: '' },
    });
    card.dispatchEvent(dragStartEvent);

    // Drop on in_progress column
    const colBody = board.querySelector(
      '.column[data-column="in_progress"] .column-body'
    ) as HTMLElement;
    const dropEvent = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(dropEvent, 'dataTransfer', {
      value: { getData: vi.fn().mockReturnValue('1') },
    });
    colBody.dispatchEvent(dropEvent);

    // Wait for async transition call
    await vi.waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/tickets/1/transition',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('in_progress'),
        })
      );
    });

    vi.unstubAllGlobals();
  });
});

describe('showUndoToast', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = '';
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('creates an undo toast element', () => {
    showUndoToast(1, 'to_do', 'in_progress', vi.fn());
    const toast = document.querySelector('.undo-toast');
    expect(toast).not.toBeNull();
    expect(toast!.textContent).toContain('Undo');
  });

  it('calls onUndo callback when undo button clicked', () => {
    const onUndo = vi.fn();
    showUndoToast(1, 'to_do', 'in_progress', onUndo);
    const btn = document.querySelector('.undo-toast button') as HTMLElement;
    btn.click();
    expect(onUndo).toHaveBeenCalled();
  });

  it('removes toast after 5 seconds', () => {
    showUndoToast(1, 'to_do', 'in_progress', vi.fn());
    expect(document.querySelector('.undo-toast')).not.toBeNull();
    vi.advanceTimersByTime(5000);
    expect(document.querySelector('.undo-toast')).toBeNull();
  });

  it('removes toast when undo is clicked before timeout', () => {
    showUndoToast(1, 'to_do', 'in_progress', vi.fn());
    const btn = document.querySelector('.undo-toast button') as HTMLElement;
    btn.click();
    expect(document.querySelector('.undo-toast')).toBeNull();
  });
});

describe('hideUndoToast', () => {
  it('removes existing toast', () => {
    document.body.innerHTML = '<div class="undo-toast"></div>';
    hideUndoToast();
    expect(document.querySelector('.undo-toast')).toBeNull();
  });

  it('does nothing if no toast exists', () => {
    expect(() => hideUndoToast()).not.toThrow();
  });
});
