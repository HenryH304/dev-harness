/**
 * Spec generation progress panel — persistent strip above the board showing active specs.
 * Dismissals are persisted in localStorage so they survive page reloads.
 */

import { apiGet } from './api.js';

export interface SpecOut {
  id: number;
  project: string;
  description: string;
  spec_content: string | null;
  status: string;
  step: string | null;
  imported_count: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

const DISMISSED_KEY = 'spp:dismissed';

function loadDismissed(): Set<number> {
  try {
    const raw = localStorage.getItem(DISMISSED_KEY);
    return raw ? new Set(JSON.parse(raw) as number[]) : new Set();
  } catch {
    return new Set();
  }
}

function saveDismissed(dismissed: Set<number>): void {
  localStorage.setItem(DISMISSED_KEY, JSON.stringify([...dismissed]));
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function trunc(s: string, max = 72): string {
  return s.length > max ? s.slice(0, max) + '…' : s;
}

function stepLabel(step: string | null): string {
  switch (step) {
    case 'spec_writing': return 'Writing specification…';
    case 'amending':     return 'Applying amendment…';
    case 'converting':   return 'Converting to tasks…';
    case 'importing':    return 'Importing tasks…';
    default:             return 'Processing…';
  }
}

function statusIcon(s: SpecOut): string {
  if (s.status === 'running' || s.status === 'pending') return '<span class="sph-icon sph-icon--running">⟳</span>';
  if (s.status === 'failed') return '<span class="sph-icon sph-icon--error">✗</span>';
  if (s.status === 'done' && s.step === 'spec_writing') return '<span class="sph-icon sph-icon--ready">◎</span>';
  if (s.status === 'done') return '<span class="sph-icon sph-icon--done">✓</span>';
  return '';
}

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// --- History modal ---

export function openSpecHistory(): void {
  document.querySelector('.sph-overlay')?.remove();
  const overlay = document.createElement('div');
  overlay.className = 'sph-overlay';
  document.body.appendChild(overlay);

  function close(): void { overlay.remove(); }
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); });

  overlay.innerHTML = `
    <div class="sph-modal">
      <div class="add-story-header">
        <h2 class="add-story-title">Spec History</h2>
        <button class="add-story-close" aria-label="Close">&times;</button>
      </div>
      <div class="sph-body">
        <p class="dash-loading">Loading…</p>
      </div>
    </div>`;

  overlay.querySelector('.add-story-close')!.addEventListener('click', close);

  const body = overlay.querySelector('.sph-body')!;
  const dismissed = loadDismissed();

  apiGet<SpecOut[]>('/specs').then(resp => {
    if (!resp.ok || resp.data.length === 0) {
      body.innerHTML = '<p class="dash-empty">No spec history yet.</p>';
      return;
    }

    body.innerHTML = `<table class="sph-table">
      <thead>
        <tr><th></th><th>Description</th><th>Step</th><th>Started</th><th>Completed</th><th>Dismissed</th></tr>
      </thead>
      <tbody>
        ${resp.data.map(s => `
          <tr class="sph-row sph-row--${s.status}${dismissed.has(s.id) ? ' sph-row--dismissed' : ''}">
            <td>${statusIcon(s)}</td>
            <td class="sph-desc" title="${esc(s.description)}">${esc(trunc(s.description, 60))}</td>
            <td>${s.status === 'failed' ? `<span class="sph-error" title="${esc(s.error ?? '')}">${esc(s.step ?? '—')} (failed)</span>` : (s.step ?? '—')}</td>
            <td class="sph-time">${formatTime(s.created_at)}</td>
            <td class="sph-time">${formatTime(s.completed_at)}</td>
            <td>${dismissed.has(s.id) ? '<span class="sph-dismissed-badge">dismissed</span>' : '—'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>`;
  }).catch(() => {
    body.innerHTML = '<p class="dash-empty">Failed to load history.</p>';
  });
}

// --- Progress panel ---

export function mountSpecProgressPanel(
  container: HTMLElement,
  options: {
    onReview: (specId: number) => void;
    onTasksCreated: () => void;
  },
): { refresh: () => Promise<void>; stop: () => void } {
  const { onReview, onTasksCreated } = options;

  const dismissed = loadDismissed();
  const notifiedDone = new Set<number>();
  let specs: SpecOut[] = [];
  let bootstrapped = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  function dismiss(id: number): void {
    dismissed.add(id);
    saveDismissed(dismissed);
    render();
  }

  function renderCard(s: SpecOut): string {
    const desc = esc(trunc(s.description));

    if (s.status === 'running' || s.status === 'pending') {
      return `<div class="spp-card spp-card--running" data-spec-id="${s.id}">
        <div class="spp-spinner"></div>
        <div class="spp-info">
          <span class="spp-desc">${desc}</span>
          <span class="spp-step">${stepLabel(s.step)}</span>
        </div>
      </div>`;
    }

    if (s.status === 'done' && s.step === 'spec_writing') {
      return `<div class="spp-card spp-card--ready" data-spec-id="${s.id}">
        <div class="spp-info">
          <span class="spp-desc">${desc}</span>
          <span class="spp-step">Spec ready — awaiting review</span>
        </div>
        <div class="spp-actions">
          <button class="dash-btn dash-btn-primary spp-review-btn">Review</button>
          <button class="dash-btn spp-dismiss-btn">Dismiss</button>
        </div>
      </div>`;
    }

    if (s.status === 'done' && (s.step === 'importing' || s.imported_count !== null)) {
      const n = s.imported_count ?? 0;
      return `<div class="spp-card spp-card--done" data-spec-id="${s.id}">
        <div class="spp-info">
          <span class="spp-desc">${desc}</span>
          <span class="spp-step">✓ ${n} task${n !== 1 ? 's' : ''} created</span>
        </div>
        <button class="dash-btn spp-dismiss-btn">Dismiss</button>
      </div>`;
    }

    if (s.status === 'failed') {
      return `<div class="spp-card spp-card--error" data-spec-id="${s.id}">
        <div class="spp-info">
          <span class="spp-desc">${desc}</span>
          <span class="spp-step spp-step--error">Failed: ${esc(s.error ?? 'unknown error')}</span>
        </div>
        <button class="dash-btn spp-dismiss-btn">Dismiss</button>
      </div>`;
    }

    return '';
  }

  function render(): void {
    const visible = specs.filter(s => !dismissed.has(s.id));
    if (visible.length === 0) {
      container.hidden = true;
      return;
    }
    container.hidden = false;
    container.innerHTML = `<div class="spp-panel">
      <div class="spp-cards">${visible.map(renderCard).join('')}</div>
    </div>`;

    container.querySelectorAll<HTMLElement>('[data-spec-id]').forEach(card => {
      const id = parseInt(card.dataset.specId ?? '0', 10);
      card.querySelector('.spp-review-btn')?.addEventListener('click', () => onReview(id));
      card.querySelector('.spp-dismiss-btn')?.addEventListener('click', () => dismiss(id));
    });
  }

  async function refresh(): Promise<void> {
    const resp = await apiGet<SpecOut[]>('/specs');
    if (!resp.ok) return;

    const active = resp.data.filter(s => {
      if (dismissed.has(s.id)) return false;
      if (s.status === 'running' || s.status === 'pending') return true;
      if (s.status === 'failed') return true;
      if (s.status === 'done') {
        if (s.step === 'spec_writing') return true;
        if (s.step === 'importing' || s.imported_count !== null) return true;
      }
      return false;
    });

    if (!bootstrapped) {
      for (const s of active) {
        if (s.status === 'done' && (s.step === 'importing' || s.imported_count !== null)) {
          notifiedDone.add(s.id);
        }
      }
      bootstrapped = true;
    }

    specs = active;

    for (const s of specs) {
      if (
        s.status === 'done' &&
        (s.step === 'importing' || s.imported_count !== null) &&
        !notifiedDone.has(s.id)
      ) {
        notifiedDone.add(s.id);
        onTasksCreated();
      }
    }

    render();
  }

  pollTimer = setInterval(refresh, 3000);
  void refresh();

  return {
    refresh,
    stop() {
      if (pollTimer !== null) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    },
  };
}
