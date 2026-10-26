import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  findButtonByText,
  flushEffects,
  importMobileModule,
  loadRenderer,
  press,
  renderElement,
  textOf,
} from './support/componentHarness.mjs';

const { React, act } = await loadRenderer();
const { MemoryRouter, Route, Routes, useNavigate } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { backgroundTasks, TASK_STATUS } = await importMobileModule('data/backgroundTasks.js');
const { materialQuizTaskKey } = await importMobileModule('screens/archive/materialQuizGeneration.js');
const { default: MaterialDetailScreen } = await importMobileModule('screens/archive/MaterialDetailScreen.jsx');

const GENERATING_TEXT = '퀴즈를 생성하고 있습니다.';
const HIDDEN_EXPLANATION = '서버만 아는 해설';

let navigateTo = null;
let mountedRenderers = [];
let generateCalls;
let pendingGenerations;
let quizListLoader;
let submitCalls;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function generatedQuiz(quizId) {
  return {
    quizId,
    success: true,
    difficulty: '보통',
    createdAt: '2026-09-28T10:00:00',
    questions: [
      {
        questionId: 'q_os',
        index: 0,
        question: '운영체제의 역할은?',
        options: [
          { optionId: 'o1', text: '자원 관리' },
          { optionId: 'o2', text: '문서 편집' },
        ],
        correctAnswer: 'o2',
        answerIndex: 1,
        correctOptionIds: ['o2'],
        explanation: HIDDEN_EXPLANATION,
      },
    ],
  };
}

function stubApis() {
  generateCalls = [];
  pendingGenerations = [];
  submitCalls = [];
  quizListLoader = async () => [];

  api.materialService.getMaterialDetail = async (materialId) => ({
    materialId: Number(materialId),
    title: `자료 ${materialId}`,
    materialType: 'DOCUMENT',
    extractionStatus: 'COMPLETED',
    originalFileName: 'os.pdf',
  });
  api.materialService.getSummary = async () => ({ summary: '요약' });
  api.materialService.getQuizzes = (materialId) => quizListLoader(materialId);
  api.materialService.generateQuiz = (materialId, request) => {
    generateCalls.push({ materialId, request });
    const pending = deferred();
    pendingGenerations.push(pending);
    return pending.promise;
  };
  api.materialService.submitQuiz = async (materialId, quizId, answers) => {
    submitCalls.push({ materialId, quizId, answers });
    return {
      quizId,
      score: 100,
      correctCount: 1,
      totalQuestions: 1,
      results: [
        {
          questionId: 'q_os',
          answered: true,
          correct: true,
          selectedOptionIds: ['o1'],
          correctOptionIds: ['o1'],
          explanation: HIDDEN_EXPLANATION,
        },
      ],
    };
  };
  api.reviewNoteService.listReviewNotes = async () => ({ ok: true, items: [] });
}

beforeEach(stubApis);

afterEach(async () => {
  const leftovers = mountedRenderers;
  mountedRenderers = [];
  for (const renderer of leftovers) {
    await act(async () => {
      renderer.unmount();
    });
  }
});

function NavigationProbe() {
  navigateTo = useNavigate();
  return null;
}

async function renderApp(initialPath) {
  const element = React.createElement(
    MemoryRouter,
    { initialEntries: [initialPath] },
    React.createElement(NavigationProbe),
    React.createElement(
      Routes,
      null,
      React.createElement(Route, { path: '/archive', element: React.createElement('p', null, '자료 목록') }),
      React.createElement(Route, { path: '/archive/:materialId', element: React.createElement(MaterialDetailScreen) })
    )
  );
  const renderer = await renderElement(element);
  mountedRenderers.push(renderer);
  await flushEffects();
  return renderer;
}

async function navigate(path) {
  await act(async () => {
    navigateTo(path);
  });
  await flushEffects();
}

function tabButton(renderer, label) {
  return renderer.root.find(
    (instance) => instance.type === 'button' && instance.props.role === 'tab' && textOf(instance.children) === label
  );
}

async function openQuizTab(renderer) {
  await press(tabButton(renderer, '퀴즈'));
  await flushEffects();
}

async function openMaterialQuiz(materialId) {
  const renderer = await renderApp(`/archive/${materialId}`);
  await openQuizTab(renderer);
  return renderer;
}

function screenText(renderer) {
  return textOf(renderer.toJSON());
}

function generationStatusOf(materialId) {
  return backgroundTasks.get(materialQuizTaskKey(materialId)).status;
}

async function startGeneration(renderer) {
  await press(findButtonByText(renderer, '새 퀴즈 생성'));
  await flushEffects();
}

async function finishGeneration(index, quiz) {
  await act(async () => {
    pendingGenerations[index].resolve(quiz);
    await pendingGenerations[index].promise;
  });
  await flushEffects();
}

function busyGenerateButtons(renderer) {
  return renderer.root.findAll(
    (instance) =>
      instance.type === 'button' &&
      instance.props.disabled === true &&
      String(instance.props.className).includes('mobile-button--primary')
  );
}

