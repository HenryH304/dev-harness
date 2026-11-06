import './style.css';
import { apiGet } from './api.js';
import { renderBoard } from './board.js';
import { createWsClient } from './ws.js';
import { setupRealtimeUpdates } from './realtime.js';
import { renderDetailPanel } from './detail-panel.js';
import type { TicketDetail, DependencyList } from './detail-panel.js';
import { setupDragDrop } from './drag-drop.js';
import { loadDashboard } from './dashboard.js';
import {
  fetchUnresolvedDeps,
  applyDependencyIcons,
} from './dependency-icons.js';
import { fetchProjects, setActivePriority } from './project-management.js';
import { openAddStoryModal, openSpecReviewModal } from './add-story-modal.js';
import { mountSpecProgressPanel, openSpecHistory } from './spec-progress-panel.js';
import { openCreateProjectModal } from './create-project-modal.js';
import { fetchPrompts, renderPromptsPanel, savePrompt } from './prompts-panel.js';
import { renderSettingsPanel, saveSettings } from './settings-panel.js';
import type { SettingsData } from './settings-panel.js';
import type { Ticket } from './types.js';
import type { DepStatus } from './dependency-icons.js';

const appEl = document.querySelector<HTMLDivElement>('#app')!;

const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
const wsClient = createWsClient(wsUrl);
wsClient.connect();

type Page = 'board' | 'dashboard' | 'settings';

function applyConnectionStatus(status: string, dot: HTMLElement, label: HTMLElement): void {
  dot.className = 'dot';
  if (status === 'connected') {
    dot.classList.add('connected');
    label.textContent = 'Connected';
  } else if (status === 'reconnecting') {
    dot.classList.add('reconnecting');
    label.textContent = 'Reconnecting...';
  } else {
    label.textContent = 'Disconnected';
  }
}

function renderShell(page: Page): void {
  appEl.innerHTML = `
    <header class="header">
      <h1>DevHarness</h1>
      <nav class="header-nav">
        <a href="#" class="nav-link${page === 'board' ? ' nav-link--active' : ''}" data-page="board">Board</a>
        <a href="#" class="nav-link${page === 'dashboard' ? ' nav-link--active' : ''}" data-page="dashboard">Dashboard</a>
        <a href="#" class="nav-link${page === 'settings' ? ' nav-link--active' : ''}" data-page="settings">Settings</a>
      </nav>
      <div class="connection-status">
        <span class="dot" id="ws-dot"></span>
        <span id="ws-label">Disconnected</span>
      </div>
    </header>
    <main id="page-content">
      <p style="color: var(--color-text-muted); padding: var(--space-lg);">Loading...</p>
    </main>
  `;

  const dot = document.getElementById('ws-dot')!;
  const label = document.getElementById('ws-label')!;
  applyConnectionStatus(wsClient.getStatus(), dot, label);
  wsClient.onStatusChange((s) => applyConnectionStatus(s, dot, label));

  appEl.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const target = (link as HTMLElement).dataset.page as Page;
      navigateTo(target);
    });
  });
}

