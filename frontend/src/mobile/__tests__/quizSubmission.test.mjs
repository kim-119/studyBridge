import test from 'node:test';
import assert from 'node:assert/strict';
import { newestQuizzesFirst } from '../screens/archive/quizModel.js';

// 채점·정오답 집계는 서버 채점 계약(materialQuizModel.test.mjs)이 담당한다. 여기서는 목록 정렬만 검증한다.
test('퀴즈 목록은 최신 생성순으로 정렬된다', () => {
  const sorted = newestQuizzesFirst([
    { quizId: 1, createdAt: '2026-01-01T10:00:00' },
    { quizId: 3, createdAt: '2026-03-01T10:00:00' },
    { quizId: 2, createdAt: '2026-02-01T10:00:00' },
  ]);

  assert.deepEqual(sorted.map((quiz) => quiz.quizId), [3, 2, 1]);
});

test('생성 시각이 같으면 quizId 가 큰 퀴즈가 먼저 온다', () => {
  const sorted = newestQuizzesFirst([
    { quizId: 4, createdAt: null },
    { quizId: 9, createdAt: null },
  ]);

  assert.deepEqual(sorted.map((quiz) => quiz.quizId), [9, 4]);
});

test('퀴즈 목록이 배열이 아니면 빈 목록이다', () => {
  assert.deepEqual(newestQuizzesFirst(null), []);
});
