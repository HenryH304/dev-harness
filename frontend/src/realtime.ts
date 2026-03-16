import type { WsClient } from './ws.js';
import type { Ticket } from './types.js';
import { apiGet } from './api.js';
import { renderBoard } from './board.js';

export interface StateChangeEvent {
  event_type: string;
  ticket_id: number;
  previous_state: string;
  new_state: string;
  agent_id: string | null;
  timestamp: string;
}

function isStateChangeEvent(data: unknown): data is StateChangeEvent {
  if (typeof data !== 'object' || data === null) return false;
  const obj = data as Record<string, unknown>;
  return (
    obj['event_type'] === 'ticket_state_changed' &&
    typeof obj['ticket_id'] === 'number' &&
    typeof obj['new_state'] === 'string'
  );
}

export function setupRealtimeUpdates(
  wsClient: WsClient,
  boardEl: HTMLElement,
  dotEl: HTMLElement,
  labelEl: HTMLElement,
  tickets: Ticket[],
  onRender?: (boardEl: HTMLElement, tickets: Ticket[]) => void
): void {
  let currentTickets = [...tickets];

  wsClient.onStatusChange((status) => {
    dotEl.className = 'dot';
    if (status === 'connected') {
      dotEl.classList.add('connected');
      labelEl.textContent = 'Connected';
    } else if (status === 'reconnecting') {
      dotEl.classList.add('reconnecting');
      labelEl.textContent = 'Reconnecting...';
    } else {
      labelEl.textContent = 'Disconnected';
    }
  });

  wsClient.onMessage(async (data: unknown) => {
    if (!isStateChangeEvent(data)) return;

    // Re-fetch all tickets to get the latest state
    try {
      const response = await apiGet<Ticket[]>('/tickets');
      if (response.ok) {
        currentTickets = response.data;
      } else {
        // Fallback: update locally
        currentTickets = applyStateChange(currentTickets, data);
      }
    } catch {
      // Fallback: update locally
      currentTickets = applyStateChange(currentTickets, data);
    }

    renderBoard(boardEl, currentTickets);
    if (onRender) {
      onRender(boardEl, currentTickets);
    }
  });

  wsClient.connect();
}

export function applyStateChange(
  tickets: Ticket[],
  event: StateChangeEvent
): Ticket[] {
  return tickets.map((t) => {
    if (t.id === event.ticket_id) {
      return {
        ...t,
        state: event.new_state,
        current_agent: event.agent_id ?? t.current_agent,
      };
    }
    return t;
  });
}
