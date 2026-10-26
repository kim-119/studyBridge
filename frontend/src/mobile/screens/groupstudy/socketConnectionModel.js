export const SOCKET_STATE = {
  IDLE: 'idle',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  RECONNECTING: 'reconnecting',
  OFFLINE: 'offline',
  FAILED: 'failed',
};

export const RECONNECT_POLICY = {
  baseDelayMs: 1000,
  maxDelayMs: 30000,
  maxAttempts: 8,
};

export const SOCKJS_HEARTBEAT_MS = 25000;
export const STALE_CONNECTION_MS = SOCKJS_HEARTBEAT_MS * 2 + 10000;
export const TOKEN_REFRESH_MARGIN_MS = 60000;

export function reconnectDelayMs(attempt, policy = RECONNECT_POLICY) {
  const safeAttempt = Math.max(0, Math.floor(attempt));
  const exponential = policy.baseDelayMs * 2 ** safeAttempt;
  return Math.min(policy.maxDelayMs, exponential);
}

export function hasExhaustedReconnects(attempt, policy = RECONNECT_POLICY) {
  return attempt >= policy.maxAttempts;
}

export function planReconnect(attempt, policy = RECONNECT_POLICY) {
  if (hasExhaustedReconnects(attempt, policy)) return { kind: 'give-up' };
  return { kind: 'retry', delayMs: reconnectDelayMs(attempt, policy), nextAttempt: attempt + 1 };
}

export function isConnectionStale(lastActivityAt, now, thresholdMs = STALE_CONNECTION_MS) {
  if (!lastActivityAt) return false;
  return now - lastActivityAt > thresholdMs;
}

function decodeBase64Url(segment) {
  const base64 = segment.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
  return atob(padded);
}

export function readTokenExpiryMs(token) {
  if (typeof token !== 'string') return null;

  const [, payloadSegment] = token.split('.');
  if (!payloadSegment) return null;

  try {
    const payload = JSON.parse(decodeBase64Url(payloadSegment));
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

export function isTokenExpiring(token, now, marginMs = TOKEN_REFRESH_MARGIN_MS) {
  const expiresAt = readTokenExpiryMs(token);
  if (expiresAt === null) return false;
  return expiresAt - now <= marginMs;
}

export const SOCKET_STATUS_LABEL = {
  [SOCKET_STATE.IDLE]: '실시간 연결 준비 중',
  [SOCKET_STATE.CONNECTING]: '실시간 서버에 연결하는 중',
  [SOCKET_STATE.CONNECTED]: '실시간 연결됨',
  [SOCKET_STATE.RECONNECTING]: '연결이 끊겨 다시 연결하는 중',
  [SOCKET_STATE.OFFLINE]: '네트워크 연결이 없습니다',
  [SOCKET_STATE.FAILED]: '실시간 연결에 실패했습니다',
};

export function describeSocketStatus(state, reconnectAttempt = 0) {
  const label = SOCKET_STATUS_LABEL[state] || SOCKET_STATUS_LABEL[SOCKET_STATE.IDLE];
  if (state === SOCKET_STATE.RECONNECTING && reconnectAttempt > 0) {
    return `${label} (${reconnectAttempt}/${RECONNECT_POLICY.maxAttempts})`;
  }
  return label;
}

export function canRetryManually(state) {
  return state === SOCKET_STATE.FAILED || state === SOCKET_STATE.RECONNECTING || state === SOCKET_STATE.OFFLINE;
}
