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

/**
 * 서버가 발급한 시간제한 TURN 자격증명이 있으면 그것을 쓰고, 없으면 기존 정적 설정으로 폴백한다.
 * 토큰 응답 예: { token, iceServers: [{ urls, username, credential, ttlSeconds }] }
 *
 * 정적 자격증명은 웹 번들과 APK 에 그대로 실려 누구나 읽을 수 있다.
 * coturn 을 --use-auth-secret 으로 전환하고 Spring 이 세션마다 발급하면 이 폴백은 제거할 수 있다.
 */
export function resolveIceServers(tokenResponse) {
  const issued = tokenResponse?.iceServers;

  if (Array.isArray(issued) && issued.length > 0) {
    return issued;
  }

  return STUDYBRIDGE_ICE_SERVERS;
}

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
