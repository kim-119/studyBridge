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

const REVIEW_NOTE_ID = '5';
const DETAIL_PATH = `/review-notes/${REVIEW_NOTE_ID}`;

const { React, act } = await loadRenderer();
const { MemoryRouter, Route, Routes } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { default: ReviewNoteDetailScreen } = await importMobileModule(
  'screens/reviewnotes/ReviewNoteDetailScreen.jsx'
);

const NOTE = {
  id: 5,
  title: '운영체제 오답노트',
  sourceName: '운영체제.pdf',
  wrongCount: 3,
  unansweredCount: 0,
  difficulty: 'normal',
  createdAt: '2026-09-27T10:00:00',
};

function similarQuestion(text, answer = '가') {
  return { question: text, choices: ['가', '나', '다', '라'], correctAnswer: answer, explanation: `${text} 해설` };
}

let variantCalls;
let variantResponses;
let mountedRenderers = [];

function stubReviewNoteApi() {
  variantCalls = [];
  variantResponses = [];
  api.reviewNoteService.getReviewNote = async () => NOTE;
  api.reviewNoteService.retry = async () => ({ questions: [] });
  api.reviewNoteService.reviewNeeded = async () => ({ reviewNeededText: '분석' });
  api.reviewNoteService.variantQuestion = async (id, body) => {
    variantCalls.push({ id, body });
    const next = variantResponses.shift();
    if (!next) throw new Error('unexpected variant request');
    return next;
  };
}

beforeEach(() => {
  window.sessionStorage.clear();
  stubReviewNoteApi();
});

afterEach(async () => {
  const leftovers = mountedRenderers;
  mountedRenderers = [];
  for (const renderer of leftovers) await unmount(renderer);
});

async function renderDetail() {
  const element = React.createElement(
    MemoryRouter,
    { initialEntries: [DETAIL_PATH] },
    React.createElement(
      Routes,
      null,
      React.createElement(Route, { path: '/review-notes/:reviewNoteId', element: React.createElement(ReviewNoteDetailScreen) }),
      React.createElement(Route, { path: '/review-notes', element: React.createElement('p', null, '목록') })
    )
  );
  const renderer = await renderElement(element);
  mountedRenderers.push(renderer);
  await flushEffects();
  return renderer;
}

async function unmount(renderer) {
  mountedRenderers = mountedRenderers.filter((mounted) => mounted !== renderer);
  await act(async () => {
    renderer.unmount();
  });
}

function screenText(renderer) {
  return textOf(renderer.toJSON());
}

function countSelect(renderer) {
  return renderer.root.find(
    (instance) => instance.type === 'select' && instance.props.value !== undefined && textOf(instance.children).includes('개')
  );
}

async function chooseCount(renderer, count) {
  await act(async () => {
    countSelect(renderer).props.onChange({ target: { value: String(count) } });
  });
}

async function tapWithoutWaiting(button) {
  await act(async () => {
    button.props.onClick({ preventDefault() {}, stopPropagation() {} });
  });
}

async function generate(renderer) {
  await press(findButtonByText(renderer, '유사문제 생성'));
  await flushEffects();
}

function optionButtons(renderer) {
  return renderer.root.findAll(
    (instance) => instance.type === 'button' && String(instance.props.className || '').includes('mobile-quiz__option')
  );
}

async function answerCurrent(renderer, optionIndex) {
  await press(optionButtons(renderer)[optionIndex]);
  await press(findButtonByText(renderer, '제출'));
}

function progressText(renderer) {
  const progress = renderer.root.find((instance) => instance.props['data-variant-progress'] !== undefined);
  return textOf(progress.children);
}

async function startThreeQuestionSession() {
  variantResponses.push({
    success: true,
    usedFallback: false,
    questions: [similarQuestion('첫째 문제'), similarQuestion('둘째 문제'), similarQuestion('셋째 문제')],
  });
  const renderer = await renderDetail();
  await chooseCount(renderer, 3);
  await generate(renderer);
  return renderer;
}

