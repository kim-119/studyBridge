// AI 학습 내비게이터 순수 로직 smoke test (의존성 0, 러너 불필요)
//   실행:  node src/__tests__/adaptive-navigator.smoke.mjs   (frontend 디렉토리에서)
//   대상:  src/utils/adaptiveNavigator.js 를 그대로 import 한다(거울 복제 아님).
//   범위:  날짜·마감 표기, status 별 빈 화면, 오류 매핑(429/503/504/409/취소), 최신 요청 게이트(오래된 응답 무시),
//          집중 모드 진행 계산, 실제 ai07 응답 원본(fastapi/docs/planner)의 활동 시간 합.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {
  ALLOWED_MINUTES, ACTIVITY_LABEL, FACTOR_LABEL, changeText, createLatestGate, dueLabel, errorView, findItem, focusProgress,
  formatClock, formatDateKo, parseIsoDate, sameId, statusView, stepLabel, stepOptionLabel, sumActivityMinutes, warningText,
} from '../utils/adaptiveNavigator.js';

let passed = 0;
const test = async (name, fn) => {
  try { await fn(); passed += 1; console.log(`  ✓ ${name}`); } catch (e) { console.error(`  ✗ ${name}\n    ${e.stack || e}`); process.exitCode = 1; }
};

const here = path.dirname(fileURLToPath(import.meta.url));
const examples = JSON.parse(readFileSync(path.resolve(here, '../../../fastapi/docs/planner/적응형_학습엔진_실제요청응답예시.json'), 'utf8'));

await test('15·30·60분만 허용', () => assert.deepEqual(ALLOWED_MINUTES, [15, 30, 60]));

await test('날짜 표기: 요일·오늘/내일, 잘못된 값은 그대로', () => {
  assert.equal(formatDateKo('2026-10-29'), '10월 29일(목)');
  assert.equal(formatDateKo('2026-10-28', '2026-10-28'), '오늘 · 10월 28일(수)');
  assert.equal(formatDateKo('2026-10-29', '2026-10-28'), '내일 · 10월 29일(목)');
  assert.equal(formatDateKo('2026-02-30'), '2026-02-30');
  assert.equal(parseIsoDate('9/18'), null);
});

await test('마감 라벨: D-n / D-Day / n일 지남', () => {
  assert.equal(dueLabel('2026-10-31', '2026-10-28'), 'D-3');
  assert.equal(dueLabel('2026-10-28', '2026-10-28'), 'D-Day');
  assert.equal(dueLabel('2026-10-27', '2026-10-28'), '1일 지남');
  assert.equal(dueLabel(null, '2026-10-28'), null);
});

await test('로드맵 단계 표시: 주차·일, 제목 접두사 제거, 상태', () => {
  const it = { id: 13, week: 1, day: 3, title: '[로드맵 1주차 3일] 합성곱 연산', status: 'IN_PROGRESS' };
  assert.equal(stepLabel(it), '1주차 3일');
  assert.equal(stepOptionLabel(it), '1주차 3일 · 합성곱 연산 (진행 중)');
  assert.equal(stepLabel({ scheduledDate: '2026-10-29' }), '10월 29일(목)');
});

await test('id 비교는 숫자·문자열 무관', () => {
  assert.ok(sameId(13, '13'));
  assert.ok(!sameId(null, null));
  assert.equal(findItem([{ id: 9002, title: 'SQLD' }], '9002').title, 'SQLD');
});

await test('status 별 화면 — READY/단계 완료/전체 완료/데이터 부족', () => {
  assert.equal(statusView({ mode: 'ROADMAP_COACH', result: { status: 'READY' } }).kind, 'ready');
  assert.equal(statusView({ mode: 'ROADMAP_COACH', result: { status: 'CURRENT_STEP_COMPLETED' } }).kind, 'stepDone');
  assert.match(statusView({ mode: 'ROADMAP_COACH', result: { status: 'ALL_COMPLETED' } }).title, /로드맵/);
  assert.match(statusView({ mode: 'MANUAL_NEXT', result: { status: 'ALL_COMPLETED' } }).title, /남은 학습/);
  const empty = statusView({ mode: 'MANUAL_NEXT', result: { status: 'INSUFFICIENT_DATA', message: '항목 없음' } });
  assert.equal(empty.kind, 'empty');
  assert.equal(empty.message, '항목 없음');
});

