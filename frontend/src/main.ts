import './style.css';
import { apiGet } from './api.js';
import { renderBoard } from './board.js';
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
  if (!board) return;

  try {
    const response = await apiGet<Ticket[]>('/tickets');
    if (response.ok) {
      renderBoard(board, response.data);
    } else {
      renderBoard(board, []);
    }
  } catch {
    renderBoard(board, []);
  }
}

loadBoard();