test('T24 문항 수 3으로 생성하면 세 문제를 모두 받고 1번 문제를 보여준다', async () => {
  const renderer = await startThreeQuestionSession();

  assert.equal(variantCalls.length, 1);
  assert.equal(variantCalls[0].body.count, 3);
  assert.equal(progressText(renderer), '문제 1 / 3');
  assert.ok(screenText(renderer).includes('첫째 문제'));
  assert.equal(findButtonByText(renderer, '다음 문제'), null);
});

test('T25 1번을 제출하면 다음 문제 버튼이 보인다', async () => {
  const renderer = await startThreeQuestionSession();
  await answerCurrent(renderer, 0);

  assert.ok(findButtonByText(renderer, '다음 문제'));
  assert.equal(findButtonByText(renderer, '완료'), null);
});

test('T26 다음 문제를 누르면 2번 문제로 이동한다', async () => {
  const renderer = await startThreeQuestionSession();
  await answerCurrent(renderer, 0);
  await press(findButtonByText(renderer, '다음 문제'));

  assert.equal(progressText(renderer), '문제 2 / 3');
  assert.ok(screenText(renderer).includes('둘째 문제'));
  assert.equal(findButtonByText(renderer, '다음 문제'), null);
});

test('T27 2번 제출 후 다음 문제를 누르면 3번 문제로 이동한다', async () => {
  const renderer = await startThreeQuestionSession();
  await answerCurrent(renderer, 0);
  await press(findButtonByText(renderer, '다음 문제'));
  await answerCurrent(renderer, 1);
  await press(findButtonByText(renderer, '다음 문제'));

  assert.equal(progressText(renderer), '문제 3 / 3');
  assert.ok(screenText(renderer).includes('셋째 문제'));
});

test('T28 T29 3번 제출 후 완료하면 요약을 보여주고 다음 문제는 생성 API 를 부르지 않는다', async () => {
  const renderer = await startThreeQuestionSession();
  await answerCurrent(renderer, 0);
  await press(findButtonByText(renderer, '다음 문제'));
  await answerCurrent(renderer, 1);
  await press(findButtonByText(renderer, '다음 문제'));
  await answerCurrent(renderer, 0);

  assert.equal(findButtonByText(renderer, '다음 문제'), null);
  await press(findButtonByText(renderer, '완료'));

  assert.ok(screenText(renderer).includes('3문제 중 2문제를 맞혔습니다.'));
  assert.equal(variantCalls.length, 1);
});

test('T30 1/3 만 생성되면 요청·생성 개수를 구분해 보여주고 부족분 재생성을 제안한다', async () => {
  variantResponses.push({ success: true, usedFallback: false, questions: [similarQuestion('첫째 문제')] });
  const renderer = await renderDetail();
  await chooseCount(renderer, 3);
  await generate(renderer);

  const text = screenText(renderer);
  assert.ok(text.includes('3문제 요청 중 1문제만 생성되었습니다.'));
  assert.ok(text.includes('생성된 유사문제 1개 (요청 3개)'));
  assert.equal(progressText(renderer), '문제 1 / 1');
  assert.ok(findButtonByText(renderer, '부족분 2문제 다시 생성'));
});

