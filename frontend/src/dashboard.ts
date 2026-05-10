/**
 * Dashboard module — agent monitor, metrics, and manual controls.
 */

import { apiGet, apiPost } from './api.js';
import {
  fetchProjects,
  importProject,
  renderProjectManagement,
  setActivePriority,
} from './project-management.js';
import {
  fetchFeatureRequests,
  renderFeaturePanel,
  submitFeature,
} from './feature-panel.js';

// --- Types ---

export interface ActiveAgent {
  id: number;
  agent_type: string;
  status: string;
  current_ticket_id: number | null;
  ticket_title: string | null;
  started_at: string | null;
  elapsed_seconds: number | null;
}

export interface DashboardMetrics {
  column_counts: Record<string, number>;
  total_tickets: number;
}

export interface TimeoutAnalytics {
  developer_timeouts: number;
  reviewer_timeouts: number;
  tester_timeouts: number;
  merger_timeouts: number;
}

export interface BlockedTicket {
  id: number;
  title: string;
  project: string;
  state: string;
  review_rejection_count: number;
  agent_attempts: number;
  last_failure_note: string | null;
}

// --- Column labels ---

const COLUMN_LABELS: Record<string, string> = {
  to_do: 'To Do',
  in_progress: 'In Progress',
  ready_for_review: 'Ready for Review',
  in_review: 'In Review',
  ready_for_test: 'Ready for Test',
  in_test: 'In Test',
  ready_to_merge: 'Ready to Merge',
  done: 'Done',
  blocked: 'Blocked',
};

// --- Helpers ---

