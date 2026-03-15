import './style.css';
import { apiGet } from './api.js';
import { renderBoard } from './board.js';
import { createWsClient } from './ws.js';
import { setupRealtimeUpdates } from './realtime.js';
import type { Ticket } from './types.js';

document.querySelector<HTMLDivElement>('#app')!.innerHTML = `
  <header class="header">
    <h1>DevHarness</h1>
    <div class="connection-status">
      <span class="dot" id="ws-dot"></span>
      <span id="ws-label">Disconnected</span>
    </div>
  </header>
  <main class="board" id="board">
    <p style="color: var(--color-text-muted); padding: var(--space-lg);">Loading board...</p>
  </main>
`;

async function loadBoard(): Promise<void> {
  const board = document.getElementById('board');
  const dot = document.getElementById('ws-dot');
  const label = document.getElementById('ws-label');
  if (!board || !dot || !label) return;

  let tickets: Ticket[] = [];
  try {
    const response = await apiGet<Ticket[]>('/tickets');
    if (response.ok) {
      tickets = response.data;
    }
  } catch {
    // continue with empty tickets
  }

  renderBoard(board, tickets);

  const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
  const wsClient = createWsClient(wsUrl);
  setupRealtimeUpdates(wsClient, board, dot, label, tickets);
}

loadBoard();
