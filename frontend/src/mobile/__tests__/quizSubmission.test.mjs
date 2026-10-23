import test from 'node:test';
import assert from 'node:assert/strict';
import {
  QUESTION_OUTCOME,
  needsReviewNote,
  newestQuizzesFirst,
  questionOutcome,
  summarizeSubmission,
  toQuizQuestions,
  toReviewNoteAnswers,
} from '../screens/archive/quizModel.js';

const questions = toQuizQuestions({
  quizzes: [
    { question: 'Q1', options: ['A', 'B', 'C'], answer: 0 },
    { question: 'Q2', options: ['A', 'B', 'C'], answer: 2 },
    { question: 'Q3', options: ['A', 'B', 'C'], answer: 1 },
  ],
});

test('문항 결과는 정답 · 오답 · 미응답으로 나뉜다', () => {
  assert.equal(questionOutcome(questions[0], 0), QUESTION_OUTCOME.CORRECT);
  assert.equal(questionOutcome(questions[1], 0), QUESTION_OUTCOME.WRONG);
  assert.equal(questionOutcome(questions[2], undefined), QUESTION_OUTCOME.UNANSWERED);
  assert.equal(questionOutcome(questions[2], null), QUESTION_OUTCOME.UNANSWERED);
});

test('제출 요약은 정답 · 오답 · 미응답 개수를 센다', () => {
  const submission = summarizeSubmission(questions, { 0: 0, 1: 1 });

  assert.deepEqual(submission, { total: 3, correct: 1, wrong: 1, unanswered: 1 });
  assert.equal(needsReviewNote(submission), true);
});

test('모두 맞히면 오답노트가 필요 없다', () => {
  const submission = summarizeSubmission(questions, { 0: 0, 1: 2, 2: 1 });

  assert.equal(submission.correct, 3);
  assert.equal(needsReviewNote(submission), false);
});

test('미응답만 있어도 오답노트 대상이다', () => {
  const submission = summarizeSubmission(questions, { 0: 0, 1: 2 });

  assert.equal(submission.unanswered, 1);
  assert.equal(needsReviewNote(submission), true);
});

test('오답노트 답안은 0-based 문항 번호를 키로, 0-based 보기 번호를 값으로 보낸다', () => {
  assert.deepEqual(toReviewNoteAnswers({ 0: 2, 2: 0 }), { 0: 2, 2: 0 });
  assert.deepEqual(Object.keys(toReviewNoteAnswers({ 1: 1 })), ['1']);
});

test('선택하지 않은 문항은 오답노트 답안에서 빠진다', () => {
  assert.deepEqual(toReviewNoteAnswers({ 0: undefined, 1: null, 2: 1 }), { 2: 1 });
});

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
