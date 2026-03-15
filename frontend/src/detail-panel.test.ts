// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import * as api from './api.js';
import {
  renderDetailPanel,
  openDetailPanel,
  closeDetailPanel,
  formatNotes,
  formatDependencies,
} from './detail-panel.js';
import type { TicketDetail, Note, DependencyList } from './detail-panel.js';

function makeTicketDetail(overrides: Partial<TicketDetail> = {}): TicketDetail {
  return {
    id: 1,
    project: 'test-project',
    title: 'Test Ticket',
    description: 'A test ticket description',
    acceptance_criteria: ['Criterion 1', 'Criterion 2', 'Criterion 3'],
    priority: 2,
    state: 'in_progress',
    branch_name: 'ticket/1',
    worktree_path: '/tmp/worktree/1',
    current_agent: 'developer-abc123',
    assigned_at: '2026-03-15T10:00:00',
    agent_attempts: 3,
    developer_timeouts: 1,
    reviewer_timeouts: 0,
    tester_timeouts: 2,
    merger_timeouts: 0,
    review_rejection_count: 1,
    created_at: '2026-03-15T09:00:00',
    updated_at: '2026-03-15T10:00:00',
    notes: [
      {
        id: 3,
        ticket_id: 1,
        author: 'developer-abc123',
        content: 'Latest note',
        note_type: 'progress',
        created_at: '2026-03-15T10:30:00',
      },
      {
        id: 2,
        ticket_id: 1,
        author: 'system',
        content: 'State changed to in_progress',
        note_type: 'general',
        created_at: '2026-03-15T10:00:00',
      },
      {
        id: 1,
        ticket_id: 1,
        author: 'reviewer-def456',
        content: 'First note',
        note_type: 'review',
        created_at: '2026-03-15T09:30:00',
      },
    ],
    ...overrides,
  };
}

function makeDependencyList(
  overrides: Partial<DependencyList> = {}
): DependencyList {
  return {
    blocked_by: [
      { id: 2, title: 'Dependency ticket', state: 'in_progress' },
    ],
    blocks: [{ id: 3, title: 'Blocked ticket', state: 'to_do' }],
    ...overrides,
  };
}

describe('renderDetailPanel', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('renders ticket title and description', () => {
    const ticket = makeTicketDetail();
    const panel = renderDetailPanel(ticket, null);
    expect(panel.querySelector('.detail-title')?.textContent).toBe(
      'Test Ticket'
    );
    expect(panel.querySelector('.detail-description')?.textContent).toContain(
      'A test ticket description'
    );
  });

  it('renders acceptance criteria as checkboxes', () => {
    const ticket = makeTicketDetail();
    const panel = renderDetailPanel(ticket, null);
    const checkboxes = panel.querySelectorAll('.detail-criteria li');
    expect(checkboxes.length).toBe(3);
    expect(checkboxes[0].textContent).toContain('Criterion 1');
    expect(checkboxes[1].textContent).toContain('Criterion 2');
    expect(checkboxes[2].textContent).toContain('Criterion 3');
  });

  it('renders state, priority, project, and branch name', () => {
    const ticket = makeTicketDetail();
    const panel = renderDetailPanel(ticket, null);
    const text = panel.textContent ?? '';
    expect(text).toContain('in_progress');
    expect(text).toContain('P2');
    expect(text).toContain('test-project');
    expect(text).toContain('ticket/1');
  });

  it('renders agent attempt counts', () => {
    const ticket = makeTicketDetail();
    const panel = renderDetailPanel(ticket, null);
    const text = panel.textContent ?? '';
    expect(text).toContain('3'); // agent_attempts
  });

  it('renders timeout counts per type', () => {
    const ticket = makeTicketDetail();
    const panel = renderDetailPanel(ticket, null);
    const text = panel.textContent ?? '';
    expect(text).toContain('1'); // developer_timeouts
    expect(text).toContain('2'); // tester_timeouts
  });

  it('renders review_rejection_count', () => {
    const ticket = makeTicketDetail();
    const panel = renderDetailPanel(ticket, null);
    const text = panel.textContent ?? '';
    expect(text).toContain('1'); // review_rejection_count
  });

  it('renders notes in reverse chronological order', () => {
    const ticket = makeTicketDetail();
    const panel = renderDetailPanel(ticket, null);
    const notes = panel.querySelectorAll('.detail-note');
    expect(notes.length).toBe(3);
    // First displayed note should be the latest (id=3)
    expect(notes[0].textContent).toContain('Latest note');
    expect(notes[1].textContent).toContain('State changed to in_progress');
    expect(notes[2].textContent).toContain('First note');
  });

  it('renders note author and type', () => {
    const ticket = makeTicketDetail();
    const panel = renderDetailPanel(ticket, null);
    const firstNote = panel.querySelector('.detail-note');
    const text = firstNote?.textContent ?? '';
    expect(text).toContain('developer-abc123');
    expect(text).toContain('progress');
  });

  it('renders dependency list when provided', () => {
    const ticket = makeTicketDetail();
    const deps = makeDependencyList();
    const panel = renderDetailPanel(ticket, deps);
    const text = panel.textContent ?? '';
    expect(text).toContain('Dependency ticket');
    expect(text).toContain('Blocked ticket');
  });

  it('shows blocked_by and blocks sections', () => {
    const ticket = makeTicketDetail();
    const deps = makeDependencyList();
    const panel = renderDetailPanel(ticket, deps);
    const text = panel.textContent ?? '';
    expect(text).toContain('Blocked By');
    expect(text).toContain('Blocks');
  });

  it('renders empty dependencies gracefully', () => {
    const ticket = makeTicketDetail();
    const deps = makeDependencyList({ blocked_by: [], blocks: [] });
    const panel = renderDetailPanel(ticket, deps);
    const depsSection = panel.querySelector('.detail-dependencies');
    expect(depsSection).toBeTruthy();
    expect(depsSection?.textContent).toContain('None');
  });

  it('renders close button', () => {
    const ticket = makeTicketDetail();
    const panel = renderDetailPanel(ticket, null);
    const closeBtn = panel.querySelector('.detail-close');
    expect(closeBtn).toBeTruthy();
  });

  it('handles null branch_name', () => {
    const ticket = makeTicketDetail({ branch_name: null });
    const panel = renderDetailPanel(ticket, null);
    const text = panel.textContent ?? '';
    expect(text).toContain('N/A');
  });

  it('handles null current_agent', () => {
    const ticket = makeTicketDetail({ current_agent: null });
    const panel = renderDetailPanel(ticket, null);
    const text = panel.textContent ?? '';
    expect(text).toContain('None');
  });
});

