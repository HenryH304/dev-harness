import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createWsClient } from './ws.ts';
import type { ConnectionStatus } from './ws.ts';

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closeCalled: boolean;
  url: string;

  constructor(url: string) {
    this.url = url;
    this.closeCalled = false;
    MockWebSocket.instances.push(this);
  }

  close(): void {
    this.closeCalled = true;
    this.onclose?.();
  }

  simulateOpen(): void {
    this.onopen?.();
  }

  simulateMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  simulateClose(): void {
    this.onclose?.();
  }

  simulateError(): void {
    this.onerror?.();
  }
}

vi.stubGlobal('WebSocket', MockWebSocket);

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('createWsClient', () => {
  it('starts with disconnected status', () => {
    const client = createWsClient('ws://localhost/ws');
    expect(client.getStatus()).toBe('disconnected');
  });

  it('connects and reports connected status', () => {
    const client = createWsClient('ws://localhost/ws');
    const statuses: ConnectionStatus[] = [];
    client.onStatusChange((s) => statuses.push(s));

    client.connect();
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toBe('ws://localhost/ws');

    MockWebSocket.instances[0].simulateOpen();
    expect(client.getStatus()).toBe('connected');
    expect(statuses).toContain('connected');
  });

  it('delivers parsed JSON messages to handlers', () => {
    const client = createWsClient('ws://localhost/ws');
    const messages: unknown[] = [];
    client.onMessage((data) => messages.push(data));

    client.connect();
    MockWebSocket.instances[0].simulateOpen();
    MockWebSocket.instances[0].simulateMessage({ type: 'ticket_state_changed', ticket_id: 1 });

    expect(messages).toHaveLength(1);
    expect(messages[0]).toEqual({ type: 'ticket_state_changed', ticket_id: 1 });
  });

  it('auto-reconnects on unexpected close', () => {
    const client = createWsClient('ws://localhost/ws', 1000);
    const statuses: ConnectionStatus[] = [];
    client.onStatusChange((s) => statuses.push(s));

    client.connect();
    MockWebSocket.instances[0].simulateOpen();
    MockWebSocket.instances[0].simulateClose();

    expect(client.getStatus()).toBe('reconnecting');

    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('does not reconnect on intentional disconnect', () => {
    const client = createWsClient('ws://localhost/ws', 1000);
    client.connect();
    MockWebSocket.instances[0].simulateOpen();

    client.disconnect();
    expect(client.getStatus()).toBe('disconnected');

    vi.advanceTimersByTime(5000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('handles WebSocket error by closing', () => {
    const client = createWsClient('ws://localhost/ws');
    client.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();
    ws.simulateError();
    expect(ws.closeCalled).toBe(true);
  });
});
