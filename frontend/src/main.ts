import './style.css';
import { apiGet } from './api.js';
import { renderBoard } from './board.js';
import { createWsClient } from './ws.js';
import { setupRealtimeUpdates } from './realtime.js';
import { setupDragDrop } from './drag-drop.js';
import { loadDashboard } from './dashboard.js';
import {
  fetchUnresolvedDeps,
  applyDependencyIcons,
} from './dependency-icons.js';
import { fetchProjects } from './project-management.js';
import { openAddStoryModal } from './add-story-modal.js';
import { fetchPrompts, renderPromptsPanel, savePrompt } from './prompts-panel.js';
import { renderSettingsPanel, saveSettings } from './settings-panel.js';
import type { SettingsData } from './settings-panel.js';
import type { Ticket } from './types.js';
import type { DepStatus } from './dependency-icons.js';

const appEl = document.querySelector<HTMLDivElement>('#app')!;

type Page = 'board' | 'dashboard' | 'settings';

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
      </div>
      <button class="dash-btn dash-btn-primary" id="add-story-btn">+ Add Story</button>
    </div>
  `;
  content.appendChild(filterBar);

  const boardContainer = document.createElement('div');
  boardContainer.className = 'board';
  content.appendChild(boardContainer);

  const dot = document.getElementById('ws-dot')!;
  const label = document.getElementById('ws-label')!;

  let allTickets: Ticket[] = [];
  let depStatus: DepStatus = {};
  let activeProject = '';
  let selectedFilter = '';

  try {
    const [ticketResp, deps, projectData] = await Promise.all([
      apiGet<Ticket[]>('/tickets'),
      fetchUnresolvedDeps(),
      fetchProjects(),
    ]);
    if (ticketResp.ok) {
      allTickets = ticketResp.data;
    }
    depStatus = deps;
    activeProject = projectData.active_priority_project;

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

    // Wire "Add Story" button
    document.querySelector<HTMLButtonElement>('#add-story-btn')!.addEventListener('click', () => {
      openAddStoryModal({
        defaultProject: selectedFilter,
        projects: projectData.projects.map((p) => p.name),
        onDone: () => loadBoard(),
      });
    });
  } catch {
    // continue with empty tickets
  }

  function getFilteredTickets(): Ticket[] {
    if (!selectedFilter) return allTickets;
    return allTickets.filter((t) => t.project === selectedFilter);
  }

  function rerenderBoard(): void {
    const filtered = getFilteredTickets();
    renderBoard(boardContainer, filtered);
    applyDependencyIcons(boardContainer, depStatus);
    setupDragDrop(boardContainer, filtered);
  }

  rerenderBoard();

  // Filter change handler
  const select = filterBar.querySelector<HTMLSelectElement>('#project-filter')!;
  select.addEventListener('change', () => {
    selectedFilter = select.value;
    rerenderBoard();
  });

  const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
  const wsClient = createWsClient(wsUrl);
  setupRealtimeUpdates(wsClient, boardContainer, dot, label, allTickets, async (b, _t) => {
    allTickets = _t;
    const freshDeps = await fetchUnresolvedDeps();
    depStatus = freshDeps;
    if (selectedFilter) {
      const filtered = _t.filter((t) => t.project === selectedFilter);
      renderBoard(b, filtered);
      applyDependencyIcons(b, freshDeps);
      setupDragDrop(b, filtered);
    } else {
      applyDependencyIcons(b, freshDeps);
      setupDragDrop(b, _t);
    }
  });
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

function handleRoute(): void {
  const hash = window.location.hash;
  if (hash === '#/dashboard') loadDashboardPage();
  else if (hash === '#/settings') loadSettingsPage();
  else loadBoard();
}

window.addEventListener('hashchange', handleRoute);
handleRoute();
