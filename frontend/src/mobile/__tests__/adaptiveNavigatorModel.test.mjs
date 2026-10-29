import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ALLOWED_MINUTES,
  ACTIVITY_LABEL,
  FACTOR_LABEL,
  changeText,
  createLatestGate,
  dueLabel,
  errorView,
  findItem,
  focusProgress,
  formatClock,
  formatDateKo,
  parseIsoDate,
  sameId,
  statusView,
  stepLabel,
  stepOptionLabel,
  sumActivityMinutes,
  warningText,
} from '../../utils/adaptiveNavigator.js';

// 웹 src/__tests__/adaptive-navigator.smoke.mjs 와 같은 검증. 앱도 같은 utils/adaptiveNavigator.js 를 쓴다.
// 실제 ai07 응답 원본(LLM-clean fastapi/docs/planner/적응형_학습엔진_실제요청응답예시.json)의 roadmap30·roadmap60·manual30 응답만 옮겨 둔다.
const examples = JSON.parse(readFileSync(new URL('./support/adaptiveNavigatorExamples.json', import.meta.url), 'utf8'));

test('15·30·60분만 허용', () => {
  assert.deepEqual(ALLOWED_MINUTES, [15, 30, 60]);
});

test('날짜 표기: 요일·오늘/내일, 잘못된 값은 그대로', () => {
  assert.equal(formatDateKo('2026-10-29'), '10월 29일(목)');
  assert.equal(formatDateKo('2026-10-28', '2026-10-28'), '오늘 · 10월 28일(수)');
  assert.equal(formatDateKo('2026-10-29', '2026-10-28'), '내일 · 10월 29일(목)');
  assert.equal(formatDateKo('2026-02-30'), '2026-02-30');
  assert.equal(parseIsoDate('9/18'), null);
});

test('마감 라벨: D-n / D-Day / n일 지남', () => {
  assert.equal(dueLabel('2026-10-31', '2026-10-28'), 'D-3');
  assert.equal(dueLabel('2026-10-28', '2026-10-28'), 'D-Day');
  assert.equal(dueLabel('2026-10-27', '2026-10-28'), '1일 지남');
  assert.equal(dueLabel(null, '2026-10-28'), null);
});

test('로드맵 단계 표시: 주차·일, 제목 접두사 제거, 상태', () => {
  const item = { id: 13, week: 1, day: 3, title: '[로드맵 1주차 3일] 합성곱 연산', status: 'IN_PROGRESS' };
  assert.equal(stepLabel(item), '1주차 3일');
  assert.equal(stepOptionLabel(item), '1주차 3일 · 합성곱 연산 (진행 중)');
  assert.equal(stepLabel({ scheduledDate: '2026-10-29' }), '10월 29일(목)');
});

test('id 비교는 숫자·문자열 무관', () => {
  assert.ok(sameId(13, '13'));
  assert.ok(!sameId(null, null));
  assert.equal(findItem([{ id: 9002, title: 'SQLD' }], '9002').title, 'SQLD');
});

test('status 별 화면 — READY/단계 완료/전체 완료/데이터 부족', () => {
  assert.equal(statusView({ mode: 'ROADMAP_COACH', result: { status: 'READY' } }).kind, 'ready');
  assert.equal(statusView({ mode: 'ROADMAP_COACH', result: { status: 'CURRENT_STEP_COMPLETED' } }).kind, 'stepDone');
  assert.match(statusView({ mode: 'ROADMAP_COACH', result: { status: 'ALL_COMPLETED' } }).title, /로드맵/);
  assert.match(statusView({ mode: 'MANUAL_NEXT', result: { status: 'ALL_COMPLETED' } }).title, /남은 학습/);
  const empty = statusView({ mode: 'MANUAL_NEXT', result: { status: 'INSUFFICIENT_DATA', message: '항목 없음' } });
  assert.equal(empty.kind, 'empty');
  assert.equal(empty.message, '항목 없음');
});

test('경고 문구 — 앞선 단계 미완료', () => {
  assert.match(warningText({ code: 'PREVIOUS_STEPS_INCOMPLETE', itemIds: [11, 12] }), /앞선 단계 2개/);
  assert.equal(warningText({ code: 'X', message: '서버 문구' }), '서버 문구');
});

