import test from 'node:test';
import assert from 'node:assert/strict';
import { TASK_STATUS, createBackgroundTaskStore } from '../data/backgroundTasks.js';
import { materialQuizTaskKey, startMaterialQuizGeneration } from '../screens/archive/materialQuizGeneration.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function readyQuiz(quizId) {
  return {
    quizId,
    success: true,
    questions: [{ questionId: 'q1', question: '문항', options: [{ optionId: 'o1', text: '보기' }] }],
  };
}

function fakeGenerator() {
  const calls = [];
  const pending = [];
  const generateQuiz = (materialId, request, options) => {
    calls.push({ materialId, request, options });
    const next = deferred();
    pending.push(next);
    return next.promise;
  };
  return { calls, pending, generateQuiz };
}

const OPTIONS = { difficulty: '보통', questionCount: 10 };

test('T24 생성 시작 즉시 해당 자료의 상태가 GENERATING 이 된다', () => {
  const store = createBackgroundTaskStore();
  const generator = fakeGenerator();

  startMaterialQuizGeneration(store, { materialId: 5, options: OPTIONS, generateQuiz: generator.generateQuiz });

  assert.equal(store.get(materialQuizTaskKey(5)).status, TASK_STATUS.GENERATING);
  assert.equal(store.get(materialQuizTaskKey(6)).status, TASK_STATUS.IDLE);
});

test('T25 화면이 사라져도(구독 해제) 요청을 취소하지 않는다', async () => {
  const store = createBackgroundTaskStore();
  const generator = fakeGenerator();
  const unsubscribe = store.subscribe(() => {});

  const running = startMaterialQuizGeneration(store, { materialId: 5, options: OPTIONS, generateQuiz: generator.generateQuiz });
  await Promise.resolve();
  unsubscribe();

  assert.equal(generator.calls.length, 1);
  assert.equal(generator.calls[0].options, undefined);
  generator.pending[0].resolve(readyQuiz(31));
  assert.equal((await running).quizId, 31);
});

test('T26 요청 결과는 컴포넌트가 아니라 자료별 저장소가 소유한다', async () => {
  const store = createBackgroundTaskStore();
  const generator = fakeGenerator();

  const running = startMaterialQuizGeneration(store, { materialId: 5, options: OPTIONS, generateQuiz: generator.generateQuiz });
  await Promise.resolve();
  generator.pending[0].resolve(readyQuiz(31));
  await running;

  const owned = store.get(materialQuizTaskKey(5));
  assert.equal(owned.status, TASK_STATUS.READY);
  assert.equal(owned.result.quizId, 31);
});

test('T27 생성 중에 돌아오면 생성 중 상태를 그대로 본다', async () => {
  const store = createBackgroundTaskStore();
  const generator = fakeGenerator();

  startMaterialQuizGeneration(store, { materialId: 5, options: OPTIONS, generateQuiz: generator.generateQuiz });
  await Promise.resolve();

  const whenReturning = store.get(materialQuizTaskKey(5));
  assert.equal(whenReturning.status, TASK_STATUS.GENERATING);
  assert.equal(whenReturning.result, null);
});

test('T28 완료 후 돌아오면 생성된 퀴즈를 받는다', async () => {
  const store = createBackgroundTaskStore();
  const generator = fakeGenerator();
  const running = startMaterialQuizGeneration(store, { materialId: 5, options: OPTIONS, generateQuiz: generator.generateQuiz });
  await Promise.resolve();
  generator.pending[0].resolve(readyQuiz(40));
  await running;

  const whenReturning = store.get(materialQuizTaskKey(5));
  assert.equal(whenReturning.status, TASK_STATUS.READY);
  assert.equal(whenReturning.result.questions.length, 1);

  store.reset(materialQuizTaskKey(5));
  assert.equal(store.get(materialQuizTaskKey(5)).status, TASK_STATUS.IDLE);
});

test('T29 생성 중에 버튼을 여러 번 눌러도 POST 는 한 번만 나간다', async () => {
  const store = createBackgroundTaskStore();
  const generator = fakeGenerator();
  const start = () =>
    startMaterialQuizGeneration(store, { materialId: 5, options: OPTIONS, generateQuiz: generator.generateQuiz });

  const first = start();
  const second = start();
  const third = start();
  await Promise.resolve();

  assert.equal(generator.calls.length, 1);
  assert.equal(first, second);
  assert.equal(second, third);
  store.reset(materialQuizTaskKey(5));
  assert.equal(store.get(materialQuizTaskKey(5)).status, TASK_STATUS.GENERATING);
});

test('T30 실패하면 FAILED 로 멈추고 다시 시도할 수 있다', async () => {
  const store = createBackgroundTaskStore();
  const generator = fakeGenerator();
  const start = () =>
    startMaterialQuizGeneration(store, { materialId: 5, options: OPTIONS, generateQuiz: generator.generateQuiz });

  const failed = start();
  await Promise.resolve();
  generator.pending[0].resolve({ success: false, errorCode: 'AI_TIMEOUT', message: 'AI 응답 시간이 초과되었습니다.' });
  await assert.rejects(failed, /AI 응답 시간이 초과되었습니다/);

  const afterFailure = store.get(materialQuizTaskKey(5));
  assert.equal(afterFailure.status, TASK_STATUS.FAILED);
  assert.equal(afterFailure.error.userMessage, 'AI 응답 시간이 초과되었습니다.');

  const retried = start();
  assert.equal(store.get(materialQuizTaskKey(5)).status, TASK_STATUS.GENERATING);
  await Promise.resolve();
  generator.pending[1].resolve(readyQuiz(41));
  await retried;
  assert.equal(generator.calls.length, 2);
  assert.equal(store.get(materialQuizTaskKey(5)).status, TASK_STATUS.READY);
});
