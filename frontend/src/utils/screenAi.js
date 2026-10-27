// AI 화면 분석 탭의 순수 로직(브라우저 API 비의존 — node:test 로 검증).
//  · 화면 목록 = 클라이언트가 실제로 받고 있는 화면공유(StreamManager 보유) ∩ 서버 상태(공유자 이름·동의). 서버가 Source of Truth 이고,
//    아직 서버 목록에 없는 공유(방금 시작)는 '확인 중'으로 두고 분석을 막지 않는다(서버가 최종 판정).
//  · 오류 = Spring 계약 {status, code, message, retryable, retryAfterSeconds} → 사용자 안내.

export const SCREEN_AI_CONSENT_SIGNAL = 'sb-screen-ai-consent';
export const SCREEN_AI_MAX_QUESTION = 1000;

export const SCREEN_AI_EXAMPLES = Object.freeze([
  '지금 보이는 화면 요약해 줘.',
  '이 Python 오류의 원인을 분석해 줘.',
  '이 PPT 내용을 설명해 줘.',
  '화면의 수학 공식을 설명해 줘.',
]);

/** 현재 게시 중인 스트림 id(공유를 다시 시작하면 바뀐다). */
export const streamIdOf = (streamManager) => streamManager?.stream?.streamId || null;

/**
 * @param clientShares StudyRoom screenShares: [{ connectionId, userId, name, isMine, isOwnUser, streamManager, connectedAt }]
 * @param serverShares GET /screen-ai/shares 의 shares (없으면 null = 아직 못 읽음)
 */
export function mergeScreenAiShares(clientShares, serverShares) {
  const byId = new Map((serverShares || []).map((s) => [s.connectionId, s]));
  return (clientShares || []).map((sh, index) => {
    const srv = byId.get(sh.connectionId) || null;
    const streamId = streamIdOf(sh.streamManager) || srv?.streamId || null;
    const own = !!(sh.isOwnUser || srv?.isMine);
    return {
      connectionId: sh.connectionId,
      streamId,
      index: index + 1,
      name: srv?.sharerName || sh.name || '참여자',
      isMine: !!sh.isMine,
      isOwnUser: own,
      known: !!srv,
      aiConsent: !!srv?.aiConsent,
      // 서버 목록에 아직 없으면(방금 시작) 내 화면만 분석 가능으로 보고, 남의 화면은 동의 확인 전까지 막는다.
      analyzable: srv ? !!srv.analyzable : own,
      streamManager: sh.streamManager || null,
    };
  });
}

/** 기본 선택: 지금 선택이 유효하면 유지 → 스테이지에서 보고 있는 화면 → 분석 가능한 남의 화면 → 분석 가능한 화면 → 첫 화면. */
export function pickDefaultShare(shares, currentId, stageSelectedId) {
  const list = shares || [];
  if (currentId && list.some((s) => s.connectionId === currentId)) return currentId;
  if (stageSelectedId && list.some((s) => s.connectionId === stageSelectedId)) return stageSelectedId;
  return (list.find((s) => s.analyzable && !s.isOwnUser) || list.find((s) => s.analyzable) || list[0] || {}).connectionId || null;
}

/** 질문 검증 → 오류 문구(통과하면 null). */
export function validateQuestion(question, max = SCREEN_AI_MAX_QUESTION) {
  const q = String(question || '').trim();
  if (!q) return '질문을 입력해 주세요.';
  if ([...q].length > max) return `질문은 최대 ${max}자까지 입력할 수 있습니다.`;
  return null;
}

const CAPTURE_MESSAGES = {
  NO_STREAM: '선택한 화면공유가 종료되었거나 아직 연결되지 않았습니다.',
  NO_FRAME: '공유 화면을 아직 받지 못했습니다. 화면이 보인 뒤 다시 시도해 주세요.',
  BLANK_FRAME: '공유 화면이 아직 검은 화면입니다. 화면이 보인 뒤 다시 시도해 주세요.',
  CANVAS_TAINTED: '브라우저 보안 정책 때문에 이 화면을 캡처할 수 없습니다.',
  ENCODE_FAILED: '이 브라우저에서 화면 이미지를 만들지 못했습니다.',
  TOO_LARGE: '화면 이미지를 분석 가능한 크기로 줄이지 못했습니다.',
};

