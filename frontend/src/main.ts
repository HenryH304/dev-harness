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
import type { Ticket } from './types.js';
import type { DepStatus } from './dependency-icons.js';

const appEl = document.querySelector<HTMLDivElement>('#app')!;

function renderShell(page: 'board' | 'dashboard'): void {
  appEl.innerHTML = `
    <header class="header">
      <h1>DevHarness</h1>
      <nav class="header-nav">
        <a href="#" class="nav-link${page === 'board' ? ' nav-link--active' : ''}" data-page="board">Board</a>
        <a href="#" class="nav-link${page === 'dashboard' ? ' nav-link--active' : ''}" data-page="dashboard">Dashboard</a>
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
      const target = (link as HTMLElement).dataset.page as 'board' | 'dashboard';
      navigateTo(target);
    });
  });
}

async function loadBoard(): Promise<void> {
  renderShell('board');
  const content = document.getElementById('page-content')!;

  // Add filter bar above board
  const filterBar = document.createElement('div');
  filterBar.className = 'board-filter-bar';
  filterBar.innerHTML = `
    <label class="filter-label" for="project-filter">Filter by project:</label>
    <select class="filter-select" id="project-filter">
      <option value="">All Projects</option>
    </select>
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

function navigateTo(page: 'board' | 'dashboard'): void {
  const hash = page === 'dashboard' ? '#/dashboard' : '#/';
  window.location.hash = hash;
}

function handleRoute(): void {
  const hash = window.location.hash;
  if (hash === '#/dashboard') {
    loadDashboardPage();
  } else {
    loadBoard();
  }
}

window.addEventListener('hashchange', handleRoute);
handleRoute();