await test('경고 문구 — 앞선 단계 미완료', () => {
  assert.match(warningText({ code: 'PREVIOUS_STEPS_INCOMPLETE', itemIds: [11, 12] }), /앞선 단계 2개/);
  assert.equal(warningText({ code: 'X', message: '서버 문구' }), '서버 문구');
});

await test('반영 후보 문구 — 세션 / 예정일 변경', () => {
  assert.equal(changeText({ kind: 'ADD_STUDY_SESSION', date: '2026-10-29', minutes: 20 }, '2026-10-28'), '내일 · 10월 29일(목) · 20분 학습 세션');
  assert.equal(changeText({ kind: 'RESCHEDULE_PLANNER', fromDate: '2026-10-25', toDate: '2026-10-29' }, '2026-10-28'),
    '예정일 10월 25일(일) → 내일 · 10월 29일(목)');
});

await test('오류 매핑 — 429/503 재시도 안내 + Retry-After, 504, 409, 403, 네트워크, 취소는 무시', () => {
  const busy = errorView({ response: { status: 429, data: { error: { code: 'ADAPTIVE_BUSY', message: 'm', retryAfterSeconds: 4 } }, headers: {} } });
  assert.equal(busy.retryable, true);
  assert.equal(busy.retryAfter, 4);
  assert.equal(busy.title, '잠시 후 다시 시도해 주세요');
  assert.equal(errorView({ response: { status: 503, data: {}, headers: { 'retry-after': '7' } } }).retryAfter, 7);
  assert.equal(errorView({ response: { status: 504, data: {} } }).code, 'TIMEOUT');
  assert.equal(errorView({ code: 'ECONNABORTED' }).code, 'TIMEOUT');
  assert.equal(errorView({ response: { status: 409, data: { error: { code: 'ADAPTIVE_STALE', message: 's' } } } }).code, 'ADAPTIVE_STALE');
  assert.equal(errorView({ response: { status: 403, data: {} } }).retryable, false);
  assert.equal(errorView({ message: 'Network Error' }).code, 'NETWORK');
  assert.equal(errorView({ code: 'ERR_CANCELED', name: 'CanceledError' }), null);
});

await test('최신 요청 게이트 — 빠른 연속 선택에서 늦게 온 이전 응답은 버리고, 이전 요청은 취소된다', async () => {
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
  const s15 = run(15, 60);
  const s30 = run(30, 40);
  const s60 = run(60, 5);
  const [sig15, sig30, sig60] = await Promise.all([s15, s30, s60]);
  assert.deepEqual(applied, [60], '오래된 응답(15·30)이 최신(60)을 덮지 않는다');
  assert.equal(sig15.aborted, true);
  assert.equal(sig30.aborted, true);
  assert.equal(sig60.aborted, false);
  gate.abort();
  assert.equal(sig60.aborted, true, '화면 이탈 시 진행 중 요청 취소');
});

await test('실제 ai07 응답 원본 — 활동 시간 합 = 선택 시간, 활동 종류 라벨 존재', () => {
  for (const key of ['roadmap30', 'roadmap60', 'manual30']) {
    const r = examples[key].response;
    assert.equal(sumActivityMinutes(r.recommendation.activities), r.availableMinutes, key);
    for (const a of r.recommendation.activities) assert.ok(ACTIVITY_LABEL[a.type], `${key} ${a.type}`);
  }
  for (const b of examples.manual30.response.recommendation.scoreBreakdown) assert.ok(FACTOR_LABEL[b.factor], b.factor);
  for (const alt of examples.manual30.response.alternatives) for (const b of alt.scoreBreakdown) assert.ok(FACTOR_LABEL[b.factor], b.factor);
});

await test('집중 모드 진행 — 경과 시간에 맞는 활동, 끝나면 done', () => {
  const acts = examples.roadmap30.response.recommendation.activities; // 10 / 15 / 5
  assert.equal(focusProgress(acts, 30, 0).index, 0);
  assert.equal(focusProgress(acts, 30, 10 * 60 + 1).index, 1);
  assert.equal(focusProgress(acts, 30, 26 * 60).index, 2);
  const end = focusProgress(acts, 30, 31 * 60);
  assert.equal(end.done, true);
  assert.equal(end.remainingSec, 0);
  assert.equal(formatClock(125), '02:05');
});

console.log(`\nadaptive-navigator smoke: ${passed} passed${process.exitCode ? ' (일부 실패)' : ''}`);
