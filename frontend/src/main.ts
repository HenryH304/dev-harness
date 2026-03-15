import './style.css';

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
