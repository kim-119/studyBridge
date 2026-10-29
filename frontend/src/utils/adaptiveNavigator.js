// AI 학습 내비게이터(적응형 학습 엔진) 화면 도우미 — 순수 함수만 둔다(React/axios 의존 없음, node 스모크 테스트 대상).
// 계약: fastapi/docs/planner/적응형_학습엔진_API_연동계약.md (adaptive-planner.v1), Spring POST /api/planners/{id}/adaptive.

export const ALLOWED_MINUTES = [15, 30, 60];

export const ACTIVITY_LABEL = {
  CONCEPT: '핵심 개념',
  UNDERSTAND: '원리 이해',
  EXAMPLE: '예제 풀이',
  PRACTICE: '직접 적용',
  CHECK: '확인 문제',
  REVIEW: '핵심 복습',
  REMEDIATION: '오답 개념 복습',
  WRONG_ANSWER_REVIEW: '최근 오답 다시 풀기',
  PREP: '목표 확인',
  WORK: '집중 학습',
  WRAP: '정리·기록',
};

export const FACTOR_LABEL = {
  PRIORITY: '사용자 우선순위',
  PRIORITY_UNSET: '우선순위 미지정',
  DUE_SOON: '마감 임박',
  OVERDUE: '마감 경과',
  SCHEDULE_PASSED: '예정일 경과',
  SCHEDULED_TODAY: '오늘 예정',
  IN_PROGRESS: '진행 중',
  FITS_AVAILABLE_TIME: '이번 시간에 끝낼 수 있음',
  USER_ORDER: '사용자 순서',
};

export const STEP_STATUS_LABEL = { COMPLETED: '완료', IN_PROGRESS: '진행 중', PENDING: '예정' };

const DOW = ['일', '월', '화', '수', '목', '금', '토'];