async function loadBoard(): Promise<void> {
  renderShell('board');
  const content = document.getElementById('page-content')!;

  // Clear the "Loading..." placeholder before adding real content
  content.innerHTML = '';

  // Add filter bar above board
  const filterBar = document.createElement('div');
  filterBar.innerHTML = `
    <div class="board-filter-bar">
      <div class="board-filter-left">
        <label class="filter-label" for="project-filter">Filter by project:</label>
        <select class="filter-select" id="project-filter">
          <option value="">All Projects</option>
        </select>
        <button class="dash-btn" id="set-priority-btn" style="display:none" title="Set as active priority project">★ Set Priority</button>
      </div>
      <button class="dash-btn dash-btn-secondary" id="new-project-btn">+ New Project</button>
      <button class="dash-btn" id="spec-history-btn">Spec History</button>
      <button class="dash-btn dash-btn-primary" id="add-story-btn">+ Add Story</button>
      <button class="dash-btn" id="dispatch-toggle-btn" title="Toggle agent dispatch">...</button>
    </div>
  `;
  content.appendChild(filterBar);

  const specPanelContainer = document.createElement('div');
  specPanelContainer.hidden = true;
  content.appendChild(specPanelContainer);

  const boardContainer = document.createElement('div');
  boardContainer.className = 'board';
  content.appendChild(boardContainer);

  const dot = document.getElementById('ws-dot')!;
  const label = document.getElementById('ws-label')!;

  let allTickets: Ticket[] = [];
  let depStatus: DepStatus = {};
  let activeProject = '';
  let selectedFilter = '';
  let panel = mountSpecProgressPanel(specPanelContainer, {
    onReview: (specId) => openSpecReviewModal({
      specId,
      projects: [],
      onClose: () => void panel.refresh(),
    }),
    onTasksCreated: () => loadBoard(),
  });

  // Dispatch toggle button
  let dispatchEnabled = true;
  const dispatchBtn = filterBar.querySelector<HTMLButtonElement>('#dispatch-toggle-btn')!;

  function applyDispatchState(enabled: boolean): void {
    dispatchEnabled = enabled;
    if (enabled) {
      dispatchBtn.textContent = '⏸ Pause Agents';
      dispatchBtn.className = 'dash-btn dash-btn-warning';
    } else {
      dispatchBtn.textContent = '▶ Resume Agents';
      dispatchBtn.className = 'dash-btn dash-btn-success';
    }
  }

  dispatchBtn.addEventListener('click', async () => {
    dispatchBtn.disabled = true;
    const newValue = dispatchEnabled ? 'false' : 'true';
    try {
      const resp = await fetch('/api/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { agent_dispatch_enabled: newValue } }),
      });
      if (resp.ok) {
        applyDispatchState(newValue === 'true');
      }
    } catch {
      // silent — button re-enables regardless
    } finally {
      dispatchBtn.disabled = false;
    }
  });

  try {
    const [ticketResp, deps, projectData, settingsResp] = await Promise.all([
      apiGet<Ticket[]>('/tickets'),
      fetchUnresolvedDeps(),
      fetchProjects(),
      apiGet<{ settings: SettingsData }>('/settings'),
    ]);
    if (ticketResp.ok) {
      allTickets = ticketResp.data;
    }
    depStatus = deps;
    activeProject = projectData.active_priority_project;

    // Initialise dispatch toggle from persisted setting
    if (settingsResp.ok) {
      const raw = settingsResp.data.settings['agent_dispatch_enabled'];
      applyDispatchState(raw !== 'false');
    } else {
      applyDispatchState(true);
    }

    // Populate filter dropdown
    const select = filterBar.querySelector<HTMLSelectElement>('#project-filter')!;
    for (const p of projectData.projects) {
      const opt = document.createElement('option');
      opt.value = p.name;
      opt.textContent = `${p.name} (${p.ticket_count})`;
      if (p.name === activeProject) {
        opt.textContent += ' ★';
      }
      select.appendChild(opt);
    }

    // Default filter to priority project if one is set and no filter already chosen
    if (activeProject && !selectedFilter) {
      selectedFilter = activeProject;
      select.value = activeProject;
    }

    // Wire "New Project" button
    document.querySelector<HTMLButtonElement>('#new-project-btn')!.addEventListener('click', () => {
      openCreateProjectModal({ onDone: () => loadBoard() });
    });

    document.querySelector<HTMLButtonElement>('#spec-history-btn')!.addEventListener('click', () => {
      openSpecHistory();
    });

    const projectNames = projectData.projects.map((p) => p.name);

    // Re-mount panel now that we have project names
    panel.stop();
    panel = mountSpecProgressPanel(specPanelContainer, {
      onReview: (specId) => openSpecReviewModal({
        specId,
        projects: projectNames,
        onClose: () => void panel.refresh(),
      }),
      onTasksCreated: () => loadBoard(),
    });

    // Wire "Add Story" button
    document.querySelector<HTMLButtonElement>('#add-story-btn')!.addEventListener('click', () => {
      openAddStoryModal({
        defaultProject: selectedFilter,
        projects: projectNames,
        onSpecSubmitted: () => void panel.refresh(),
      });
    });
  } catch {
    // continue with empty tickets
    applyDispatchState(true);
  }

  function getFilteredTickets(): Ticket[] {
    if (!selectedFilter) return allTickets;
    return allTickets.filter((t) => t.project === selectedFilter);
  }

  function rerenderBoard(): void {
    const filtered = getFilteredTickets();
    renderBoard(boardContainer, filtered);
    applyDependencyIcons(boardContainer, depStatus);
    setupDragDrop(boardContainer, filtered, refreshBoard);
  }

  async function refreshBoard(): Promise<void> {
    const [ticketResp, freshDeps] = await Promise.all([
      apiGet<Ticket[]>('/tickets'),
      fetchUnresolvedDeps(),
    ]);
    if (ticketResp.ok) allTickets = ticketResp.data;
    depStatus = freshDeps;
    rerenderBoard();
  }

  rerenderBoard();

  // Filter change handler + Set Priority button
  const select = filterBar.querySelector<HTMLSelectElement>('#project-filter')!;
  const setPriorityBtn = filterBar.querySelector<HTMLButtonElement>('#set-priority-btn')!;

  function updateSetPriorityBtn(): void {
    if (!selectedFilter || selectedFilter === activeProject) {
      setPriorityBtn.style.display = 'none';
    } else {
      setPriorityBtn.style.display = '';
      setPriorityBtn.textContent = `★ Set Priority`;
    }
  }
  updateSetPriorityBtn();

  select.addEventListener('change', () => {
    selectedFilter = select.value;
    rerenderBoard();
    updateSetPriorityBtn();
  });

  setPriorityBtn.addEventListener('click', async () => {
    if (!selectedFilter) return;
    setPriorityBtn.disabled = true;
    const ok = await setActivePriority(selectedFilter);
    if (ok) {
      activeProject = selectedFilter;
      // Update the ★ indicator in the dropdown
      select.querySelectorAll('option').forEach((opt) => {
        opt.textContent = opt.textContent?.replace(' ★', '') ?? '';
        if (opt.value === activeProject) opt.textContent += ' ★';
      });
    }
    setPriorityBtn.disabled = false;
    updateSetPriorityBtn();
  });

  setupRealtimeUpdates(wsClient, boardContainer, dot, label, allTickets, async (b, _t) => {
    allTickets = _t;
    const freshDeps = await fetchUnresolvedDeps();
    depStatus = freshDeps;
    if (selectedFilter) {
      const filtered = _t.filter((t) => t.project === selectedFilter);
      renderBoard(b, filtered);
      applyDependencyIcons(b, freshDeps);
      setupDragDrop(b, filtered, refreshBoard);
    } else {
      applyDependencyIcons(b, freshDeps);
      setupDragDrop(b, _t, refreshBoard);
    }
  }, () => void panel.refresh());
}

