import { apiGet, apiPatch } from './api.js';
import { parseUtc } from './types.js';

export interface Note {
  id: number;
  ticket_id: number;
  author: string;
  content: string;
  note_type: string;
  created_at: string;
}

export interface TicketDetail {
  id: number;
  project: string;
  title: string;
  description: string;
  acceptance_criteria: unknown[];
  priority: number;
  state: string;
  previous_state: string | null;
  branch_name: string | null;
  worktree_path: string | null;
  current_agent: string | null;
  assigned_at: string | null;
  agent_attempts: number;
  developer_timeouts: number;
  reviewer_timeouts: number;
  tester_timeouts: number;
  merger_timeouts: number;
  review_rejection_count: number;
  created_at: string;
  updated_at: string;
  notes: Note[];
}

export interface TicketSummary {
  id: number;
  title: string;
  state: string;
}

export interface DependencyList {
  blocked_by: TicketSummary[];
  blocks: TicketSummary[];
}

export function formatNotes(notes: Note[]): HTMLElement {
  const container = document.createElement('div');
  container.className = 'detail-notes';

  if (notes.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'detail-notes-empty';
    empty.textContent = 'No notes';
    container.appendChild(empty);
    return container;
  }

  for (const note of notes) {
    const noteEl = document.createElement('div');
    noteEl.className = 'detail-note';

    const header = document.createElement('div');
    header.className = 'detail-note-header';
    header.textContent = `${note.author} (${note.note_type}) — ${note.created_at}`;
    noteEl.appendChild(header);

    const content = document.createElement('div');
    content.className = 'detail-note-content';
    content.textContent = note.content;
    noteEl.appendChild(content);

    container.appendChild(noteEl);
  }

  return container;
}

export function formatDependencies(deps: DependencyList): HTMLElement {
  const container = document.createElement('div');
  container.className = 'detail-dependencies';

  const blockedByHeader = document.createElement('h4');
  blockedByHeader.textContent = 'Blocked By';
  container.appendChild(blockedByHeader);

  if (deps.blocked_by.length === 0) {
    const none = document.createElement('span');
    none.className = 'detail-dep-none';
    none.textContent = 'None';
    container.appendChild(none);
  } else {
    const list = document.createElement('ul');
    for (const dep of deps.blocked_by) {
      const li = document.createElement('li');
      li.textContent = `#${dep.id} ${dep.title} (${dep.state})`;
      list.appendChild(li);
    }
    container.appendChild(list);
  }

  const blocksHeader = document.createElement('h4');
  blocksHeader.textContent = 'Blocks';
  container.appendChild(blocksHeader);

  if (deps.blocks.length === 0) {
    const none = document.createElement('span');
    none.className = 'detail-dep-none';
    none.textContent = 'None';
    container.appendChild(none);
  } else {
    const list = document.createElement('ul');
    for (const dep of deps.blocks) {
      const li = document.createElement('li');
      li.textContent = `#${dep.id} ${dep.title} (${dep.state})`;
      list.appendChild(li);
    }
    container.appendChild(list);
  }

  return container;
}

