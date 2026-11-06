export type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting';
export type MessageHandler = (data: unknown) => void;
export type StatusHandler = (status: ConnectionStatus) => void;

export interface WsClient {
  connect(): void;
  disconnect(): void;
  onMessage(handler: MessageHandler): void;
  onStatusChange(handler: StatusHandler): void;
  getStatus(): ConnectionStatus;
}

export function createWsClient(url: string, reconnectInterval = 3000): WsClient {
  let ws: WebSocket | null = null;
  let status: ConnectionStatus = 'disconnected';
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let intentionalClose = false;
  const messageHandlers: MessageHandler[] = [];
  const statusHandlers: StatusHandler[] = [];

  function setStatus(newStatus: ConnectionStatus): void {
    status = newStatus;
    statusHandlers.forEach((h) => h(newStatus));
  }

  function scheduleReconnect(): void {
    if (intentionalClose) return;
    setStatus('reconnecting');
    reconnectTimer = setTimeout(() => {
      connect();
    }, reconnectInterval);
  }

  function connect(): void {
    if (ws !== null) return;
    intentionalClose = false;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    ws = new WebSocket(url);

    ws.onopen = (): void => {
      setStatus('connected');
    };

    ws.onmessage = (event: MessageEvent): void => {
      try {
        const data: unknown = JSON.parse(event.data as string);
        messageHandlers.forEach((h) => h(data));
      } catch {
        // ignore non-JSON messages
      }
    };

    ws.onclose = (): void => {
      ws = null;
      if (!intentionalClose) {
        scheduleReconnect();
      } else {
        setStatus('disconnected');
      }
    };

    ws.onerror = (): void => {
      ws?.close();
    };
  }

  function disconnect(): void {
    intentionalClose = true;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    ws?.close();
    ws = null;
    setStatus('disconnected');
  }

  return {
    connect,
    disconnect,
    onMessage(handler: MessageHandler): void {
      messageHandlers.push(handler);
    },
    onStatusChange(handler: StatusHandler): void {
      statusHandlers.push(handler);
    },
    getStatus(): ConnectionStatus {
      return status;
    },
  };
}
