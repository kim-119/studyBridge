// node --test frontend/src/utils/__tests__ — 오답노트 문항 상태 머신(다시 풀기 초기화) 회귀 테스트
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ATTEMPT_STATUS, createAttempt, attemptOf, attemptMapReducer, transition, submitAndGrade, canPick, canSubmit, isGraded,
} from '../questionAttempt.js';

const R = attemptMapReducer;

test('READY → ANSWERING → SUBMITTED → GRADED 정상 전이', () => {
  let m = {};
  assert.equal(attemptOf(m, 'q1').status, ATTEMPT_STATUS.READY);
  m = R(m, { type: 'PICK', id: 'q1', choice: 2 });
  assert.equal(m.q1.status, ATTEMPT_STATUS.ANSWERING);
  assert.equal(m.q1.picked, 2);
  assert.ok(canSubmit(m.q1));
  m = R(m, { type: 'SUBMIT', id: 'q1' });
  assert.equal(m.q1.status, ATTEMPT_STATUS.SUBMITTED);
  m = R(m, { type: 'GRADE', id: 'q1', correct: false });
  assert.equal(m.q1.status, ATTEMPT_STATUS.GRADED);
  assert.equal(m.q1.correct, false);
  assert.ok(!canPick(m.q1));
});

test('다시 풀기(RETRY): 선택/채점/결과 모두 초기화, 시도 번호 증가, 이전 시도는 history 에 보존', () => {
  let m = submitAndGrade(R({}, { type: 'PICK', id: 'q1', choice: 0 }), 'q1', false);
  m = R(m, { type: 'RETRY', id: 'q1' });
  const a = m.q1;
  assert.equal(a.status, ATTEMPT_STATUS.READY);
  assert.equal(a.picked, null);
  assert.equal(a.correct, null);
  assert.equal(a.attempt, 2);
  assert.deepEqual(a.history, [{ attempt: 1, picked: 0, correct: false }]);
  assert.ok(canPick(a));
  assert.ok(!isGraded(a));
});

test('3회 이상 반복 다시 풀기 + 다른 답으로 재채점', () => {
  let m = {};
  for (let i = 1; i <= 4; i++) {
    m = R(m, { type: 'PICK', id: 'q1', choice: i % 3 });
    m = submitAndGrade(m, 'q1', i % 2 === 0);
    assert.equal(m.q1.status, ATTEMPT_STATUS.GRADED);
    assert.equal(m.q1.attempt, i);
    assert.equal(m.q1.picked, i % 3);
    assert.equal(m.q1.correct, i % 2 === 0);
    m = R(m, { type: 'RETRY', id: 'q1' });
    assert.equal(m.q1.status, ATTEMPT_STATUS.READY);
    assert.equal(m.q1.picked, null);
    assert.equal(m.q1.attempt, i + 1);
    assert.equal(m.q1.history.length, i);
  }
});

test('문항 간 독립: q1 다시 풀기가 q2/q3 채점 상태를 건드리지 않는다', () => {
  let m = {};
  for (const id of ['q1', 'q2', 'q3']) {
    m = R(m, { type: 'PICK', id, choice: 1 });
    m = submitAndGrade(m, id, id === 'q2');
  }
  const q2Before = m.q2; const q3Before = m.q3;
  m = R(m, { type: 'RETRY', id: 'q1' });
  assert.equal(m.q1.status, ATTEMPT_STATUS.READY);
  assert.equal(m.q2, q2Before);
  assert.equal(m.q3, q3Before);
  assert.equal(m.q2.status, ATTEMPT_STATUS.GRADED);
  assert.equal(m.q3.status, ATTEMPT_STATUS.GRADED);
});

test('허용되지 않는 전이는 무시(READY 에서 SUBMIT/GRADE/RETRY, GRADED 에서 PICK)', () => {
  const m0 = {};
  assert.equal(R(m0, { type: 'SUBMIT', id: 'q' }), m0);
  assert.equal(R(m0, { type: 'GRADE', id: 'q', correct: true }), m0);
  assert.equal(R(m0, { type: 'RETRY', id: 'q' }), m0);
  const graded = submitAndGrade(R({}, { type: 'PICK', id: 'q', choice: 0 }), 'q', true);
  assert.equal(R(graded, { type: 'PICK', id: 'q', choice: 1 }), graded);
  // 선택 없이 제출 불가
  const ready = { q: createAttempt() };
  assert.equal(submitAndGrade(ready, 'q', true), ready);
});

test('SEED(서버 복원)는 로컬 상태가 없을 때만 적용 — 다시 풀기 중인 문항을 되돌리지 않는다(근본 원인 회귀)', () => {
  let m = R({}, { type: 'SEED', id: 0, picked: 1, correct: false });
  assert.equal(m[0].status, ATTEMPT_STATUS.GRADED);
  assert.equal(m[0].seeded, true);
  m = R(m, { type: 'RETRY', id: 0 });
  assert.equal(m[0].status, ATTEMPT_STATUS.READY);
  // 서버 응답 재수신(retryResults 갱신 → effect 재실행)을 흉내: SEED 가 다시 들어와도 READY 유지
  const again = R(m, { type: 'SEED', id: 0, picked: 1, correct: false });
  assert.equal(again, m);
  assert.equal(again[0].status, ATTEMPT_STATUS.READY);
  assert.equal(again[0].attempt, 2);
});

test('RESET_ALL 은 새 문제 세트 생성 시 전체 초기화', () => {
  const m = submitAndGrade(R({}, { type: 'PICK', id: 'a', choice: 0 }), 'a', true);
  assert.deepEqual(R(m, { type: 'RESET_ALL' }), {});
  assert.equal(transition(undefined, { type: 'NOPE' }).status, ATTEMPT_STATUS.READY);
});