async function loadDashboardPage(): Promise<void> {
  renderShell('dashboard');
  const content = document.getElementById('page-content')!;
  content.classList.add('dashboard-page');
  await loadDashboard(content);
}

async function loadSettingsPage(): Promise<void> {
  renderShell('settings');
  const content = document.getElementById('page-content')!;
  content.classList.add('settings-page');
  content.innerHTML = `
    <div class="settings-page-grid">
      <section class="dash-section dash-section--full" id="settings-prompts">
        <h2 class="dash-section-title">Agent Prompts</h2>
        <div class="dash-section-body"><p class="dash-loading">Loading...</p></div>
      </section>
      <section class="dash-section dash-section--full" id="settings-app">
        <h2 class="dash-section-title">App Settings</h2>
        <div class="dash-section-body"><p class="dash-loading">Loading...</p></div>
      </section>
    </div>
  `;

  const promptsBody = content.querySelector<HTMLElement>('#settings-prompts .dash-section-body')!;
  try {
    const prompts = await fetchPrompts();
    if (prompts.length > 0) {
      renderPromptsPanel(promptsBody, prompts, savePrompt);
    } else {
      promptsBody.innerHTML = '<p class="dash-empty">No prompts found</p>';
    }
  } catch {
    promptsBody.innerHTML = '<p class="dash-empty">Failed to load prompts</p>';
  }

  const appSettingsBody = content.querySelector<HTMLElement>('#settings-app .dash-section-body')!;
  try {
    const resp = await apiGet<{ settings: SettingsData }>('/settings');
    if (resp.ok) {
      renderSettingsPanel(appSettingsBody, resp.data.settings, async (updated) => {
        return saveSettings(updated);
      });
    }
  } catch {
    appSettingsBody.innerHTML = '<p class="dash-empty">Failed to load settings</p>';
  }
}

function navigateTo(page: Page): void {
  if (page === 'dashboard') window.location.hash = '#/dashboard';
  else if (page === 'settings') window.location.hash = '#/settings';
  else window.location.hash = '#/';
}

async function loadTicketPage(ticketId: number): Promise<void> {
  appEl.innerHTML = `
    <div class="ticket-page">
      <p style="color: var(--color-text-muted); padding: var(--space-lg);">Loading ticket #${ticketId}…</p>
    </div>
  `;

  const [ticketResp, depsResp] = await Promise.all([
    apiGet<TicketDetail>(`/tickets/${ticketId}`),
    apiGet<DependencyList>(`/tickets/${ticketId}/dependencies`),
  ]);

  if (!ticketResp.ok) {
    appEl.innerHTML = `<p style="color:var(--color-text-muted);padding:var(--space-lg);">Ticket #${ticketId} not found.</p>`;
    return;
  }

  const panel = renderDetailPanel(ticketResp.data, depsResp.ok ? depsResp.data : null);
  panel.classList.add('ticket-page-panel');
  appEl.innerHTML = '';
  appEl.appendChild(panel);
}

function handleRoute(): void {
  const hash = window.location.hash;
  if (hash === '#/dashboard') loadDashboardPage();
  else if (hash === '#/settings') loadSettingsPage();
  else {
    const ticketMatch = hash.match(/^#\/ticket\/(\d+)$/);
    if (ticketMatch) loadTicketPage(Number(ticketMatch[1]));
    else loadBoard();
  }
}

window.addEventListener('hashchange', handleRoute);
handleRoute();
