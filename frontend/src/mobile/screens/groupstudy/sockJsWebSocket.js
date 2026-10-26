export const SOCKJS_FRAME = {
  OPEN: 'open',
  HEARTBEAT: 'heartbeat',
  MESSAGES: 'messages',
  CLOSE: 'close',
  UNKNOWN: 'unknown',
};

const READY_STATE = {
  CONNECTING: 0,
  OPEN: 1,
  CLOSING: 2,
  CLOSED: 3,
};

function randomServerId() {
  return String(Math.floor(Math.random() * 1000)).padStart(3, '0');
}

function randomSessionId() {
  return Math.random().toString(36).slice(2, 10);
}

export function sockJsWebSocketUrl(endpointUrl, serverId = randomServerId(), sessionId = randomSessionId()) {
  const websocketBase = endpointUrl.replace(/^http/, 'ws').replace(/\/+$/, '');
  return `${websocketBase}/${serverId}/${sessionId}/websocket`;
}

function parseJsonArray(text) {
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function parseSockJsFrame(raw) {
  const text = String(raw ?? '');
  const kind = text.charAt(0);

  if (kind === 'o') return { type: SOCKJS_FRAME.OPEN };
  if (kind === 'h') return { type: SOCKJS_FRAME.HEARTBEAT };

  if (kind === 'a') {
    const messages = parseJsonArray(text.slice(1));
    return messages ? { type: SOCKJS_FRAME.MESSAGES, messages } : { type: SOCKJS_FRAME.UNKNOWN };
  }

  if (kind === 'm') {
    const messages = parseJsonArray(`[${text.slice(1)}]`);
    return messages ? { type: SOCKJS_FRAME.MESSAGES, messages } : { type: SOCKJS_FRAME.UNKNOWN };
  }

  if (kind === 'c') {
    const [code, reason] = parseJsonArray(text.slice(1)) || [];
    return { type: SOCKJS_FRAME.CLOSE, code, reason };
  }

  return { type: SOCKJS_FRAME.UNKNOWN };
}

export function encodeSockJsMessage(data) {
  return JSON.stringify([data]);
}

export class SockJsWebSocket {
  constructor(url, { onActivity = () => {}, WebSocketImpl = WebSocket } = {}) {
    this.url = url;
    this.binaryType = 'arraybuffer';
    this.readyState = READY_STATE.CONNECTING;
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    this.onActivity = onActivity;

    this.socket = new WebSocketImpl(url);
    this.socket.onmessage = (event) => this.handleFrame(event.data);
    this.socket.onerror = (event) => this.onerror?.(event);
    this.socket.onclose = (event) => this.handleClose(event);
  }

  handleFrame(raw) {
    this.onActivity();
    const frame = parseSockJsFrame(raw);

    if (frame.type === SOCKJS_FRAME.OPEN) {
      this.readyState = READY_STATE.OPEN;
      this.onopen?.({ type: 'open' });
      return;
    }

    if (frame.type === SOCKJS_FRAME.MESSAGES) {
      frame.messages.forEach((data) => this.onmessage?.({ data }));
      return;
    }

    if (frame.type === SOCKJS_FRAME.CLOSE) {
      this.socket.close();
    }
  }

  handleClose(event) {
    this.readyState = READY_STATE.CLOSED;
    this.onclose?.(event);
  }

  send(data) {
    if (this.readyState !== READY_STATE.OPEN) return;
    this.socket.send(encodeSockJsMessage(data));
  }

  close() {
    if (this.readyState === READY_STATE.CLOSED) return;
    this.readyState = READY_STATE.CLOSING;
    this.socket.close();
  }
}
