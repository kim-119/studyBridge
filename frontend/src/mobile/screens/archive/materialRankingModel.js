// PDF(자료)별 · 퀴즈별 랭킹 모델. 화면과 분리된 순수 함수만 둔다(node --test 로 검증).
//
// 서버 계약(EC2 LLM-clean MaterialController#getQuizRanking, 초안은 frontend/docs/material-quiz-ranking-contract.md)
//   GET /api/materials/{materialId}/quiz/{quizId}/ranking?limit=1..100
//   정책 BEST_SCORE: 사용자별 최고점 1건, 경쟁 순위(1,1,3), 같은 점수는 먼저 달성한 사람이 위. 앱은 서버 순서를 바꾸지 않는다.
// 점수·순위는 서버가 검증·결정한다. 앱은 점수를 계산하거나 제출하지 않고, 응답을 표시용으로만 정리한다.

// 서버 랭킹 API 가 배포되기 전에는 탭 자체를 노출하지 않는다(미완성 기능을 정상 기능처럼 릴리스하지 않기 위함).
// 서버 배포 후 모바일 빌드 환경변수 VITE_FEATURE_MATERIAL_RANKING=true 로 켠다.
// Vite 는 `import.meta.env.VITE_*` 정확한 표기만 정적 치환한다(옵셔널 체이닝 금지). node --test 에서는 env 가 없어 false.
function readRankingFlag() {
  try {
    return import.meta.env.VITE_FEATURE_MATERIAL_RANKING === 'true';
  } catch {
    return false;
  }
}

export const MATERIAL_RANKING_ENABLED = readRankingFlag();

const BASE_DOCUMENT_TABS = [
  { key: 'summary', label: '요약' },
  { key: 'quiz', label: '퀴즈' },
  { key: 'roadmap', label: '로드맵' },
  { key: 'memo', label: '메모' },
  { key: 'question', label: 'AI 질문' },
];

export const RANKING_TAB = { key: 'ranking', label: '랭킹' };

/** 랭킹 탭은 퀴즈 바로 오른쪽에 둔다. */
export function documentTabs({ rankingEnabled = MATERIAL_RANKING_ENABLED } = {}) {
  if (!rankingEnabled) return BASE_DOCUMENT_TABS;
  const quizIndex = BASE_DOCUMENT_TABS.findIndex((tab) => tab.key === 'quiz');
  return [...BASE_DOCUMENT_TABS.slice(0, quizIndex + 1), RANKING_TAB, ...BASE_DOCUMENT_TABS.slice(quizIndex + 1)];
}

export const RANKING_STATE = {
  UNAVAILABLE: 'unavailable', // 서버에 랭킹 API 가 아직 없음(404 without code / 405 / 501)
  BAD_REQUEST: 'bad-request', // 400 (INVALID_LIMIT 등)
  UNAUTHORIZED: 'unauthorized', // 401 로그인 필요
  FORBIDDEN: 'forbidden', // 403 비공개 자료 등 열람 권한 없음
  QUIZ_NOT_FOUND: 'quiz-not-found', // 404 QUIZ_NOT_FOUND 퀴즈가 없거나 삭제됨
  NOT_FOUND: 'not-found', // 404 MATERIAL_NOT_FOUND 등 자료가 없거나 삭제됨
  RATE_LIMITED: 'rate-limited', // 429 요청 제한(재시도 가능)
  SERVER_ERROR: 'server-error', // 5xx (503 RANKING_UNAVAILABLE 포함, 재시도 가능)
  ERROR: 'error', // 네트워크 오류 등(재시도 가능)
};

/** 다시 시도하면 달라질 수 있는 상태. 나머지는 안내만 한다. */
export const RETRYABLE_RANKING_STATES = new Set([RANKING_STATE.RATE_LIMITED, RANKING_STATE.SERVER_ERROR, RANKING_STATE.ERROR]);

// 계약상 랭킹 API 의 비즈니스 404 는 반드시 code 를 담는다. code 없는 404 는 라우트 자체가 없는 것으로 본다.
const NOT_FOUND_CODES = new Set(['MATERIAL_NOT_FOUND', 'QUIZ_NOT_FOUND']);

export function classifyRankingError(error) {
  const status = error?.status || error?.response?.status;
  const code = error?.response?.data?.code;
  if (status === 404) {
    if (code === 'QUIZ_NOT_FOUND') return RANKING_STATE.QUIZ_NOT_FOUND;
    return NOT_FOUND_CODES.has(code) ? RANKING_STATE.NOT_FOUND : RANKING_STATE.UNAVAILABLE;
  }
  if (status === 405 || status === 501) return RANKING_STATE.UNAVAILABLE;
  if (status === 400) return RANKING_STATE.BAD_REQUEST;
  if (status === 401) return RANKING_STATE.UNAUTHORIZED;
  if (status === 403) return RANKING_STATE.FORBIDDEN;
  if (status === 429) return RANKING_STATE.RATE_LIMITED;
  if (status >= 500) return RANKING_STATE.SERVER_ERROR;
  return RANKING_STATE.ERROR;
}

