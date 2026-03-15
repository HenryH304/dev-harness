import type { Ticket, ColumnKey } from './types.js';
import { COLUMNS } from './types.js';

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
    agent.textContent = `Agent: ${ticket.current_agent}`;
    meta.appendChild(agent);
  }

  card.appendChild(meta);

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
