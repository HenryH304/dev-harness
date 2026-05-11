import type { Ticket } from './types.js';
import { apiPost } from './api.js';

export const ALLOWED_TRANSITIONS: Record<string, string[]> = {
  to_do: ['in_progress', 'blocked'],
  in_progress: ['ready_for_review', 'blocked'],
  ready_for_review: ['in_review', 'blocked'],
  in_review: ['ready_for_test', 'blocked'],
  ready_for_test: ['in_test', 'blocked'],
  in_test: ['ready_for_merge', 'blocked'],
  ready_for_merge: ['in_merge', 'blocked'],
  in_merge: ['done', 'blocked'],
  done: ['blocked'],
  blocked: [
    'to_do',
    'in_progress',
    'ready_for_review',
    'in_review',
    'ready_for_test',
    'in_test',
    'ready_for_merge',
    'in_merge',
    'done',
  ],
};

export function isValidTransition(from: string, to: string): boolean {
  if (from === to) return false;
  const allowed = ALLOWED_TRANSITIONS[from];
  return allowed ? allowed.includes(to) : false;
}

interface DragState {
  ticketId: number | null;
  fromState: string | null;
}

let dragState: DragState = { ticketId: null, fromState: null };
let undoTimer: ReturnType<typeof setTimeout> | null = null;

export function setupDragDrop(boardEl: HTMLElement, tickets: Ticket[]): void {
  const ticketMap = new Map<number, Ticket>();
  for (const t of tickets) {
    ticketMap.set(t.id, t);
  }

  // Make all cards draggable
  const cards = boardEl.querySelectorAll('.card');
  cards.forEach((card) => {
    const el = card as HTMLElement;
    el.setAttribute('draggable', 'true');

    el.addEventListener('dragstart', (e: Event) => {
      const de = e as DragEvent;
      const ticketId = Number(el.getAttribute('data-ticket-id'));
      const ticket = ticketMap.get(ticketId);
      if (!ticket) return;

      dragState = { ticketId, fromState: ticket.state };
      el.classList.add('card--dragging');

      if (de.dataTransfer) {
        de.dataTransfer.setData('text/plain', String(ticketId));
        de.dataTransfer.effectAllowed = 'move';
      }
    });

    el.addEventListener('dragend', () => {
      el.classList.remove('card--dragging');
      // Clean up drop target highlights
      boardEl.querySelectorAll('.column--drop-target, .column--invalid-drop').forEach((col) => {
        col.classList.remove('column--drop-target', 'column--invalid-drop');
      });
      dragState = { ticketId: null, fromState: null };
    });
  });

  // Set up column drop zones
  const columns = boardEl.querySelectorAll('.column');
  columns.forEach((col) => {
    const colEl = col as HTMLElement;
    const columnKey = colEl.getAttribute('data-column') || '';

    colEl.addEventListener('dragenter', (e: Event) => {
      e.preventDefault();
      if (!dragState.fromState) return;

      // Remove existing highlights
      boardEl.querySelectorAll('.column--drop-target, .column--invalid-drop').forEach((c) => {
        c.classList.remove('column--drop-target', 'column--invalid-drop');
      });

      if (isValidTransition(dragState.fromState, columnKey)) {
        colEl.classList.add('column--drop-target');
      } else {
        colEl.classList.add('column--invalid-drop');
      }
    });

    colEl.addEventListener('dragover', (e: Event) => {
      if (!dragState.fromState) return;
      if (isValidTransition(dragState.fromState, columnKey)) {
        e.preventDefault(); // Allow drop
      }
    });

    colEl.addEventListener('dragleave', () => {
      colEl.classList.remove('column--drop-target', 'column--invalid-drop');
    });

    colEl.addEventListener('drop', (e: Event) => {
      e.preventDefault();
      colEl.classList.remove('column--drop-target', 'column--invalid-drop');

      if (!dragState.ticketId || !dragState.fromState) return;
      if (!isValidTransition(dragState.fromState, columnKey)) return;

      const ticketId = dragState.ticketId;
      const fromState = dragState.fromState;
      const toState = columnKey;

      // Call transition API with manual_override flag
      const isFromBlocked = fromState === 'blocked';
      apiPost(`/tickets/${ticketId}/transition`, {
        new_state: toState,
        manual_override: isFromBlocked,
        note: `Manually moved from ${fromState} to ${toState} by user`,
      }).then(() => {
        // Show undo toast
        showUndoToast(ticketId, fromState, toState, () => {
          // Undo: transition back to original state
          apiPost(`/tickets/${ticketId}/transition`, {
            new_state: fromState,
            manual_override: true,
            note: `Undo: reverted from ${toState} back to ${fromState} by user`,
          });
        });
      });
    });
  });
}

export function showUndoToast(
  ticketId: number,
  fromState: string,
  toState: string,
  onUndo: () => void
): void {
  // Remove any existing toast
  hideUndoToast();

  const toast = document.createElement('div');
  toast.className = 'undo-toast';

  const label = document.createElement('span');
  label.textContent = `Moved ticket #${ticketId} from ${fromState.replace(/_/g, ' ')} to ${toState.replace(/_/g, ' ')}`;
  toast.appendChild(label);

  const btn = document.createElement('button');
  btn.textContent = 'Undo';
  btn.addEventListener('click', () => {
    onUndo();
    hideUndoToast();
  });
  toast.appendChild(btn);

  document.body.appendChild(toast);

  undoTimer = setTimeout(() => {
    hideUndoToast();
  }, 5000);
}

export function hideUndoToast(): void {
  if (undoTimer) {
    clearTimeout(undoTimer);
    undoTimer = null;
  }
  const existing = document.querySelector('.undo-toast');
  if (existing) {
    existing.remove();
  }
}
