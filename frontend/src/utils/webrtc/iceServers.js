const TURN_HOST = import.meta.env.VITE_TURN_HOST || '43.202.211.123:3478';
const TURN_USERNAME = import.meta.env.VITE_TURN_USERNAME || 'studybridge';
const TURN_CREDENTIAL =
  import.meta.env.VITE_TURN_CREDENTIAL || '00ce0e28506590253bceac8215653f6de6633355e9a0f4c2';

export const STUDYBRIDGE_ICE_SERVERS = [
  { urls: 'stun:stun.l.google.com:19302' },
  {
    urls: [`turn:${TURN_HOST}?transport=udp`, `turn:${TURN_HOST}?transport=tcp`],
    username: TURN_USERNAME,
    credential: TURN_CREDENTIAL,
  },
];

export function forceSecureWebSocketTransport(openViduInstance) {
  if (!openViduInstance || openViduInstance.__studybridgeWssPatched) return;

  const originalStartWs = openViduInstance.startWs?.bind(openViduInstance);
  if (!originalStartWs) return;

  openViduInstance.startWs = (...args) => {
    const isInsecureUri =
      typeof openViduInstance.wsUri === 'string' && /^ws:\/\//i.test(openViduInstance.wsUri);

    if (isInsecureUri) {
      openViduInstance.wsUri = openViduInstance.wsUri.replace(/^ws:\/\//i, 'wss://');
    }

    return originalStartWs(...args);
  };

  openViduInstance.__studybridgeWssPatched = true;
}

export function parseConnectionMetadata(connection) {
  const raw = connection?.data;
  if (!raw) return {};

  const candidates = typeof raw === 'string' && raw.includes('%/%') ? raw.split('%/%') : [raw];

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate);
      if (parsed && typeof parsed === 'object') return parsed;
    } catch {
      continue;
    }
  }

  return {};
}
