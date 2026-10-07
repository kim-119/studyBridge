// 백엔드/axios 원본 오류 → 사용자 문구 단일 지점.
//  · "Request failed with status code 401", "Group study not found with ID: 106" 같은 개발자용 문자열이
//    showAlert/alert 로 그대로 노출되지 않게 한다. 원본은 항상 console.error 로 남긴다(개발자 진단용).
//  · 서버가 한국어로 내려준 사용자용 메시지(GlobalExceptionHandler 의 400/409 등)는 그대로 쓴다.
//  · 순수 함수(브라우저 API 의존 없음) — node:test 로 검증한다.

export const USER_FACING_MESSAGES = Object.freeze({
  UNAUTHORIZED: '로그인 정보가 만료되었습니다. 다시 로그인해주세요.',
  FORBIDDEN: '이 작업을 수행할 권한이 없습니다. 스터디 멤버/방장만 이용할 수 있습니다.',
  GROUP_NOT_FOUND: '스터디 정보를 찾을 수 없습니다. 스터디가 해체되었거나 더 이상 접근할 수 없습니다.',
  NOT_FOUND: '요청한 정보를 찾을 수 없습니다. 새로고침 후 다시 시도해주세요.',
  PAYLOAD_TOO_LARGE: '파일 크기가 허용 한도를 초과했습니다. 더 작은 파일로 다시 시도해주세요.',
  UNSUPPORTED_MEDIA_TYPE: '지원하지 않는 파일 형식입니다. PDF 파일로 다시 시도해주세요.',
  NETWORK: '네트워크 연결이 불안정하거나 서버 응답이 지연되고 있습니다. 연결 상태를 확인한 뒤 다시 시도해주세요.',
  SERVER: '서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.',
  GENERIC: '요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.',
});

const GROUP_NOT_FOUND_RE = /group\s*study\s*not\s*found|스터디(를|\s*정보를)?\s*찾을\s*수\s*없/i;
const RAW_AXIOS_RE = /request failed with status code|network error|timeout of \d+ms|ECONNABORTED|ERR_NETWORK/i;
const HANGUL_RE = /[가-힣]/;

// axios 오류 / fetch Response / {status,message} 평면 객체(uploadProfileImage 의 catch 가 던지는 형태) 모두 수용.
export const extractStatus = (err) => {
  if (!err || typeof err !== 'object') return null;
  const candidates = [err.response?.status, err.status, err.statusCode];
  for (const c of candidates) {
    const n = Number(c);
    if (Number.isInteger(n) && n >= 100 && n <= 599) return n;
  }
  return null;
};

export const extractServerMessage = (err) => {
  if (!err || typeof err !== 'object') return null;
  const data = err.response?.data ?? err.data ?? null;
  if (data && typeof data === 'object' && typeof data.message === 'string') return data.message;
  if (typeof data === 'string' && data.trim()) return data;
  // axios 가 아닌 평면 {message} 객체(이미 response.data 가 풀린 상태)
  if (!err.response && typeof err.message === 'string' && !(err instanceof Error)) return err.message;
  return null;
};

// 응답 자체가 없음(= 네트워크 끊김/CORS/타임아웃). axios 는 timeout 시 code=ECONNABORTED(또는 ETIMEDOUT), 응답 없음.
export const isNetworkError = (err) => {
  if (!err || typeof err !== 'object') return false;
  if (extractStatus(err) != null) return false;
  if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT' || err.code === 'ERR_NETWORK') return true;
  if (err.request && !err.response) return true;
  return typeof err.message === 'string' && /network error|timeout/i.test(err.message);
};

export const isGroupNotFoundError = (err) => {
  if (extractStatus(err) !== 404) return false;
  const msg = extractServerMessage(err) || '';
  return GROUP_NOT_FOUND_RE.test(msg);
};

// 서버 메시지를 사용자에게 그대로 보여줘도 되는가: 한국어 + 짧음 + axios/스택 문자열 아님.
const isUserSafeServerMessage = (msg) => (
  typeof msg === 'string' && msg.length > 0 && msg.length <= 200 && HANGUL_RE.test(msg) && !RAW_AXIOS_RE.test(msg)
);

/**
 * @param {unknown} err 원본 오류(axios error / Error / {status,message})
 * @param {{ fallback?: string, context?: 'group'|'upload'|string, log?: boolean }} [opts]
 * @returns {{ message: string, status: number|null, code: string, groupNotFound: boolean, network: boolean }}
 */
export const toUserFacingError = (err, opts = {}) => {
  const { fallback = USER_FACING_MESSAGES.GENERIC, context = '', log = true } = opts;
  if (log) {
    // 개발자용 원본. (토큰 등 민감값은 axios error 에 없다 — config.headers 는 찍지 않는다.)
    try {
      // eslint-disable-next-line no-console
      console.error('[userFacingError] original error', {
        context,
        message: err?.message,
        code: err?.code,
        status: extractStatus(err),
        url: err?.config?.url,
        method: err?.config?.method,
        data: err?.response?.data,
      });
    } catch { /* console 이 없는 환경 */ }
  }

  const status = extractStatus(err);
  const serverMessage = extractServerMessage(err);
  const base = { status, groupNotFound: false, network: false };

  if (isNetworkError(err)) return { ...base, network: true, code: 'NETWORK', message: USER_FACING_MESSAGES.NETWORK };
  if (status === 401) return { ...base, code: 'UNAUTHORIZED', message: USER_FACING_MESSAGES.UNAUTHORIZED };
  if (status === 403) return { ...base, code: 'FORBIDDEN', message: USER_FACING_MESSAGES.FORBIDDEN };
  if (status === 404) {
    if (context === 'group' || isGroupNotFoundError(err)) {
      return { ...base, groupNotFound: true, code: 'GROUP_NOT_FOUND', message: USER_FACING_MESSAGES.GROUP_NOT_FOUND };
    }
    return { ...base, code: 'NOT_FOUND', message: USER_FACING_MESSAGES.NOT_FOUND };
  }
  if (status === 413) return { ...base, code: 'PAYLOAD_TOO_LARGE', message: USER_FACING_MESSAGES.PAYLOAD_TOO_LARGE };
  if (status === 415) return { ...base, code: 'UNSUPPORTED_MEDIA_TYPE', message: USER_FACING_MESSAGES.UNSUPPORTED_MEDIA_TYPE };
  if (status != null && status >= 500) return { ...base, code: 'SERVER', message: USER_FACING_MESSAGES.SERVER };
  // 400/409/422 등: 서버가 의도적으로 내려준 한국어 안내(검증 실패, 진행 중 세션 등)는 그대로 보여준다.
  if (isUserSafeServerMessage(serverMessage)) return { ...base, code: 'SERVER_MESSAGE', message: serverMessage };
  return { ...base, code: 'GENERIC', message: fallback || USER_FACING_MESSAGES.GENERIC };
};

// showAlert/alert 에 바로 넣는 문자열 버전.
export const userFacingMessage = (err, fallback, opts = {}) => toUserFacingError(err, { ...opts, fallback }).message;