/** 기존 퀴즈 목록 API(GET /quiz) 오류. 이미 배포된 경로라 404 는 '미배포' 가 아니라 자료 없음/삭제다. */
export function classifyQuizListError(error) {
  const status = error?.status || error?.response?.status;
  if (status === 404) return RANKING_STATE.NOT_FOUND;
  if (status === 401) return RANKING_STATE.UNAUTHORIZED;
  if (status === 403) return RANKING_STATE.FORBIDDEN;
  return RANKING_STATE.ERROR;
}

export const RANKING_STATE_MESSAGE = {
  [RANKING_STATE.UNAVAILABLE]: '랭킹 기능은 서버 준비 중입니다. 퀴즈 응시와 채점은 그대로 이용할 수 있습니다.',
  [RANKING_STATE.BAD_REQUEST]: '랭킹 요청이 올바르지 않습니다. 화면을 닫았다가 다시 열어주세요.',
  [RANKING_STATE.UNAUTHORIZED]: '로그인이 필요합니다. 다시 로그인한 뒤 랭킹을 확인해주세요.',
  [RANKING_STATE.FORBIDDEN]: '이 자료의 랭킹을 볼 권한이 없습니다.',
  [RANKING_STATE.QUIZ_NOT_FOUND]: '퀴즈를 찾을 수 없습니다. 삭제되었을 수 있습니다.',
  [RANKING_STATE.NOT_FOUND]: '자료 또는 퀴즈를 찾을 수 없습니다. 삭제되었을 수 있습니다.',
  [RANKING_STATE.RATE_LIMITED]: '요청이 많아 잠시 제한되었습니다. 잠시 후 다시 시도해주세요.',
  [RANKING_STATE.SERVER_ERROR]: '랭킹 서버에 일시적인 문제가 있습니다. 잠시 후 다시 시도해주세요.',
};

function toCount(value) {
  return Number.isFinite(value) && value >= 0 ? Math.trunc(value) : null;
}

/** 서버 rank 가 없을 때만 같은 점수 = 같은 순위(1,1,3) 로 채운다. 서버가 준 rank 는 그대로 쓴다. */
function withCompetitionRanks(entries) {
  let previousScore = null;
  let previousRank = 0;
  return entries.map((entry, index) => {
    if (entry.rank !== null) return entry;
    const rank = entry.score === previousScore ? previousRank : index + 1;
    previousScore = entry.score;
    previousRank = rank;
    return { ...entry, rank };
  });
}

function toEntry(raw) {
  const rank = toCount(raw?.rank);
  return {
    rank: rank && rank > 0 ? rank : null,
    nickname: typeof raw?.nickname === 'string' && raw.nickname.trim() ? raw.nickname.trim() : '익명',
    score: Number.isFinite(raw?.score) ? raw.score : 0,
    correctCount: toCount(raw?.correctCount),
    totalQuestions: toCount(raw?.totalQuestions),
    attemptCount: toCount(raw?.attemptCount),
    isMe: raw?.isMe === true,
  };
}

/**
 * 응답을 표시용으로 정리한다. 요청한 materialId/quizId 와 다른 응답은 다른 PDF·퀴즈 점수가 섞이는 것이므로 거부한다.
 * userId 등 식별자는 버리고 nickname · 점수 · isMe 만 남긴다.
 */
export function normalizeRanking(response, { materialId, quizId }) {
  if (!response || typeof response !== 'object') throw new Error('랭킹 응답 형식이 올바르지 않습니다.');
  if (String(response.materialId) !== String(materialId) || String(response.quizId) !== String(quizId)) {
    throw new Error('요청한 자료·퀴즈와 다른 랭킹 응답입니다.');
  }

  const sorted = (Array.isArray(response.entries) ? response.entries : [])
    .map(toEntry)
    .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity) || b.score - a.score);
  const entries = withCompetitionRanks(sorted);
  const meInList = entries.find((entry) => entry.isMe) || null;
  const me = meInList || (response.me ? { ...toEntry(response.me), isMe: true } : null);

  return {
    materialId: response.materialId,
    quizId: response.quizId,
    totalParticipants: toCount(response.totalParticipants) ?? entries.length,
    entries,
    me,
    meOutsideList: Boolean(me && !meInList),
  };
}

export function medalOf(rank) {
  return rank >= 1 && rank <= 3 ? rank : null;
}

/** 같은 순위가 둘 이상이면 동점 표시. */
export function tiedRanks(entries) {
  const counts = new Map();
  entries.forEach((entry) => counts.set(entry.rank, (counts.get(entry.rank) || 0) + 1));
  return new Set([...counts].filter(([, count]) => count > 1).map(([rank]) => rank));
}

/** 정답률(%) — 서버가 준 최고점 달성 시 정답 수/채점 문항 수로 표시만 한다(순위 계산에 쓰지 않음). */
export function describeAccuracy(entry) {
  if (entry.correctCount === null || !entry.totalQuestions) return null;
  return `정답률 ${Math.round((entry.correctCount / entry.totalQuestions) * 100)}%`;
}

export function describeCorrect(entry) {
  if (entry.correctCount === null || entry.totalQuestions === null) return null;
  return `${entry.correctCount}/${entry.totalQuestions} 정답`;
}
