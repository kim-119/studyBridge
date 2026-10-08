// 오답노트 문제 풀이(다시 풀기 / 유사문제) 문항별 상태 머신 — 순수 함수(React 무관, node:test 로 검증).
//
//  READY ──PICK──▶ ANSWERING ──SUBMIT──▶ SUBMITTED ──GRADE──▶ GRADED ──RETRY──▶ READY(attempt+1)
//
//  · 문항 id 별로 독립된 상태를 갖는다(다른 문항의 다시 풀기가 서로 영향을 주지 않는다).
//  · RETRY 는 선택/채점/결과를 모두 비우고 같은 문항을 새 시도로 되돌린다. 문항 내용은 상태에 두지 않으므로 변하지 않는다.
//  · 이전 시도는 history 에 남긴다(화면 표시용). 서버 기록(재풀이 1회 결과)은 여기서 건드리지 않는다.
//  · SEED 는 서버에 이미 기록된 결과로 "처음 한 번만" 채점 상태를 복원한다. 이미 로컬 상태가 있는 문항(다시 풀기 포함)은
//    덮어쓰지 않는다 — 서버 응답 재수신 때 다시 풀기 상태가 채점 상태로 되돌아가던 원인을 막는다.

export const ATTEMPT_STATUS = Object.freeze({
  READY: 'READY',
  ANSWERING: 'ANSWERING',
  SUBMITTED: 'SUBMITTED',
  GRADED: 'GRADED',
});

export function createAttempt() {
  return { status: ATTEMPT_STATUS.READY, picked: null, correct: null, attempt: 1, history: [], seeded: false };
}

export const attemptOf = (map, id) => map?.[id] ?? createAttempt();
export const canPick = (a) => a.status === ATTEMPT_STATUS.READY || a.status === ATTEMPT_STATUS.ANSWERING;
export const canSubmit = (a) => a.status === ATTEMPT_STATUS.ANSWERING && a.picked != null;
export const isGraded = (a) => a.status === ATTEMPT_STATUS.GRADED;
export const isSubmittedOrGraded = (a) => a.status === ATTEMPT_STATUS.SUBMITTED || a.status === ATTEMPT_STATUS.GRADED;

// 한 문항의 전이. 허용되지 않는 전이는 상태를 그대로 돌려준다(화면에서 버튼이 숨겨져도 방어).
export function transition(a, action) {
  const cur = a ?? createAttempt();
  switch (action.type) {
    case 'PICK':
      if (!canPick(cur)) return cur;
      return { ...cur, status: ATTEMPT_STATUS.ANSWERING, picked: action.choice };
    case 'SUBMIT':
      if (!canSubmit(cur)) return cur;
      return { ...cur, status: ATTEMPT_STATUS.SUBMITTED };
    case 'GRADE':
      if (cur.status !== ATTEMPT_STATUS.SUBMITTED) return cur;
      return { ...cur, status: ATTEMPT_STATUS.GRADED, correct: Boolean(action.correct) };
    case 'RETRY': {
      if (!isGraded(cur)) return cur;
      const history = [...cur.history, { attempt: cur.attempt, picked: cur.picked, correct: cur.correct }];
      return { ...createAttempt(), attempt: cur.attempt + 1, history };
    }
    case 'SEED': {
      if (a) return cur; // 로컬 상태가 있으면 서버 복원으로 덮지 않는다.
      return { ...createAttempt(), status: ATTEMPT_STATUS.GRADED, picked: action.picked ?? null, correct: action.correct == null ? null : Boolean(action.correct), seeded: true };
    }
    default:
      return cur;
  }
}

// 문항 id → 상태 맵 리듀서(useReducer 용). RESET_ALL 은 새 문제 세트 생성 시 전체 초기화.
export function attemptMapReducer(map, action) {
  if (action.type === 'RESET_ALL') return {};
  const prev = map[action.id];
  if (!prev && !['PICK', 'SEED'].includes(action.type)) return map;
  const next = transition(prev, action);
  if (next === prev) return map;
  return { ...map, [action.id]: next };
}

// 제출+채점을 한 번에(채점이 동기적인 화면용). 상태 머신상 SUBMITTED 를 거쳐 GRADED 로 간다.
export function submitAndGrade(map, id, correct) {
  const afterSubmit = attemptMapReducer(map, { type: 'SUBMIT', id });
  if (afterSubmit === map) return map;
  return attemptMapReducer(afterSubmit, { type: 'GRADE', id, correct });
}