/** "YYYY-MM-DD" → Date(로컬 자정). 형식이 아니면 null. */
export function parseIsoDate(iso) {
  if (typeof iso !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d ? dt : null;
}

/** "2026-10-29" → "10월 29일(목)". today(ISO)가 주어지면 오늘/내일을 앞에 붙인다. */
export function formatDateKo(iso, today) {
  const dt = parseIsoDate(iso);
  if (!dt) return iso || '';
  const base = `${dt.getMonth() + 1}월 ${dt.getDate()}일(${DOW[dt.getDay()]})`;
  const t = parseIsoDate(today);
  if (!t) return base;
  const diff = Math.round((dt - t) / 86400000);
  if (diff === 0) return `오늘 · ${base}`;
  if (diff === 1) return `내일 · ${base}`;
  return base;
}

/** 마감까지 남은 날 → "D-3" / "D-Day" / "3일 지남". */
export function dueLabel(dueIso, todayIso) {
  const d = parseIsoDate(dueIso);
  const t = parseIsoDate(todayIso);
  if (!d || !t) return null;
  const diff = Math.round((d - t) / 86400000);
  if (diff === 0) return 'D-Day';
  return diff > 0 ? `D-${diff}` : `${-diff}일 지남`;
}

/** 로드맵 단계 표시 이름: "1주차 3일" 우선, 없으면 날짜. */
export function stepLabel(item) {
  if (!item) return '';
  if (item.week != null && item.day != null) return `${item.week}주차 ${item.day}일`;
  if (item.scheduledDate) return formatDateKo(item.scheduledDate);
  return `${item.orderIndex ?? ''}단계`;
}

/** 단계 선택 목록 한 줄. */
export function stepOptionLabel(item) {
  const title = String(item?.title || '').replace(/^\[\s*로드맵\s*\d+\s*주차\s*\d+\s*일\s*\]\s*/, '');
  const st = STEP_STATUS_LABEL[item?.status] || '';
  return `${stepLabel(item)} · ${title}${st ? ` (${st})` : ''}`;
}

export function sumActivityMinutes(activities) {
  return (Array.isArray(activities) ? activities : []).reduce((s, a) => s + (Number(a?.minutes) > 0 ? Number(a.minutes) : 0), 0);
}

/** id 비교(서버는 숫자, 화면은 문자열일 수 있다). */
export function sameId(a, b) {
  return a != null && b != null && String(a) === String(b);
}

export function findItem(items, id) {
  return (Array.isArray(items) ? items : []).find((i) => sameId(i?.id, id)) || null;
}

/**
 * 응답 status 별 화면. READY 가 아니면 빈 상태 카드를 그린다.
 *  kind: ready | empty | allDone | stepDone
 */
export function statusView(data) {
  const r = data?.result || {};
  const roadmap = data?.mode === 'ROADMAP_COACH';
  switch (r.status) {
    case 'READY':
      return { kind: 'ready' };
    case 'CURRENT_STEP_COMPLETED':
      return { kind: 'stepDone', title: '이 단계는 이미 완료했어요', message: r.message || '코칭 받을 단계를 골라 주세요.' };
    case 'ALL_COMPLETED':
      return {
        kind: 'allDone',
        title: roadmap ? '로드맵의 모든 단계를 완료했어요' : '남은 학습이 없어요',
        message: r.message || (roadmap ? '수고했어요! 새 로드맵을 만들거나 복습을 이어가 보세요.' : '등록된 학습을 모두 끝냈어요.'),
      };
    case 'INSUFFICIENT_DATA':
    default:
      return {
        kind: 'empty',
        title: roadmap ? '코칭할 로드맵 단계가 없어요' : '추천할 학습이 없어요',
        message: r.message || (roadmap
          ? '로드맵 플래너가 연결되어 있지 않습니다.'
          : '최근 2주~앞으로 2달 안의 수기 플래너가 없습니다. 플래너를 작성하면 무엇부터 할지 추천해 드려요.'),
      };
  }
}

/** 경고 코드 → 사용자 문구. 알 수 없는 코드는 서버 message 를 쓴다. */
export function warningText(w) {
  if (!w) return '';
  const n = Array.isArray(w.itemIds) ? w.itemIds.length : 0;
  if (w.code === 'PREVIOUS_STEPS_INCOMPLETE') return n > 0 ? `앞선 단계 ${n}개가 아직 완료되지 않았어요. 순서는 그대로 두고 현재 단계를 코칭합니다.` : '앞선 단계 중 미완료가 있어요.';
  if (w.code === 'AVAILABLE_MINUTES_DEFAULTED') return '학습 시간을 30분으로 구성했어요.';
  return w.message || '';
}

/** 반영 후보 한 줄 설명. */
export function changeText(c, todayIso) {
  if (!c) return '';
  if (c.kind === 'RESCHEDULE_PLANNER') {
    return `예정일 ${formatDateKo(c.fromDate)} → ${formatDateKo(c.toDate, todayIso)}`;
  }
  return `${formatDateKo(c.date, todayIso)} · ${c.minutes}분 학습 세션`;
}

/** axios 오류 → 화면 오류. 취소(요청 교체)는 null. */
export function errorView(e) {
  if (!e) return null;
  if (e.code === 'ERR_CANCELED' || e.name === 'CanceledError' || e.name === 'AbortError') return null;
  const status = e.response?.status;
  const err = e.response?.data?.error || {};
  const retryAfter = Number(err.retryAfterSeconds || e.response?.headers?.['retry-after']) || null;
  if (status === 429 || status === 503) {
    return { status, code: err.code || 'BUSY', retryable: true, retryAfter, title: '잠시 후 다시 시도해 주세요',
      message: err.message || 'AI 서버가 혼잡합니다.' };
  }
  if (status === 504 || e.code === 'ECONNABORTED') {
    return { status: status || 504, code: err.code || 'TIMEOUT', retryable: true, retryAfter, title: '응답이 늦어지고 있어요',
      message: err.message || 'AI 응답 시간이 초과되었습니다. 다시 시도해 주세요.' };
  }
  if (status === 403 || status === 404) {
    return { status, code: err.code || 'FORBIDDEN', retryable: false, title: '이 플래너를 볼 수 없어요',
      message: err.message || '본인의 플래너만 이용할 수 있습니다.' };
  }
  if (status === 409) {
    return { status, code: err.code || 'CONFLICT', retryable: true, title: '추천을 다시 계산해야 해요',
      message: err.message || '추천 이후 플래너가 바뀌었습니다.' };
  }
  if (!e.response) {
    return { status: 0, code: 'NETWORK', retryable: true, title: '연결이 끊겼어요', message: '네트워크 상태를 확인한 뒤 다시 시도해 주세요.' };
  }
  return { status, code: err.code || 'ERROR', retryable: err.retryable !== false, retryAfter,
    title: 'AI 학습 내비게이터를 불러오지 못했어요', message: err.message || '잠시 후 다시 시도해 주세요.' };
}

/**
 * 최신 요청만 반영하는 게이트. next() 가 이전 요청을 취소(AbortController)하고 시퀀스를 올린다.
 * 응답을 적용하기 전에 isLatest(seq) 로 한 번 더 확인한다(취소가 늦게 도착해도 오래된 응답이 덮지 않는다).
 */
export function createLatestGate() {
  let seq = 0;
  let controller = null;
  return {
    next() {
      if (controller) controller.abort();
      controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      seq += 1;
      return { seq, signal: controller ? controller.signal : undefined };
    },
    isLatest(s) {
      return s === seq;
    },
    abort() {
      if (controller) controller.abort();
      controller = null;
      seq += 1;
    },
  };
}

/**
 * 학습 시작(집중 모드) 진행 계산. 활동을 분 단위로 이어 붙여 지금 몇 번째 활동인지 낸다.
 * elapsedSec 은 일시정지를 뺀 경과 초.
 */
export function focusProgress(activities, totalMinutes, elapsedSec) {
  const list = Array.isArray(activities) ? activities : [];
  const totalSec = Math.max(1, (Number(totalMinutes) || sumActivityMinutes(list)) * 60);
  const e = Math.max(0, Math.min(totalSec, Number(elapsedSec) || 0));
  let acc = 0;
  let index = list.length ? list.length - 1 : -1;
  for (let i = 0; i < list.length; i += 1) {
    acc += Math.max(0, Number(list[i]?.minutes) || 0) * 60;
    if (e < acc) { index = i; break; }
  }
  return { index, remainingSec: totalSec - e, done: e >= totalSec, percent: Math.round((e / totalSec) * 100) };
}

export function formatClock(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

/** 브라우저 저장소 안전 접근(사생활 모드·차단 시 조용히 실패). */
export const safeStorage = {
  get(kind, key) {
    try { const s = typeof window !== 'undefined' ? window[kind] : null; return s ? s.getItem(key) : null; } catch { return null; }
  },
  set(kind, key, value) {
    try { const s = typeof window !== 'undefined' ? window[kind] : null; if (s) s.setItem(key, value); } catch { /* 무시 */ }
  },
  remove(kind, key) {
    try { const s = typeof window !== 'undefined' ? window[kind] : null; if (s) s.removeItem(key); } catch { /* 무시 */ }
  },
};