export function formatElapsed(seconds: number | null): string {
  if (seconds === null) return '\u2014';
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

// --- Render functions ---

export function renderDashboard(container: HTMLElement): void {
  container.innerHTML = `
    <div class="dash-grid">
      <section class="dash-section" id="dash-agents">
        <h2 class="dash-section-title">Active Agents</h2>
        <div class="dash-section-body"><p class="dash-loading">Loading...</p></div>
      </section>
      <section class="dash-section" id="dash-metrics">
        <h2 class="dash-section-title">Workflow Metrics</h2>
        <div class="dash-section-body"><p class="dash-loading">Loading...</p></div>
      </section>
      <section class="dash-section" id="dash-timeouts">
        <h2 class="dash-section-title">Timeout Analytics</h2>
        <div class="dash-section-body"><p class="dash-loading">Loading...</p></div>
      </section>
      <section class="dash-section" id="dash-blocked">
        <h2 class="dash-section-title">Blocked Tickets</h2>
        <div class="dash-section-body"><p class="dash-loading">Loading...</p></div>
      </section>
      <section class="dash-section" id="dash-controls">
        <h2 class="dash-section-title">Controls</h2>
        <div class="dash-section-body"></div>
      </section>
      <section class="dash-section dash-section--full" id="dash-projects">
        <h2 class="dash-section-title">Project Management</h2>
        <div class="dash-section-body"><p class="dash-loading">Loading...</p></div>
      </section>
      <section class="dash-section dash-section--full" id="dash-features">
        <h2 class="dash-section-title">Feature Generation</h2>
        <div class="dash-section-body"><p class="dash-loading">Loading...</p></div>
      </section>
    </div>
  `;
}

export function renderAgentsTable(
  container: HTMLElement,
  agents: ActiveAgent[],
): void {
  if (agents.length === 0) {
    container.innerHTML = '<p class="dash-empty">No active agents</p>';
    return;
  }

  const rows = agents
    .map(
      (a) => `
    <tr>
      <td>${a.agent_type}</td>
      <td>#${a.current_ticket_id ?? '—'}</td>
      <td>${a.ticket_title ?? '—'}</td>
      <td>${formatElapsed(a.elapsed_seconds)}</td>
    </tr>`,
    )
    .join('');

  container.innerHTML = `
    <table class="dash-table">
      <thead><tr><th>Type</th><th>Ticket</th><th>Title</th><th>Elapsed</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

export function renderMetrics(
  container: HTMLElement,
  metrics: DashboardMetrics,
): void {
  const items = Object.entries(metrics.column_counts)
    .map(
      ([key, count]) => `
    <div class="dash-metric-item">
      <span class="dash-metric-label">${COLUMN_LABELS[key] ?? key}</span>
      <span class="dash-metric-value">${count}</span>
    </div>`,
    )
    .join('');

  container.innerHTML = `
    <div class="dash-metric-total">
      <span>Total Tickets</span>
      <span class="dash-metric-value-lg">${metrics.total_tickets}</span>
    </div>
    <div class="dash-metric-grid">${items}</div>
  `;
}

export function renderTimeoutAnalytics(
  container: HTMLElement,
  data: TimeoutAnalytics,
): void {
  const items = [
    { label: 'Developer', value: data.developer_timeouts },
    { label: 'Reviewer', value: data.reviewer_timeouts },
    { label: 'Tester', value: data.tester_timeouts },
    { label: 'Merger', value: data.merger_timeouts },
  ];

  container.innerHTML = `
    <div class="dash-timeout-grid">
      ${items
        .map(
          (i) => `
        <div class="dash-timeout-item">
          <span class="dash-timeout-label">${i.label}</span>
          <span class="dash-timeout-value${i.value > 0 ? ' dash-timeout-warn' : ''}">${i.value}</span>
        </div>`,
        )
        .join('')}
    </div>
  `;
}

export function renderBlockedTickets(
  container: HTMLElement,
  tickets: BlockedTicket[],
  onForceUnlock: (ticketId: number) => void,
): void {
  if (tickets.length === 0) {
    container.innerHTML = '<p class="dash-empty">No blocked tickets</p>';
    return;
  }

  container.innerHTML = tickets
    .map(
      (t) => `
    <div class="dash-blocked-card" data-ticket-id="${t.id}">
      <div class="dash-blocked-header">
        <strong>#${t.id} ${t.title}</strong>
        <span class="dash-blocked-project">${t.project}</span>
      </div>
      <div class="dash-blocked-meta">
        <span>Rejections: <strong>${t.review_rejection_count}</strong></span>
        <span>Attempts: <strong>${t.agent_attempts}</strong></span>
      </div>
      ${t.last_failure_note ? `<p class="dash-blocked-note">${t.last_failure_note}</p>` : ''}
      <button class="dash-btn dash-btn-danger force-unlock-btn">Force Unlock</button>
    </div>`,
    )
    .join('');

  container.querySelectorAll('.force-unlock-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.dash-blocked-card') as HTMLElement;
      const ticketId = parseInt(card.dataset.ticketId ?? '0', 10);
      onForceUnlock(ticketId);
    });
  });
}

function renderControls(
  container: HTMLElement,
  paused: boolean,
  onToggle: (pause: boolean) => void,
): void {
  container.innerHTML = `
    <div class="dash-controls">
      <div class="dash-control-item">
        <span>Agent Processing</span>
        <button class="dash-btn ${paused ? 'dash-btn-success' : 'dash-btn-danger'}" id="toggle-agents-btn">
          ${paused ? 'Resume All Agents' : 'Pause All Agents'}
        </button>
      </div>
    </div>
  `;

  document.getElementById('toggle-agents-btn')?.addEventListener('click', () => {
    onToggle(!paused);
  });
}

// --- Load dashboard ---

export async function loadDashboard(container: HTMLElement): Promise<void> {
  renderDashboard(container);

  let agentsPaused = false;

  const agentsSection = document.querySelector('#dash-agents .dash-section-body') as HTMLElement;
  const metricsSection = document.querySelector('#dash-metrics .dash-section-body') as HTMLElement;
  const timeoutsSection = document.querySelector('#dash-timeouts .dash-section-body') as HTMLElement;
  const blockedSection = document.querySelector('#dash-blocked .dash-section-body') as HTMLElement;
  const controlsSection = document.querySelector('#dash-controls .dash-section-body') as HTMLElement;

  async function handleForceUnlock(ticketId: number): Promise<void> {
    try {
      await apiPost(`/dashboard/force-unlock/${ticketId}`, {});
      await refreshAll();
    } catch {
      // silent
    }
  }

  async function handleToggle(pause: boolean): Promise<void> {
    try {
      const resp = await apiPost<{ agents_paused: boolean }>('/dashboard/toggle-agents', { paused: pause });
      if (resp.ok) {
        agentsPaused = resp.data.agents_paused;
      }
    } catch {
      // silent
    }
    renderControls(controlsSection, agentsPaused, handleToggle);
  }

  async function refreshAll(): Promise<void> {
    try {
      const [agentsResp, metricsResp, timeoutsResp, blockedResp] = await Promise.all([
        apiGet<{ agents: ActiveAgent[] }>('/dashboard/agents'),
        apiGet<DashboardMetrics>('/dashboard/metrics'),
        apiGet<TimeoutAnalytics>('/dashboard/timeouts'),
        apiGet<{ blocked_tickets: BlockedTicket[] }>('/dashboard/blocked'),
      ]);

      if (agentsResp.ok) renderAgentsTable(agentsSection, agentsResp.data.agents);
      if (metricsResp.ok) renderMetrics(metricsSection, metricsResp.data);
      if (timeoutsResp.ok) renderTimeoutAnalytics(timeoutsSection, timeoutsResp.data);
      if (blockedResp.ok) renderBlockedTickets(blockedSection, blockedResp.data.blocked_tickets, handleForceUnlock);
    } catch {
      // silent — sections keep their loading state
    }
  }

  renderControls(controlsSection, agentsPaused, handleToggle);
  await refreshAll();

  // Load project management
  const projectsSection = document.querySelector('#dash-projects .dash-section-body') as HTMLElement;
  async function loadProjectsPanel(): Promise<void> {
    try {
      const data = await fetchProjects();
      renderProjectManagement(
        projectsSection,
        data.projects,
        data.active_priority_project,
        async (name, path, repoPath, createIfMissing) => {
          const ok = await importProject(name, path, repoPath, createIfMissing);
          if (ok) await loadProjectsPanel();
          return ok;
        },
        async (name) => {
          const ok = await setActivePriority(name);
          if (ok) await loadProjectsPanel();
          return ok;
        },
      );
    } catch {
      projectsSection.innerHTML = '<p class="dash-empty">Failed to load projects</p>';
    }
  }
  await loadProjectsPanel();

  // Load feature generation panel
  const featuresSection = document.querySelector('#dash-features .dash-section-body') as HTMLElement;
  try {
    const [featureRequests, projectData] = await Promise.all([
      fetchFeatureRequests(),
      fetchProjects().catch(() => ({ projects: [], active_priority_project: '' })),
    ]);
    const projectNames = projectData.projects.map((p) => p.name);
    renderFeaturePanel(featuresSection, featureRequests, projectNames, submitFeature);
  } catch {
    featuresSection.innerHTML = '<p class="dash-empty">Failed to load feature requests</p>';
  }

}