test('반영 후보 문구 — 세션 / 예정일 변경', () => {
  assert.equal(
    changeText({ kind: 'ADD_STUDY_SESSION', date: '2026-10-29', minutes: 20 }, '2026-10-28'),
    '내일 · 10월 29일(목) · 20분 학습 세션'
  );
  assert.equal(
    changeText({ kind: 'RESCHEDULE_PLANNER', fromDate: '2026-10-25', toDate: '2026-10-29' }, '2026-10-28'),
    '예정일 10월 25일(일) → 내일 · 10월 29일(목)'
  );
});

test('오류 매핑 — 429/503 재시도 안내 + Retry-After, 504, 409, 403, 네트워크, 취소는 무시', () => {
  const busy = errorView({
    response: { status: 429, data: { error: { code: 'ADAPTIVE_BUSY', message: 'm', retryAfterSeconds: 4 } }, headers: {} },
  });
  assert.equal(busy.retryable, true);
  assert.equal(busy.retryAfter, 4);
  assert.equal(busy.title, '잠시 후 다시 시도해 주세요');
  assert.equal(errorView({ response: { status: 503, data: {}, headers: { 'retry-after': '7' } } }).retryAfter, 7);
  assert.equal(errorView({ response: { status: 504, data: {} } }).code, 'TIMEOUT');
  assert.equal(errorView({ code: 'ECONNABORTED' }).code, 'TIMEOUT');
  assert.equal(
    errorView({ response: { status: 409, data: { error: { code: 'ADAPTIVE_STALE', message: 's' } } } }).code,
    'ADAPTIVE_STALE'
  );
  assert.equal(errorView({ response: { status: 403, data: {} } }).retryable, false);
  assert.equal(errorView({ message: 'Network Error' }).code, 'NETWORK');
  assert.equal(errorView({ code: 'ERR_CANCELED', name: 'CanceledError' }), null);
});

test('최신 요청 게이트 — 늦게 온 이전 응답은 버리고, 이전 요청은 취소된다', async () => {
  const gate = createLatestGate();
  const applied = [];
  const fakeFetch = (minutes, delay) => new Promise((resolve) => setTimeout(() => resolve({ minutes }), delay));
  const run = async (minutes, delay) => {
    const { seq, signal } = gate.next();
    const res = await fakeFetch(minutes, delay);
    if (gate.isLatest(seq)) applied.push(res.minutes);
    return signal;
  };
  // 15 → 30 → 60 을 연달아 누르고, 응답은 60 이 먼저, 15 가 마지막에 도착한다.
  const [sig15, sig30, sig60] = await Promise.all([run(15, 60), run(30, 40), run(60, 5)]);
  assert.deepEqual(applied, [60], '오래된 응답(15·30)이 최신(60)을 덮지 않는다');
  assert.equal(sig15.aborted, true);
  assert.equal(sig30.aborted, true);
  assert.equal(sig60.aborted, false);
  gate.abort();
  assert.equal(sig60.aborted, true, '화면 이탈 시 진행 중 요청 취소');
});

test('실제 ai07 응답 원본 — 활동 시간 합 = 선택 시간, 활동 종류·점수 요소 라벨 존재', () => {
  for (const key of ['roadmap30', 'roadmap60', 'manual30']) {
    const response = examples[key];
    assert.equal(sumActivityMinutes(response.recommendation.activities), response.availableMinutes, key);
    for (const activity of response.recommendation.activities) assert.ok(ACTIVITY_LABEL[activity.type], `${key} ${activity.type}`);
  }
  for (const b of examples.manual30.recommendation.scoreBreakdown) assert.ok(FACTOR_LABEL[b.factor], b.factor);
  for (const alt of examples.manual30.alternatives) {
    for (const b of alt.scoreBreakdown) assert.ok(FACTOR_LABEL[b.factor], b.factor);
  }
});

test('집중 모드 진행 — 경과 시간에 맞는 활동, 끝나면 done', () => {
  const activities = examples.roadmap30.recommendation.activities; // 10 / 15 / 5
  assert.equal(focusProgress(activities, 30, 0).index, 0);
  assert.equal(focusProgress(activities, 30, 10 * 60 + 1).index, 1);
  assert.equal(focusProgress(activities, 30, 26 * 60).index, 2);
  const end = focusProgress(activities, 30, 31 * 60);
  assert.equal(end.done, true);
  assert.equal(end.remainingSec, 0);
  assert.equal(formatClock(125), '02:05');
});
