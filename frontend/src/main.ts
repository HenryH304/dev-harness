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
  content.classList.add('board');

  const dot = document.getElementById('ws-dot')!;
  const label = document.getElementById('ws-label')!;

  let tickets: Ticket[] = [];
  let depStatus: DepStatus = {};
  try {
    const [ticketResp, deps] = await Promise.all([
      apiGet<Ticket[]>('/tickets'),
      fetchUnresolvedDeps(),
    ]);
    if (ticketResp.ok) {
      tickets = ticketResp.data;
    }
    depStatus = deps;
  } catch {
    // continue with empty tickets
  }

  renderBoard(content, tickets);
  applyDependencyIcons(content, depStatus);
  setupDragDrop(content, tickets);

  const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
  const wsClient = createWsClient(wsUrl);
  setupRealtimeUpdates(wsClient, content, dot, label, tickets, async (b, _t) => {
    const freshDeps = await fetchUnresolvedDeps();
    applyDependencyIcons(b, freshDeps);
    setupDragDrop(b, _t);
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