test('T9 자료 상세 퀴즈 탭에서 생성하면 POST 를 보내고 생성 중 상태를 보여준다', async () => {
  const renderer = await openMaterialQuiz(9);
  await startGeneration(renderer);

  assert.equal(generateCalls.length, 1);
  assert.equal(generateCalls[0].materialId, 9);
  assert.deepEqual(generateCalls[0].request, {
    difficulty: '보통',
    questionCount: 10,
    pageRange: '전체',
    sourceMode: 'PDF_BASED',
  });
  assert.equal(generationStatusOf(9), TASK_STATUS.GENERATING);
  assert.ok(screenText(renderer).includes(GENERATING_TEXT));
});

test('T10 생성 중 자료보관함으로 이동해 화면이 사라져도 요청은 계속된다', async () => {
  const renderer = await openMaterialQuiz(10);
  await startGeneration(renderer);
  await navigate('/archive');

  assert.ok(screenText(renderer).includes('자료 목록'));
  assert.equal(generationStatusOf(10), TASK_STATUS.GENERATING);
  assert.equal(generateCalls.length, 1);
});

test('T11 생성 중에 같은 자료의 퀴즈 탭으로 돌아오면 생성 중 상태를 본다', async () => {
  const renderer = await openMaterialQuiz(11);
  await startGeneration(renderer);
  await navigate('/archive');
  await navigate('/archive/11');
  await openQuizTab(renderer);

  assert.ok(screenText(renderer).includes(GENERATING_TEXT));
  assert.equal(busyGenerateButtons(renderer).length, 1);
  assert.equal(generateCalls.length, 1);
});

test('T12 떠나 있는 동안 생성이 끝나면 돌아왔을 때 결과 퀴즈를 보여준다', async () => {
  const renderer = await openMaterialQuiz(12);
  await startGeneration(renderer);
  await navigate('/archive');
  await finishGeneration(0, generatedQuiz(1201));
  assert.equal(generationStatusOf(12), TASK_STATUS.READY);

  await navigate('/archive/12');
  await openQuizTab(renderer);

  const text = screenText(renderer);
  assert.ok(text.includes('운영체제의 역할은?'));
  assert.ok(!text.includes(GENERATING_TEXT));
  assert.equal(generationStatusOf(12), TASK_STATUS.IDLE);
});

test('T13 생성 중 버튼을 여러 번 눌러도 POST 는 한 번만 나간다', async () => {
  const renderer = await openMaterialQuiz(13);
  const generateButton = findButtonByText(renderer, '새 퀴즈 생성');

  await press(generateButton);
  await press(generateButton);
  await press(generateButton);
  await flushEffects();

  assert.equal(generateCalls.length, 1);
  assert.equal(busyGenerateButtons(renderer).length, 1);
});

test('POST 성공 뒤 목록 재조회가 실패해도 생성된 퀴즈를 오류로 바꾸지 않는다', async () => {
  const renderer = await openMaterialQuiz(14);
  await startGeneration(renderer);
  quizListLoader = async () => {
    throw Object.assign(new Error('Server Error'), { response: { status: 500 } });
  };
  await finishGeneration(0, generatedQuiz(1401));

  const text = screenText(renderer);
  assert.ok(text.includes('운영체제의 역할은?'));
  assert.ok(!text.includes('서버에서 오류가 발생했습니다'));
  assert.ok(findButtonByText(renderer, '제출'));
  assert.equal(findButtonByText(renderer, '새 퀴즈 생성').props.disabled, false);
});

test('생성이 실패하면 오류와 다시 시도를 보여주고 다시 시도하면 새 POST 를 보낸다', async () => {
  const renderer = await openMaterialQuiz(15);
  await startGeneration(renderer);
  await act(async () => {
    pendingGenerations[0].reject(Object.assign(new Error('timeout'), { code: 'ECONNABORTED' }));
    await pendingGenerations[0].promise.catch(() => {});
  });
  await flushEffects();

  assert.equal(generationStatusOf(15), TASK_STATUS.FAILED);
  assert.ok(renderer.root.findAll((instance) => instance.props['data-quiz-generation'] === 'failed').length === 1);
  const retryButton = findButtonByText(renderer, '다시 시도');
  assert.ok(retryButton);
  assert.equal(retryButton.props.disabled, false);

  await press(retryButton);
  await flushEffects();
  assert.equal(generateCalls.length, 2);
  assert.ok(screenText(renderer).includes(GENERATING_TEXT));
});

test('첫 화면은 정답·해설을 쓰지 않고 제출은 questionId·selectedOptionIds 만 보내며 점수는 서버 값을 쓴다', async () => {
  const renderer = await openMaterialQuiz(16);
  await startGeneration(renderer);
  await finishGeneration(0, generatedQuiz(1601));

  const initialText = screenText(renderer);
  assert.ok(!initialText.includes(HIDDEN_EXPLANATION));
  assert.ok(!initialText.includes('점'));
  const gradedMarks = renderer.root.findAll((instance) => /is-correct|is-wrong/.test(String(instance.props.className || '')));
  assert.equal(gradedMarks.length, 0);

  await press(findButtonByText(renderer, '자원 관리'));
  await press(findButtonByText(renderer, '제출'));
  await flushEffects();

  assert.deepEqual(submitCalls, [
    { materialId: 16, quizId: 1601, answers: [{ questionId: 'q_os', selectedOptionIds: ['o1'] }] },
  ]);
  const gradedText = screenText(renderer);
  assert.ok(gradedText.includes('채점 결과 100점 (1/1)'));
  assert.ok(gradedText.includes(HIDDEN_EXPLANATION));
});
