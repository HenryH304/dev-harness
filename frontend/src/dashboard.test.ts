// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  renderDashboard,
  renderAgentsTable,
  renderMetrics,
  renderTimeoutAnalytics,
  renderBlockedTickets,
  formatElapsed,
} from './dashboard.js';
import type {
  ActiveAgent,
  DashboardMetrics,
  TimeoutAnalytics,
  BlockedTicket,
} from './dashboard.js';

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// --- formatElapsed ---

describe('formatElapsed', () => {
  it('formats seconds', () => {
    expect(formatElapsed(45)).toBe('45s');
  });

  it('formats minutes and seconds', () => {
    expect(formatElapsed(125)).toBe('2m 5s');
  });

  it('formats hours and minutes', () => {
    expect(formatElapsed(3661)).toBe('1h 1m');
  });

  it('handles null', () => {
    expect(formatElapsed(null)).toBe('—');
  });
});

// --- renderAgentsTable ---

describe('renderAgentsTable', () => {
  it('renders empty state', () => {
    const el = document.createElement('div');
    const agents: ActiveAgent[] = [];
    renderAgentsTable(el, agents);
    expect(el.querySelector('.dash-empty')).not.toBeNull();
    expect(el.textContent).toContain('No active agents');
  });

  it('renders agent rows', () => {
    const el = document.createElement('div');
    const agents: ActiveAgent[] = [
      {
        id: 1,
        agent_type: 'developer',
        status: 'busy',
        current_ticket_id: 42,
        ticket_title: 'Build feature',
        started_at: '2026-03-16T10:00:00',
        elapsed_seconds: 300,
      },
    ];
    renderAgentsTable(el, agents);
    expect(el.querySelector('table')).not.toBeNull();
    expect(el.textContent).toContain('developer');
    expect(el.textContent).toContain('Build feature');
    expect(el.textContent).toContain('#42');
    expect(el.textContent).toContain('5m 0s');
  });
});

// --- renderMetrics ---

describe('renderMetrics', () => {
  it('renders column counts', () => {
    const el = document.createElement('div');
    const metrics: DashboardMetrics = {
      column_counts: {
        to_do: 5,
        in_progress: 2,
        ready_for_review: 1,
        in_review: 0,
        ready_for_test: 0,
        in_test: 1,
        ready_to_merge: 0,
        done: 3,
        blocked: 1,
      },
      total_tickets: 13,
    };
    renderMetrics(el, metrics);
    expect(el.textContent).toContain('13');
    expect(el.textContent).toContain('To Do');
    expect(el.textContent).toContain('5');
  });

  it('renders zero state', () => {
    const el = document.createElement('div');
    const metrics: DashboardMetrics = {
      column_counts: {
        to_do: 0,
        in_progress: 0,
        ready_for_review: 0,
        in_review: 0,
        ready_for_test: 0,
        in_test: 0,
        ready_to_merge: 0,
        done: 0,
        blocked: 0,
      },
      total_tickets: 0,
    };
    renderMetrics(el, metrics);
    expect(el.textContent).toContain('0');
  });
});

// --- renderTimeoutAnalytics ---

describe('renderTimeoutAnalytics', () => {
  it('renders timeout counts', () => {
    const el = document.createElement('div');
    const data: TimeoutAnalytics = {
      developer_timeouts: 5,
      reviewer_timeouts: 2,
      tester_timeouts: 1,
      merger_timeouts: 0,
    };
    renderTimeoutAnalytics(el, data);
    expect(el.textContent).toContain('Developer');
    expect(el.textContent).toContain('5');
    expect(el.textContent).toContain('Merger');
    expect(el.textContent).toContain('0');
  });
});

// --- renderBlockedTickets ---

describe('renderBlockedTickets', () => {
  it('renders empty state', () => {
    const el = document.createElement('div');
    renderBlockedTickets(el, [], vi.fn());
    expect(el.textContent).toContain('No blocked tickets');
  });

  it('renders blocked tickets with force unlock button', () => {
    const el = document.createElement('div');
    const tickets: BlockedTicket[] = [
      {
        id: 7,
        title: 'Broken feature',
        project: 'myproj',
        state: 'blocked',
        review_rejection_count: 3,
        agent_attempts: 5,
        last_failure_note: 'Tests failed',
      },
    ];
    const onUnlock = vi.fn();
    renderBlockedTickets(el, tickets, onUnlock);
    expect(el.textContent).toContain('Broken feature');
    expect(el.textContent).toContain('3');
    const btn = el.querySelector('button');
    expect(btn).not.toBeNull();
    btn?.click();
    expect(onUnlock).toHaveBeenCalledWith(7);
  });
});

// --- renderDashboard ---

describe('renderDashboard', () => {
  it('renders dashboard skeleton with sections', () => {
    const el = document.createElement('div');
    renderDashboard(el);
    expect(el.querySelector('#dash-agents')).not.toBeNull();
    expect(el.querySelector('#dash-metrics')).not.toBeNull();
    expect(el.querySelector('#dash-timeouts')).not.toBeNull();
    expect(el.querySelector('#dash-blocked')).not.toBeNull();
    expect(el.querySelector('#dash-controls')).not.toBeNull();
    expect(el.querySelector('#dash-settings')).not.toBeNull();
    expect(el.textContent).toContain('Active Agents');
    expect(el.textContent).toContain('Workflow Metrics');
    expect(el.textContent).toContain('Timeout Analytics');
    expect(el.textContent).toContain('Blocked Tickets');
    expect(el.textContent).toContain('Controls');
    expect(el.textContent).toContain('Settings');
  });
});
