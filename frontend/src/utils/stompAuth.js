// 그룹스터디 STOMP 인증 계약(서버 StompAuthChannelInterceptor 와 짝).
//  · CONNECT 프레임에 Authorization: Bearer <액세스 토큰> 을 넣는다. 재연결마다 최신 토큰을 다시 읽고, 곧 만료면 먼저 갱신한다.
//  · 서버 ERROR 프레임 message 헤더:
//      UNAUTHORIZED → 토큰 없음·위조·만료. 토큰을 강제 갱신한 뒤 다시 연결(연속 실패는 제한).
//      FORBIDDEN    → 그룹 멤버 아님·허용되지 않은 목적지·사칭·정지. 재연결해도 같으므로 멈춘다.
//    세부 사유는 sb-reason 헤더(예: NOT_GROUP_MEMBER, MEMBERSHIP_REVOKED).

export const TOKEN_REFRESH_MARGIN_MS = 60_000;
export const MAX_UNAUTHORIZED_RETRIES = 3;

function decodeBase64Url(segment) {
  const base64 = segment.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
  if (typeof atob === 'function') return atob(padded);
  return Buffer.from(padded, 'base64').toString('binary');
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

// exp 를 읽을 수 없는 토큰은 서버 판단에 맡긴다(만료로 보지 않음).
export function isTokenExpiring(token, now, marginMs = TOKEN_REFRESH_MARGIN_MS) {
  const expiresAt = readTokenExpiryMs(token);
  if (expiresAt == null) return false;
  return expiresAt - now <= marginMs;
}

/**
 * 연결 직전에 쓸 액세스 토큰. 없거나 곧 만료되거나 서버가 UNAUTHORIZED 로 거부한 직후(forceRefresh)면 갱신한다.
 * 갱신이 실패하면 저장된 토큰을 그대로 쓴다(서버가 다시 거부하면 재시도 한도에서 멈춘다).
 */
export async function resolveStompAccessToken({ getStoredToken, refresh, now = Date.now(), forceRefresh = false }) {
  const stored = getStoredToken();
  const needsRefresh = forceRefresh || !stored || isTokenExpiring(stored, now);
  if (!needsRefresh || typeof refresh !== 'function') return stored || null;
  try {
    return (await refresh()) || stored || null;
  } catch {
    return getStoredToken() || null;
  }
}

export function buildStompConnectHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function classifyStompError(frame) {
  const code = String(frame?.headers?.message || '').trim().toUpperCase();
  if (code.startsWith('UNAUTHORIZED')) return 'unauthorized';
  if (code.startsWith('FORBIDDEN')) return 'forbidden';
  return 'other';
}

export function stompErrorReason(frame) {
  return frame?.headers?.['sb-reason'] || null;
}

/**
 * ERROR 프레임에 대한 클라이언트 동작을 정한다(상태 보관).
 *  · 'refresh-and-retry' : 다음 연결 전에 토큰을 강제 갱신하고 기존 재연결 주기를 따른다.
 *  · 'stop'              : 재연결을 멈춘다(client.deactivate()). message 로 사용자 안내.
 *  · 'retry'             : 인증과 무관한 오류 — 기존 재연결 동작 유지.
 */
export function createStompAuthPolicy({ maxUnauthorizedRetries = MAX_UNAUTHORIZED_RETRIES } = {}) {
  let unauthorizedStreak = 0;
  let forceRefreshNext = false;

  return {
    onConnected() {
      unauthorizedStreak = 0;
      forceRefreshNext = false;
    },
    consumeForceRefresh() {
      const value = forceRefreshNext;
      forceRefreshNext = false;
      return value;
    },
    onError(frame) {
      const kind = classifyStompError(frame);
      const reason = stompErrorReason(frame);
      if (kind === 'forbidden') {
        return { action: 'stop', kind, reason, message: forbiddenMessage(reason) };
      }
      if (kind === 'unauthorized') {
        unauthorizedStreak += 1;
        if (unauthorizedStreak > maxUnauthorizedRetries) {
          return { action: 'stop', kind, reason, message: '로그인이 만료되어 실시간 채팅·퀴즈 연결을 멈췄습니다. 다시 로그인해 주세요.' };
        }
        forceRefreshNext = true;
        return { action: 'refresh-and-retry', kind, reason, message: null };
      }
      return { action: 'retry', kind, reason, message: null };
    },
  };
}

function forbiddenMessage(reason) {
  if (reason === 'MEMBERSHIP_REVOKED') return '그룹스터디 참여 권한이 없어 실시간 채팅·퀴즈 연결을 종료했습니다.';
  if (reason === 'USER_INACTIVE' || reason === 'ACCOUNT_REVOKED') return '이용이 제한된 계정이라 실시간 채팅·퀴즈에 연결할 수 없습니다.';
  if (reason === 'NOT_GROUP_MEMBER') return '그룹 멤버만 실시간 채팅·퀴즈에 참여할 수 있습니다.';
  return '실시간 채팅·퀴즈 연결이 거부되었습니다.';
}

// 퀴즈 제출 확인(ack)은 그룹 전체에 방송된다. 내 ack 만 내 제출 상태에 반영한다
//  (다른 멤버의 제출이 내 답안 버튼을 잠그거나 선택을 지우지 않게). userId 가 없는 ack 는 이전 서버 호환으로 반영.
export function isOwnQuizAck(payload, userId) {
  if (!payload) return false;
  if (payload.userId === undefined || payload.userId === null) return true;
  return String(payload.userId) === String(userId);
}
