import type { WsClient } from './ws.js';
import type { Ticket } from './types.js';
import { apiGet } from './api.js';
import { renderBoard } from './board.js';

export interface TicketEvent {
  event_type: string;
  ticket_id: number;
  previous_state?: string;
  new_state?: string;
  agent_id?: string | null;
  timestamp: string;
}

// Matches any event that references a specific ticket — covers all agent-driven
// transitions (agent_assigned, agent_completed, agent_failed, ticket_blocked)
// as well as manual ticket_state_changed events.
function isTicketEvent(data: unknown): data is TicketEvent {
  if (typeof data !== 'object' || data === null) return false;
  const obj = data as Record<string, unknown>;
  return typeof obj['ticket_id'] === 'number';
}

export function setupRealtimeUpdates(
  wsClient: WsClient,
  boardEl: HTMLElement,
  dotEl: HTMLElement,
  labelEl: HTMLElement,
  tickets: Ticket[],
  onRender?: (boardEl: HTMLElement, tickets: Ticket[]) => void,
  onSpecUpdate?: () => void,
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
    if (typeof data === 'object' && data !== null && (data as Record<string, unknown>)['event_type'] === 'spec_update') {
      onSpecUpdate?.();
      return;
    }

    if (!isTicketEvent(data)) return;

    // Re-fetch all tickets to get the latest state
    try {
      const response = await apiGet<Ticket[]>('/tickets');
      if (response.ok) {
        currentTickets = response.data;
      } else {
        if (data.new_state) {
          currentTickets = applyStateChange(currentTickets, data);
        }
      }
    } catch {
      if (data.new_state) {
        currentTickets = applyStateChange(currentTickets, data);
      }
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
  event: TicketEvent
): Ticket[] {
  return tickets.map((t) => {
    if (t.id === event.ticket_id) {
      return {
        ...t,
        state: event.new_state ?? t.state,
        current_agent: event.agent_id ?? t.current_agent,
      };
    }
    return t;
  });
}
