import type { Ticket, ColumnKey } from './types.js';
import { COLUMNS } from './types.js';
import { openDetailPanel } from './detail-panel.js';

export function groupTicketsByState(
  tickets: Ticket[]
): Record<ColumnKey, Ticket[]> {
  const grouped = Object.fromEntries(
    COLUMNS.map((c) => [c.key, [] as Ticket[]])
  ) as Record<ColumnKey, Ticket[]>;

  for (const ticket of tickets) {
    const key = ticket.state as ColumnKey;
    if (key in grouped) {
      grouped[key].push(ticket);
    }
  }

  return grouped;
}

function getPriorityClass(priority: number): string {
  if (priority <= 2) return 'high';
  if (priority <= 4) return 'medium';
  return 'low';
}

function timeAgo(iso: string): string {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function renderCard(ticket: Ticket): HTMLElement {
  const card = document.createElement('div');
  card.className = 'card';
  card.setAttribute('data-ticket-id', String(ticket.id));

  const title = document.createElement('div');
  title.className = 'card-title';
  title.textContent = ticket.title;
  card.appendChild(title);

  const meta = document.createElement('div');
  meta.className = 'card-meta';

  const priorityBadge = document.createElement('span');
  priorityBadge.className = `priority-badge ${getPriorityClass(ticket.priority)}`;
  priorityBadge.textContent = `P${ticket.priority}`;
  meta.appendChild(priorityBadge);

  const project = document.createElement('span');
  project.textContent = ticket.project;
  meta.appendChild(project);

  if (ticket.current_agent) {
    const agent = document.createElement('span');
    agent.className = 'card-agent';
    // Format agent ID: "developer-c9ffd296" → "🤖 Developer"
    const agentType = ticket.current_agent.split('-')[0];
    const agentLabel = agentType.charAt(0).toUpperCase() + agentType.slice(1);
    agent.textContent = `🤖 ${agentLabel}`;
    meta.appendChild(agent);
  }

  const age = document.createElement('span');
  age.className = 'card-age';
  age.title = new Date(ticket.updated_at).toLocaleString();
  age.textContent = timeAgo(ticket.updated_at);
  meta.appendChild(age);

  card.appendChild(meta);

  card.addEventListener('click', () => {
    openDetailPanel(ticket.id);
  });

  return card;
}

export function renderBoard(container: HTMLElement, tickets: Ticket[]): void {
  container.innerHTML = '';
  const grouped = groupTicketsByState(tickets);

  for (const col of COLUMNS) {
    const colEl = document.createElement('div');
    colEl.className = 'column';
    if (col.key === 'blocked') {
      colEl.classList.add('column--blocked');
    }
    colEl.setAttribute('data-column', col.key);

    const header = document.createElement('div');
    header.className = 'column-header';

    const label = document.createElement('span');
    label.className = 'column-label';
    label.textContent = col.label;
    header.appendChild(label);

    const badge = document.createElement('span');
    badge.className = 'badge';
    badge.textContent = String(grouped[col.key].length);
    header.appendChild(badge);

    colEl.appendChild(header);

    const body = document.createElement('div');
    body.className = 'column-body';

    for (const ticket of grouped[col.key]) {
      body.appendChild(renderCard(ticket));
    }

    colEl.appendChild(body);
    container.appendChild(colEl);
  }
}
