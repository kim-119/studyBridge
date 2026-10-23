import test from 'node:test';
import assert from 'node:assert/strict';
import {
  INITIAL_QUIZ_STATE,
  QUIZ_PHASE,
  applyEndPayload,
  applyScoreboardPayload,
  applySessionPayload,
  applySubmittedPayload,
  isAnswerable,
  rememberDismissedSession,
  remainingSecondsAt,
  selectAnswer,
  timeTakenSecondsAt,
} from '../screens/groupstudy/quizSessionModel.js';

const QUESTION = {
  sessionId: 11,
  phase: 'QUESTION',
  quizId: 3,
  quizTitle: '네트워크',
  questionId: 101,
  questionText: 'TCP 는?',
  options: ['A', 'B', 'C', 'D'],
  currentIndex: 0,
  totalQuestions: 5,
  timeLimitSeconds: 30,
  remainingSeconds: 30,
};

test('풀이 시간은 웹처럼 문제 시작 시각부터의 벽시계 경과 시간이다', () => {
  const receivedAt = 1_000_000;
  const state = applySessionPayload(INITIAL_QUIZ_STATE, QUESTION, receivedAt);

  assert.equal(timeTakenSecondsAt(state, receivedAt + 7_400), 7);
  assert.equal(remainingSecondsAt(state, receivedAt + 7_400), 23);
});

test('중간에 합류하면 남은 시간만큼 시작 시각을 앞당겨 계산한다', () => {
  const receivedAt = 2_000_000;
  const state = applySessionPayload(INITIAL_QUIZ_STATE, { ...QUESTION, remainingSeconds: 20 }, receivedAt);

  assert.equal(timeTakenSecondsAt(state, receivedAt), 10);
});

test('시작 시각을 모르면 웹과 같은 기본값 5초를 보낸다', () => {
  assert.equal(timeTakenSecondsAt(INITIAL_QUIZ_STATE, 123), 5);
});

test('제출 후에는 다시 답할 수 없고 거절 응답이 오면 선택을 되돌린다', () => {
  const now = 3_000_000;
  const started = applySessionPayload(INITIAL_QUIZ_STATE, QUESTION, now);
  assert.equal(isAnswerable(started, now), true);

  const submitted = selectAnswer(started, 2);
  assert.equal(isAnswerable(submitted, now), false);

  const rejected = applySubmittedPayload(submitted, { sessionId: 11, questionId: 101, accepted: false });
  assert.equal(rejected.selectedAnswer, null);
  assert.equal(rejected.hasSubmitted, false);
});

test('다른 세션의 이벤트는 무시한다', () => {
  const state = applySessionPayload(INITIAL_QUIZ_STATE, QUESTION, 0);
  const ignored = applyScoreboardPayload(state, { sessionId: 99, scoreboard: [{ userId: 1, points: 10 }] });
  assert.equal(ignored, state);
});

test('점수판 ENDED 와 quiz/end 는 최종 결과와 랭킹을 남긴다', () => {
  const state = applySessionPayload(INITIAL_QUIZ_STATE, QUESTION, 0);
  const scoreboard = [{ userId: 7, displayName: '나', points: 30 }];

  const viaScoreboard = applyScoreboardPayload(state, { sessionId: 11, phase: 'ENDED', scoreboard });
  assert.equal(viaScoreboard.phase, QUIZ_PHASE.ENDED);
  assert.deepEqual(viaScoreboard.scoreboard, scoreboard);

  const viaEnd = applyEndPayload(state, { sessionId: 11, scoreboard });
  assert.equal(viaEnd.phase, QUIZ_PHASE.ENDED);
  assert.equal(viaEnd.finalResult.sessionId, 11);
});

test('닫은 퀴즈 세션은 최근 20개까지만 기억한다', () => {
  let dismissed = [];
  for (let sessionId = 1; sessionId <= 25; sessionId += 1) {
    dismissed = rememberDismissedSession(dismissed, sessionId);
  }
  assert.equal(dismissed.length, 20);
  assert.equal(dismissed[0], 6);
  assert.deepEqual(rememberDismissedSession([1, 2], 2), [1, 2]);
});