/**
 * 캡처·네트워크·서버 오류 → { kind, code, message, retryable, retryAfterSeconds }.
 * kind: cancelled | capture | timeout | network | consent | gone | busy | client | server
 */
export function describeScreenAiError(err) {
  if (!err) return { kind: 'server', code: 'UNKNOWN', message: 'AI 화면 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.', retryable: true, retryAfterSeconds: null };
  if (err.name === 'ScreenCaptureError') {
    return { kind: 'capture', code: err.code, message: CAPTURE_MESSAGES[err.code] || err.message, retryable: err.code !== 'CANVAS_TAINTED' && err.code !== 'ENCODE_FAILED', retryAfterSeconds: null };
  }
  if (err.code === 'ERR_CANCELED' || err.name === 'CanceledError' || err.name === 'AbortError') {
    return { kind: 'cancelled', code: 'CANCELLED', message: '분석을 취소했습니다.', retryable: true, retryAfterSeconds: null };
  }
  const data = err.response?.data && typeof err.response.data === 'object' ? err.response.data : null;
  const status = Number(err.response?.status) || null;
  if (!status) {
    if (err.code === 'ECONNABORTED' || /timeout/i.test(String(err.message || ''))) {
      return { kind: 'timeout', code: 'CLIENT_TIMEOUT', message: 'AI 응답을 기다리는 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.', retryable: true, retryAfterSeconds: null };
    }
    return { kind: 'network', code: 'NETWORK', message: '네트워크 연결이 불안정합니다. 연결을 확인한 뒤 다시 시도해 주세요.', retryable: true, retryAfterSeconds: null };
  }
  const code = data?.code || `HTTP_${status}`;
  const serverMessage = typeof data?.message === 'string' && /[가-힣]/.test(data.message) ? data.message : null;
  const retryAfterSeconds = Number.isFinite(Number(data?.retryAfterSeconds)) ? Number(data.retryAfterSeconds)
    : Number(err.response?.headers?.['retry-after']) || null;
  const retryable = typeof data?.retryable === 'boolean' ? data.retryable : status >= 500 || status === 429;
  const kind = code === 'SHARER_CONSENT_REQUIRED' ? 'consent'
    : code === 'SCREEN_NOT_FOUND' || code === 'SCREEN_STREAM_MISMATCH' ? 'gone'
      : code === 'SCREEN_AI_TIMEOUT' || status === 504 ? 'timeout'
        : status === 429 || code === 'SCREEN_AI_OVERLOADED' ? 'busy'
          : status >= 500 ? 'server' : 'client';
  const fallback = status === 401 ? '로그인 정보가 만료되었습니다. 다시 로그인해 주세요.'
    : status === 403 ? '이 화면을 분석할 권한이 없습니다.'
      : status >= 500 ? 'AI 화면 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.'
        : '요청을 처리하지 못했습니다.';
  return { kind, code, message: serverMessage || fallback, retryable, retryAfterSeconds };
}

/** 대기 안내(경과 초 → 문구). ai07 은 대기열이 있어 혼잡하면 수십 초가 걸린다. */
export function pendingHint(phase, elapsedSec) {
  if (phase === 'capturing') return '현재 화면을 캡처하고 있어요';
  if (elapsedSec < 15) return 'AI가 화면을 분석하고 있어요';
  if (elapsedSec < 60) return '분석이 조금 오래 걸리고 있어요. AI 서버가 다른 요청을 처리 중일 수 있어요';
  return 'AI 서버가 혼잡해요. 계속 기다리거나 취소할 수 있어요';
}

export const formatBytes = (n) => (!Number.isFinite(n) ? '' : n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`);