test('T31 부족분 응답은 중복을 제외하고 뒤에 이어 붙여 1/3→2/3→3/3 이 된다', async () => {
  variantResponses.push({
    success: true,
    usedFallback: false,
    questions: [{ ...similarQuestion('첫째 문제'), id: 'fallback-5-1' }],
  });
  const renderer = await renderDetail();
  await chooseCount(renderer, 3);
  await generate(renderer);
  await answerCurrent(renderer, 0);

  variantResponses.push({
    success: true,
    usedFallback: false,
    questions: [
      { ...similarQuestion('첫째 문제 재출제'), id: 'fallback-5-1' },
      similarQuestion(' 첫째   문제 '),
      similarQuestion('둘째 문제'),
      similarQuestion('셋째 문제'),
    ],
  });
  await press(findButtonByText(renderer, '부족분 2문제 다시 생성'));
  await flushEffects();

  assert.equal(variantCalls.length, 2);
  assert.equal(variantCalls[1].body.count, 2);
  assert.equal(progressText(renderer), '문제 1 / 3');
  assert.ok(screenText(renderer).includes('생성된 유사문제 3개 (요청 3개)'));
  assert.equal(findButtonByText(renderer, '부족분'), null);
  assert.ok(screenText(renderer).includes('이미 받은 문제와 같은 2문제는 제외했습니다.'));

  await press(findButtonByText(renderer, '다음 문제'));
  assert.equal(progressText(renderer), '문제 2 / 3');
  await answerCurrent(renderer, 0);
  await press(findButtonByText(renderer, '다음 문제'));
  assert.equal(progressText(renderer), '문제 3 / 3');
  await answerCurrent(renderer, 0);
  await press(findButtonByText(renderer, '완료'));
  assert.ok(screenText(renderer).includes('3문제 중 3문제를 맞혔습니다.'));
  assert.equal(variantCalls.length, 2);
});

test('T32 탭 이동과 화면 재진입 후에도 문제 목록·현재 번호·답안을 유지한다', async () => {
  const first = await startThreeQuestionSession();
  await answerCurrent(first, 1);
  await press(findButtonByText(first, '다음 문제'));

  await press(findButtonByText(first, 'AI 해설'));
  await flushEffects();
  await press(findButtonByText(first, '유사문제'));
  assert.equal(progressText(first), '문제 2 / 3');

  await unmount(first);
  const second = await renderDetail();

  assert.equal(progressText(second), '문제 2 / 3');
  assert.ok(screenText(second).includes('둘째 문제'));
  assert.ok(screenText(second).includes('오답'));
  assert.equal(variantCalls.length, 1);
});

test('생성 중 화면을 떠났다 돌아오면 생성 중 상태를 보고 완료 결과를 받는다', async () => {
  let finishGeneration;
  api.reviewNoteService.variantQuestion = (id, body) => {
    variantCalls.push({ id, body });
    return new Promise((resolve) => {
      finishGeneration = resolve;
    });
  };

  const first = await renderDetail();
  await tapWithoutWaiting(findButtonByText(first, '유사문제 생성'));
  assert.ok(screenText(first).includes('유사문제를 생성하고 있습니다.'));
  await unmount(first);

  const second = await renderDetail();
  assert.ok(screenText(second).includes('유사문제를 생성하고 있습니다.'));
  assert.equal(findButtonByText(second, '유사문제 생성'), null);
  assert.ok(second.root.findAll((instance) => instance.type === 'button' && instance.props.disabled === true).length > 0);
  assert.equal(variantCalls.length, 1);

  finishGeneration({ success: true, questions: [similarQuestion('첫째 문제'), similarQuestion('둘째 문제'), similarQuestion('셋째 문제')] });
  await flushEffects();
  assert.equal(progressText(second), '문제 1 / 3');
});

test('다시 풀기와 복습 필요 분석 버튼은 공용 액션 버튼 클래스를 쓰고 아이콘은 버튼 글자색을 따른다', async () => {
  const renderer = await renderDetail();
  const expectedClassNames = {
    '다시 풀기': 'mobile-button mobile-button--action',
    '복습 필요 분석': 'mobile-button mobile-button--action mobile-button--block',
  };

  for (const [label, className] of Object.entries(expectedClassNames)) {
    const button = findButtonByText(renderer, label);
    assert.ok(button, `${label} 버튼이 있어야 한다`);
    assert.equal(button.props.className, className);
    assert.equal(button.props.style, undefined);

    const icon = button.find((instance) => instance.type === 'svg');
    assert.ok(String(icon.props.className).split(' ').includes('lucide'));
    assert.equal(icon.props.stroke, 'currentColor');
    assert.equal(icon.props.style, undefined);
  }
});