export function renderDetailPanel(
  ticket: TicketDetail,
  deps: DependencyList | null
): HTMLElement {
  const panel = document.createElement('div');
  panel.className = 'detail-panel';

  // Close button
  const closeBtn = document.createElement('button');
  closeBtn.className = 'detail-close';
  closeBtn.textContent = '\u00d7';
  closeBtn.addEventListener('click', () => closeDetailPanel());
  panel.appendChild(closeBtn);

  // Ticket ID link \u2014 opens full-window view in new tab
  const idLink = document.createElement('a');
  idLink.className = 'detail-id-link';
  idLink.textContent = `#${ticket.id}`;
  idLink.href = `#/ticket/${ticket.id}`;
  idLink.target = '_blank';
  idLink.rel = 'noopener';
  panel.appendChild(idLink);

  // Title
  const title = document.createElement('h2');
  title.className = 'detail-title';
  title.textContent = ticket.title;
  panel.appendChild(title);

  // Meta info
  const meta = document.createElement('div');
  meta.className = 'detail-meta';
  meta.innerHTML = `
    <div class="detail-meta-row"><strong>State:</strong> ${ticket.state}${ticket.previous_state ? ` <span class="detail-prev-state">(was: ${ticket.previous_state})</span>` : ''}</div>
    <div class="detail-meta-row"><strong>Priority:</strong> P${ticket.priority}</div>
    <div class="detail-meta-row"><strong>Project:</strong> ${ticket.project}</div>
    <div class="detail-meta-row"><strong>Branch:</strong> ${ticket.branch_name ?? 'N/A'}</div>
    <div class="detail-meta-row"><strong>Agent:</strong> ${ticket.current_agent ?? 'None'}</div>
    <div class="detail-meta-row"><strong>Last modified:</strong> ${parseUtc(ticket.updated_at).toLocaleString()}</div>
    <div class="detail-meta-row"><strong>Created:</strong> ${parseUtc(ticket.created_at).toLocaleString()}</div>
  `;
  panel.appendChild(meta);

  // Description
  const descSection = document.createElement('div');
  descSection.className = 'detail-section';
  const descHeaderRow = document.createElement('div');
  descHeaderRow.className = 'detail-section-header-row';
  const descHeader = document.createElement('h3');
  descHeader.textContent = 'Description';
  descHeaderRow.appendChild(descHeader);
  const descSaveBtn = document.createElement('button');
  descSaveBtn.className = 'detail-save-btn';
  descSaveBtn.textContent = 'Save';
  descSaveBtn.disabled = true;
  descHeaderRow.appendChild(descSaveBtn);
  descSection.appendChild(descHeaderRow);
  const descBody = document.createElement('textarea');
  descBody.className = 'detail-description';
  descBody.value = ticket.description;
  descBody.rows = 6;
  descBody.addEventListener('input', () => {
    descSaveBtn.disabled = descBody.value === ticket.description;
  });
  descSaveBtn.addEventListener('click', async () => {
    descSaveBtn.disabled = true;
    descSaveBtn.textContent = 'Saving…';
    const res = await apiPatch(`/tickets/${ticket.id}`, { description: descBody.value });
    if (res.ok) {
      ticket.description = descBody.value;
      descSaveBtn.textContent = 'Saved';
    } else {
      descSaveBtn.textContent = 'Save';
      descSaveBtn.disabled = false;
    }
  });
  descSection.appendChild(descBody);
  panel.appendChild(descSection);

  // Acceptance Criteria
  const acSection = document.createElement('div');
  acSection.className = 'detail-section';
  const acHeader = document.createElement('h3');
  acHeader.textContent = 'Acceptance Criteria';
  acSection.appendChild(acHeader);
  const acList = document.createElement('ul');
  acList.className = 'detail-criteria';
  for (const criterion of ticket.acceptance_criteria) {
    const li = document.createElement('li');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.disabled = true;
    li.appendChild(checkbox);
    const span = document.createElement('span');
    span.textContent = ` ${String(criterion)}`;
    li.appendChild(span);
    acList.appendChild(li);
  }
  acSection.appendChild(acList);
  panel.appendChild(acSection);

  // Stats
  const statsSection = document.createElement('div');
  statsSection.className = 'detail-section';
  const statsHeader = document.createElement('h3');
  statsHeader.textContent = 'Stats';
  statsSection.appendChild(statsHeader);
  const statsGrid = document.createElement('div');
  statsGrid.className = 'detail-stats';
  statsGrid.innerHTML = `
    <div class="detail-stat"><span class="detail-stat-label">Agent Attempts</span><span class="detail-stat-value">${ticket.agent_attempts}</span></div>
    <div class="detail-stat"><span class="detail-stat-label">Review Rejections</span><span class="detail-stat-value">${ticket.review_rejection_count}</span></div>
    <div class="detail-stat"><span class="detail-stat-label">Dev Timeouts</span><span class="detail-stat-value">${ticket.developer_timeouts}</span></div>
    <div class="detail-stat"><span class="detail-stat-label">Reviewer Timeouts</span><span class="detail-stat-value">${ticket.reviewer_timeouts}</span></div>
    <div class="detail-stat"><span class="detail-stat-label">Tester Timeouts</span><span class="detail-stat-value">${ticket.tester_timeouts}</span></div>
    <div class="detail-stat"><span class="detail-stat-label">Merger Timeouts</span><span class="detail-stat-value">${ticket.merger_timeouts}</span></div>
  `;
  statsSection.appendChild(statsGrid);
  panel.appendChild(statsSection);

  // Dependencies
  const depsSection = document.createElement('div');
  depsSection.className = 'detail-section';
  const depsHeader = document.createElement('h3');
  depsHeader.textContent = 'Dependencies';
  depsSection.appendChild(depsHeader);
  depsSection.appendChild(
    formatDependencies(deps ?? { blocked_by: [], blocks: [] })
  );
  panel.appendChild(depsSection);

  // Notes
  const notesSection = document.createElement('div');
  notesSection.className = 'detail-section';
  const notesHeader = document.createElement('h3');
  notesHeader.textContent = 'Notes';
  notesSection.appendChild(notesHeader);
  notesSection.appendChild(formatNotes(ticket.notes));
  panel.appendChild(notesSection);

  return panel;
}

export async function openDetailPanel(ticketId: number): Promise<void> {
  // Fetch ticket detail
  let ticket: TicketDetail;
  try {
    const response = await apiGet<TicketDetail>(`/tickets/${ticketId}`);
    if (!response.ok) return;
    ticket = response.data;
  } catch {
    return;
  }

  // Fetch dependencies (best effort)
  let deps: DependencyList | null = null;
  try {
    const response = await apiGet<DependencyList>(
      `/tickets/${ticketId}/dependencies`
    );
    if (response.ok) {
      deps = response.data;
    }
  } catch {
    // continue without dependencies
  }

  // Remove existing overlay if any
  closeDetailPanel();

  // Create overlay
  const overlay = document.createElement('div');
  overlay.className = 'detail-overlay';
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeDetailPanel();
  });

  const panel = renderDetailPanel(ticket, deps);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);
}

export function closeDetailPanel(): void {
  const existing = document.querySelector('.detail-overlay');
  if (existing) {
    existing.remove();
  }
}
