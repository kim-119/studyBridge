import test from 'node:test';
import assert from 'node:assert/strict';
import { buildRetrySubmission } from '../screens/reviewnotes/reviewNoteModel.js';

const questions = [
  { options: ['가', '나', '다'], answerIndex: 1 },
  { options: ['A', 'B'], answerIndex: 0 },
  { options: ['X', 'Y'], answerIndex: 1 },
];

test('다시 풀기 제출은 정오답 판정을 보내지 않고 서버가 채점하도록 답만 보낸다', () => {
  const results = buildRetrySubmission(questions, { 0: 2, 1: 0 }, new Set());

  assert.deepEqual(results, [
    { index: 1, userAnswer: '다' },
    { index: 2, userAnswer: 'A' },
  ]);
  results.forEach((result) => assert.equal('correct' in result, false));
});

test('이미 제출해 잠긴 문항과 고르지 않은 문항은 제외한다', () => {
  assert.deepEqual(buildRetrySubmission(questions, { 0: 1, 2: 0 }, new Set([0])), [{ index: 3, userAnswer: 'X' }]);
});