describe('openDetailPanel', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="app"></div>';
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('fetches ticket detail and dependencies, then renders panel', async () => {
    const ticket = makeTicketDetail();
    const deps = makeDependencyList();

    vi.spyOn(api, 'apiGet').mockImplementation(async (path: string) => {
      if (path === '/tickets/1') {
        return { data: ticket, ok: true, status: 200 } as api.ApiResponse<unknown>;
      }
      if (path === '/tickets/1/dependencies') {
        return { data: deps, ok: true, status: 200 } as api.ApiResponse<unknown>;
      }
      return { data: null, ok: false, status: 404 } as api.ApiResponse<unknown>;
    });

    await openDetailPanel(1);

    const panel = document.querySelector('.detail-overlay');
    expect(panel).toBeTruthy();
    expect(panel?.textContent).toContain('Test Ticket');
    expect(panel?.textContent).toContain('Dependency ticket');
  });

  it('renders panel even if dependency fetch fails', async () => {
    const ticket = makeTicketDetail();

    vi.spyOn(api, 'apiGet').mockImplementation(async (path: string) => {
      if (path === '/tickets/1') {
        return { data: ticket, ok: true, status: 200 } as api.ApiResponse<unknown>;
      }
      throw new Error('Network error');
    });

    await openDetailPanel(1);

    const panel = document.querySelector('.detail-overlay');
    expect(panel).toBeTruthy();
    expect(panel?.textContent).toContain('Test Ticket');
  });

  it('does not render panel if ticket fetch fails', async () => {
    vi.spyOn(api, 'apiGet').mockRejectedValue(new Error('Network error'));

    await openDetailPanel(1);

    const panel = document.querySelector('.detail-overlay');
    expect(panel).toBeNull();
  });
});

describe('closeDetailPanel', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('removes the overlay from the DOM', () => {
    const overlay = document.createElement('div');
    overlay.className = 'detail-overlay';
    document.body.appendChild(overlay);

    closeDetailPanel();

    expect(document.querySelector('.detail-overlay')).toBeNull();
  });

  it('does nothing if no overlay exists', () => {
    expect(() => closeDetailPanel()).not.toThrow();
  });
});

describe('formatNotes', () => {
  it('returns notes HTML in order', () => {
    const notes: Note[] = [
      {
        id: 1,
        ticket_id: 1,
        author: 'bot',
        content: 'Hello',
        note_type: 'general',
        created_at: '2026-03-15T10:00:00',
      },
    ];
    const el = formatNotes(notes);
    expect(el.querySelectorAll('.detail-note').length).toBe(1);
    expect(el.textContent).toContain('Hello');
    expect(el.textContent).toContain('bot');
  });

  it('returns empty message when no notes', () => {
    const el = formatNotes([]);
    expect(el.textContent).toContain('No notes');
  });
});

describe('formatDependencies', () => {
  it('renders blocked_by and blocks', () => {
    const deps = makeDependencyList();
    const el = formatDependencies(deps);
    expect(el.textContent).toContain('Dependency ticket');
    expect(el.textContent).toContain('Blocked ticket');
  });

  it('shows None when lists are empty', () => {
    const deps = makeDependencyList({ blocked_by: [], blocks: [] });
    const el = formatDependencies(deps);
    const noneElements = el.querySelectorAll('.detail-dep-none');
    expect(noneElements.length).toBe(2);
  });
});
