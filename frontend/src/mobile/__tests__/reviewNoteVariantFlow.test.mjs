import test from 'node:test';
import assert from 'node:assert/strict';
import { createBackgroundTaskStore } from '../data/backgroundTasks.js';
import {
  createEmptyVariantSession,
  loadVariantSession,
  saveVariantSession,
} from '../data/reviewNoteVariantSession.js';
import {
  applyGeneratedResult,
  completeVariantSession,
  goToNextQuestion,
  progressOf,
  variantGenerationTaskKey,
} from '../screens/reviewnotes/variantProgress.js';

const SETTINGS = { wrongQuestionId: 1, difficulty: 'normal', count: 5 };
const REQUEST = { wrongQuestionId: 1, difficulty: 'normal', count: 5 };

function generatedQuestions(count) {
  return Array.from({ length: count }, (_, index) => ({
    question: `유사문제 ${index + 1}`,
    choices: ['가', '나', '다', '라'],
    answer: '가',
  }));
}

function fiveQuestionSession() {
  return applyGeneratedResult(createEmptyVariantSession(SETTINGS), REQUEST, {
    questions: generatedQuestions(5),
    usedFallback: false,
  });
}

function solveCurrent(session, pickedIndex) {
  const questionId = progressOf(session).currentQuestion.id;
  return {
    ...session,
    answers: { ...session.answers, [questionId]: pickedIndex },
    submitted: { ...session.submitted, [questionId]: true },
  };
}

function createMemoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}

test('T19 5문제를 요청하면 생성된 5문제를 모두 유지한다', () => {
  const session = fiveQuestionSession();
  const progress = progressOf(session);

  assert.equal(session.questions.length, 5);
  assert.equal(progress.total, 5);
  assert.equal(progress.currentNumber, 1);
  assert.equal(progress.isLast, false);
});

test('T20 다음 문제를 누르면 현재 문제 번호가 1씩 증가한다', () => {
  let session = solveCurrent(fiveQuestionSession(), 0);
  session = goToNextQuestion(session);
  assert.equal(progressOf(session).currentNumber, 2);

  session = goToNextQuestion(solveCurrent(session, 1));
  assert.equal(progressOf(session).currentNumber, 3);
  assert.equal(progressOf(session).submittedCount, 2);
  assert.equal(progressOf(session).correctCount, 1);
});

test('T21 다음 문제는 새 생성 요청 없이 최초 생성 배열을 그대로 쓴다', async () => {
  const store = createBackgroundTaskStore();
  const taskKey = variantGenerationTaskKey(7);
  let generationRequests = 0;

  const initial = await store.run(taskKey, async () => {
    generationRequests += 1;
    return fiveQuestionSession();
  });

  let session = initial;
  for (let step = 0; step < 4; step += 1) session = goToNextQuestion(solveCurrent(session, 0));

  assert.equal(generationRequests, 1);
  assert.equal(session.questions, initial.questions);
  assert.equal(store.get(taskKey).status, 'ready');
  assert.equal(progressOf(session).currentNumber, 5);
});

test('T22 마지막 문제에서는 다음 문제 대신 완료로 끝난다', () => {
  let session = fiveQuestionSession();
  for (let step = 0; step < 4; step += 1) session = goToNextQuestion(solveCurrent(session, 0));
  session = solveCurrent(session, 2);

  const lastProgress = progressOf(session);
  assert.equal(lastProgress.isLast, true);
  assert.equal(lastProgress.isCurrentSubmitted, true);
  assert.equal(goToNextQuestion(session), session);

  const completed = progressOf(completeVariantSession(session));
  assert.equal(completed.isCompleted, true);
  assert.equal(completed.correctCount, 4);
  assert.equal(completed.total, 5);
});

test('T23 다른 탭으로 이동해 화면이 사라졌다 돌아와도 같은 세션을 복원한다', () => {
  const storage = createMemoryStorage();
  let session = goToNextQuestion(solveCurrent(fiveQuestionSession(), 0));
  session = goToNextQuestion(solveCurrent(session, 3));
  saveVariantSession(11, session, storage);

  const restored = loadVariantSession(11, SETTINGS, storage);
  assert.deepEqual(restored.questions, session.questions);
  assert.equal(progressOf(restored).currentNumber, 3);
  assert.deepEqual(restored.answers, session.answers);
  assert.deepEqual(restored.submitted, session.submitted);

  saveVariantSession(11, completeVariantSession(restored), storage);
  assert.equal(progressOf(loadVariantSession(11, SETTINGS, storage)).isCompleted, true);
});
