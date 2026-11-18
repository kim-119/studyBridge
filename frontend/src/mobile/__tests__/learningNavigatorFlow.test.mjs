import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  findAllByText,
  findButtonByText,
  flushEffects,
  importMobileModule,
  loadRenderer,
  press,
  renderElement,
  textOf,
} from './support/componentHarness.mjs';

// 자료보관함 플래너 자료 → AI 학습 내비게이터 탭 → AI 추천(POST /adaptive) → 일정 반영(POST /adaptive/apply) 흐름.
// 서버 응답 모양은 Spring AdaptivePlannerController(LLM-clean) 기준이고, recommendation 은 실제 ai07 응답 원본을 쓴다.
const { React, act } = await loadRenderer();
const { MemoryRouter, Route, Routes, useLocation, useParams } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { default: MaterialDetailScreen } = await importMobileModule('screens/archive/MaterialDetailScreen.jsx');
const { PLANNER_TABS } = await importMobileModule('screens/archive/planner/PlannerMaterialTabs.jsx');

const examples = JSON.parse(readFileSync(new URL('./support/adaptiveNavigatorExamples.json', import.meta.url), 'utf8'));
const DEBOUNCE_MS = 250;
const TODAY = '2026-10-29';

let navigatorCalls;
let navigatorHandler;
let applyCalls;
let applyHandler;
let material;
let mountedRenderers = [];

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const ROADMAP_ITEMS = [
  { id: 12, week: 1, day: 2, title: '[로드맵 1주차 2일] 활성화 함수', status: 'COMPLETED', checklistTotal: 2, checklistCompleted: 2 },
  { id: 13, week: 1, day: 3, title: '[로드맵 1주차 3일] 합성곱 연산', status: 'IN_PROGRESS', checklistTotal: 3, checklistCompleted: 1 },
  { id: 14, week: 1, day: 4, title: '[로드맵 1주차 4일] 풀링', status: 'PENDING', checklistTotal: 2, checklistCompleted: 0 },
];

const ROADMAP_CHANGES = [
  { id: 'session-13-2026-10-30', kind: 'ADD_STUDY_SESSION', title: '[로드맵 1주차 3일] 합성곱 연산', date: '2026-10-30', minutes: 30 },
  { id: 'reschedule-14', kind: 'RESCHEDULE_PLANNER', title: '[로드맵 1주차 4일] 풀링', fromDate: '2026-10-27', toDate: '2026-10-31' },
];

function roadmapResponse(body, overrides = {}) {
  const minutes = body.availableMinutes;
  const example = minutes === 60 ? examples.roadmap60 : examples.roadmap30;
  return {
    mode: 'ROADMAP_COACH',
    plannerType: 'ROADMAP',
    availableMinutes: minutes,
    today: TODAY,
    currentStepId: body.currentStepId ?? 13,
    suggestedStepId: null,
    items: ROADMAP_ITEMS,
    quiz: { available: false, wrongCount: 0 },
    result: {
      status: 'READY',
      source: 'AI_ASSISTED',
      recommendation: { ...example.recommendation, itemId: 13, title: `${example.recommendation.title} (${minutes}분)` },
      alternatives: [],
      recoveryPlan: null,
      warnings: [],
    },
    changes: ROADMAP_CHANGES,
    proposalToken: `token-${minutes}-${body.currentStepId ?? 13}`,
    warnings: [],
    ...overrides,
  };
}

function manualResponse(body) {
  return {
    mode: 'MANUAL_NEXT',
    plannerType: 'MANUAL',
    availableMinutes: body.availableMinutes,
    today: TODAY,
    currentStepId: null,
    suggestedStepId: null,
    items: [
      { id: 9002, title: 'SQLD 기출문제 풀이', subject: 'SQLD', priority: '높음', status: 'PENDING', dueDate: '2026-10-30' },
      { id: 9004, title: '미적분 문제 풀이', subject: '수학', status: 'PENDING', dueDate: '2026-10-28' },
      { id: 9001, title: 'Java 예외 처리 복습', subject: 'Java', status: 'PENDING', dueDate: '2026-11-01' },
    ],
    quiz: { available: false, wrongCount: 0 },
    result: {
      status: 'READY',
      source: 'RULE_BASED',
      recommendation: examples.manual30.recommendation,
      alternatives: examples.manual30.alternatives,
      recoveryPlan: examples.manual30.recoveryPlan,
      warnings: [],
    },
    changes: [],
    proposalToken: null,
    warnings: [],
  };
}

function stubApis() {
  navigatorCalls = [];
  applyCalls = [];
  navigatorHandler = async (plannerId, body) => roadmapResponse(body);
  applyHandler = async () => ({ applied: [{ kind: 'ADD_STUDY_SESSION' }], alreadyApplied: false });
  material = { materialId: 501, title: 'CNN 로드맵 플래너', materialType: 'PLANNER', plannerId: 7 };

  localStorage.setItem('userId', '2');
  localStorage.setItem('token', 'test-token');
  localStorage.removeItem('sb.aln.minutes');
  sessionStorage.clear();

  api.materialService.getMaterialDetail = async () => material;
  api.materialService.getMemo = async () => ({ content: '' });
  api.plannerService.getPlanAnalysis = async () => null;
  api.planAnalysisService.get = async () => null;
  api.plannerService.getAdaptiveNavigator = (plannerId, body, options) => {
    navigatorCalls.push({ plannerId, body, signal: options?.signal });
    return navigatorHandler(plannerId, body, options);
  };
  api.plannerService.applyAdaptiveProposal = (plannerId, body) => {
    applyCalls.push({ plannerId, body });
    return applyHandler(plannerId, body);
  };
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

function RouteProbe({ name }) {
  const location = useLocation();
  const params = useParams();
  return React.createElement('p', { 'data-route': name, 'data-param': params.plannerId ?? '' }, location.pathname);
}

async function renderArchive() {
  const element = React.createElement(
    MemoryRouter,
    { initialEntries: [`/archive/${material.materialId}`] },
    React.createElement(
      Routes,
      null,
      React.createElement(Route, { path: '/archive/:materialId', element: React.createElement(MaterialDetailScreen) }),
      React.createElement(Route, { path: '/weekly-schedule', element: React.createElement(RouteProbe, { name: 'weekly' }) }),
      React.createElement(Route, { path: '/planner/new', element: React.createElement(RouteProbe, { name: 'planner-new' }) }),
      React.createElement(Route, { path: '/planner/:plannerId', element: React.createElement(RouteProbe, { name: 'planner' }) })
    )
  );
  const renderer = await renderElement(element);
  mountedRenderers.push(renderer);
  await flushEffects();
  return renderer;
}

function tabs(renderer) {
  return renderer.root.findAll((node) => node.type === 'button' && node.props.role === 'tab');
}

async function openNavigatorTab(renderer) {
  const tab = tabs(renderer).find((node) => textOf(node.children) === 'AI 학습 내비게이터');
  assert.ok(tab, 'AI 학습 내비게이터 탭이 있어야 한다');
  await press(tab);
}

function navigatorSection(renderer) {
  return renderer.root.find((node) => node.type === 'section' && node.props['aria-label'] === 'AI 학습 내비게이터');
}

function heroTitle(renderer) {
  const hero = renderer.root.findAll((node) => node.type === 'h4' && node.props.className === 'mobile-aln-hero-title');
  return hero.length ? textOf(hero[0].children) : null;
}

function minuteButton(renderer, minutes) {
  return renderer.root.find(
    (node) => node.type === 'button' && node.props.className?.includes('mobile-aln-seg-btn') && textOf(node.children).includes(`${minutes}분`)
  );
}

function stepSelect(renderer) {
  const matches = renderer.root.findAll((node) => node.type === 'select' && node.props['aria-label'] === '코칭 받을 현재 단계');
  return matches[0] || null;
}

function applySheet(renderer) {
  const matches = renderer.root.findAll((node) => node.props.role === 'dialog' && node.props['aria-label'] === '일정에 반영할까요?');
  return matches[0] || null;
}

function notice(renderer) {
  const matches = renderer.root.findAll((node) => node.type === 'div' && node.props.role === 'status' && node.props.className?.includes('mobile-aln-notice'));
  return matches[0] || null;
}

function route(renderer) {
  const matches = renderer.root.findAll((node) => node.type === 'p' && node.props['data-route'] !== undefined);
  return matches[0] ? { name: matches[0].props['data-route'], param: matches[0].props['data-param'] } : null;
}

async function change(instance, event) {
  await act(async () => {
    instance.props.onChange(event);
  });
}

test('플래너 자료 탭은 웹과 같은 AI 계획 분석 / AI 학습 내비게이터 / 메모 이고, 예전 다음 학습 탭은 없다', async () => {
  assert.deepEqual(PLANNER_TABS.map((tab) => tab.label), ['AI 계획 분석', 'AI 학습 내비게이터', '메모']);

  const renderer = await renderArchive();
  assert.deepEqual(tabs(renderer).map((node) => textOf(node.children)), ['AI 계획 분석', 'AI 학습 내비게이터', '메모']);
  assert.equal(navigatorCalls.length, 0, '탭을 열기 전에는 내비게이터를 호출하지 않는다');

  await openNavigatorTab(renderer);
  await flushEffects(DEBOUNCE_MS);
  assert.equal(findAllByText(renderer, '다음 학습 추천').length, 0, '예전 next-learning 카드는 렌더하지 않는다');
  assert.equal(findAllByText(renderer, 'AI 계획 분석 기반 추천').length, 0, '예전 recommendations 카드는 렌더하지 않는다');
  assert.equal(navigatorCalls.length, 1);
});

test('로드맵 플래너: AI 추천 → 시간·단계 변경 재계산 → 일정 반영 → 주간 일정 이동', async () => {
  const renderer = await renderArchive();
  await openNavigatorTab(renderer);

  assert.ok(findAllByText(renderer, '학습 데이터를 모아 AI 가 계획을 구성하고 있어요').length > 0, '첫 응답 전에는 스켈레톤');
  await flushEffects(DEBOUNCE_MS);

  assert.equal(navigatorCalls.length, 1);
  assert.equal(String(navigatorCalls[0].plannerId), '7');
  assert.deepEqual(navigatorCalls[0].body, { availableMinutes: 30, useLlm: true });
  assert.ok(navigatorCalls[0].signal instanceof AbortSignal, '요청은 취소 가능해야 한다');

  const section = navigatorSection(renderer);
  assert.match(textOf(section), /AI 학습 코치/);
  assert.match(textOf(section), /현재 단계 코칭/);
  assert.match(textOf(section), /AI 보강/);
  assert.equal(heroTitle(renderer), '합성곱 연산 학습 코칭 (30분)');
  assert.match(textOf(section), /1주차 3일 · 체크리스트 1\/3/);
  assert.match(textOf(section), /이번 30분 학습 활동/);
  assert.equal(renderer.root.findAll((node) => node.type === 'li' && node.props.className === 'mobile-aln-activity').length, 3);
  assert.match(textOf(section), /이 로드맵 자료로 푼 퀴즈 기록이 없어 일반 코칭으로 구성했어요/);
  assert.equal(minuteButton(renderer, 30).props['aria-pressed'], true);

  const select = stepSelect(renderer);
  assert.ok(select, '로드맵 모드에서는 현재 단계를 고를 수 있다');
  assert.equal(select.props.value, 13);
  assert.equal(select.findAll((node) => node.type === 'option').length, ROADMAP_ITEMS.length);

  await press(minuteButton(renderer, 60));
  await flushEffects(DEBOUNCE_MS);
  assert.equal(navigatorCalls.length, 2);
  assert.deepEqual(navigatorCalls[1].body, { availableMinutes: 60, useLlm: true });
  assert.equal(localStorage.getItem('sb.aln.minutes'), '60', '고른 시간은 다음에도 유지된다');
  assert.equal(heroTitle(renderer), '합성곱 연산 학습 코칭 (60분)');

  await change(stepSelect(renderer), { target: { value: '14' } });
  await flushEffects(DEBOUNCE_MS);
  assert.equal(navigatorCalls.length, 3);
  assert.deepEqual(navigatorCalls[2].body, { availableMinutes: 60, useLlm: true, currentStepId: 14 });

  await press(findButtonByText(renderer, '일정에 반영'));
  const sheet = applySheet(renderer);
  assert.ok(sheet, '반영 전에 항목을 확인하는 시트가 열린다');
  assert.match(textOf(sheet), /주간 일정 추가/);
  assert.match(textOf(sheet), /내일 · 10월 30일\(금\) · 30분 학습 세션/);
  assert.match(textOf(sheet), /플래너 날짜 변경/);
  assert.match(textOf(sheet), /예정일 10월 27일\(화\) → 10월 31일\(토\)/);
  const checkboxes = sheet.findAll((node) => node.type === 'input' && node.props.type === 'checkbox');
  assert.deepEqual(checkboxes.map((node) => node.props.checked), [true, true], '기본은 모든 후보 선택');
  assert.ok(findButtonByText(renderer, '2건 반영'));

  await change(checkboxes[1], { target: { checked: false } });
  const confirm = findButtonByText(renderer, '1건 반영');
  assert.ok(confirm, '체크 해제한 항목은 빠진다');
  await press(confirm);
  await flushEffects();

  assert.equal(applyCalls.length, 1);
  assert.equal(String(applyCalls[0].plannerId), '7');
  assert.deepEqual(applyCalls[0].body, { proposalToken: 'token-60-14', changeIds: ['session-13-2026-10-30'] });
  assert.equal(applySheet(renderer), null, '반영 후 시트가 닫힌다');
  assert.match(textOf(notice(renderer)), /일정에 반영했어요 — 주간 일정 1건\. 최신 데이터로 다시 계산했어요\./);

  await flushEffects(DEBOUNCE_MS);
  assert.equal(navigatorCalls.length, 4, '반영 뒤 최신 데이터로 다시 계산한다');
  assert.deepEqual(navigatorCalls[3].body, { availableMinutes: 60, useLlm: true, currentStepId: 14 });

  await press(findButtonByText(renderer, '주간 일정 보기'));
  assert.deepEqual(route(renderer), { name: 'weekly', param: '' });
});

test('수기 플래너: AI 다음 학습 — 선정 근거·다른 후보, 후보 플래너 열기', async () => {
  material = { materialId: 502, title: '이번 주 플래너', materialType: 'PLANNER', plannerId: 9 };
  navigatorHandler = async (plannerId, body) => manualResponse(body);

  const renderer = await renderArchive();
  await openNavigatorTab(renderer);
  await flushEffects(DEBOUNCE_MS);

  assert.equal(String(navigatorCalls[0].plannerId), '9');
  const section = navigatorSection(renderer);
  assert.match(textOf(section), /AI 다음 학습/);
  assert.match(textOf(section), /규칙 기반/);
  assert.equal(heroTitle(renderer), 'SQLD 기출문제 풀이');
  assert.match(textOf(section), /마감 10월 30일\(금\) · D-1/);
  assert.match(textOf(section), /선정 근거 65점/);
  assert.match(textOf(section), /사용자 우선순위사용자 우선순위 높음\+30/);
  assert.match(textOf(section), /2순위미적분 문제 풀이/);
  assert.match(textOf(section), /학습 복구 제안/);
  assert.equal(stepSelect(renderer), null, '수기 플래너에는 단계 선택이 없다');
  assert.equal(findAllByText(renderer, '퀴즈 오답 반영').length, 0);
  assert.equal(findButtonByText(renderer, '일정에 반영'), null, '반영 후보가 없으면 버튼을 숨긴다');

  const openAlt = renderer.root.find((node) => node.type === 'button' && node.props['aria-label'] === '미적분 문제 풀이 플래너 열기');
  await press(openAlt);
  assert.deepEqual(route(renderer), { name: 'planner', param: '9004' });
});

test('빠르게 시간을 바꾸면 마지막 값만 보내고, 늦게 도착한 이전 응답은 화면을 덮지 않는다', async () => {
  const pending = [];
  navigatorHandler = (plannerId, body) => {
    const request = deferred();
    pending.push({ body, request });
    return request.promise;
  };

  const renderer = await renderArchive();
  await openNavigatorTab(renderer);
  await flushEffects(DEBOUNCE_MS);
  assert.equal(navigatorCalls.length, 1);

  await press(minuteButton(renderer, 15));
  await flushEffects(50);
  await press(minuteButton(renderer, 60));
  await flushEffects(DEBOUNCE_MS);

  assert.equal(navigatorCalls.length, 2, '200ms 안의 연속 선택은 하나로 모은다');
  assert.equal(navigatorCalls[1].body.availableMinutes, 60);
  assert.equal(navigatorCalls[0].signal.aborted, true, '이전 요청은 취소된다');
  assert.equal(navigatorCalls[1].signal.aborted, false);

  await act(async () => {
    pending[1].request.resolve(roadmapResponse(pending[1].body));
  });
  assert.equal(heroTitle(renderer), '합성곱 연산 학습 코칭 (60분)');

  await act(async () => {
    pending[0].request.resolve(roadmapResponse(pending[0].body));
  });
  assert.equal(heroTitle(renderer), '합성곱 연산 학습 코칭 (60분)', '오래된 30분 응답은 버린다');
});

test('429 혼잡 응답은 재시도 안내와 다시 시도 버튼을 보여 준다', async () => {
  let attempts = 0;
  navigatorHandler = async (plannerId, body) => {
    attempts += 1;
    if (attempts === 1) {
      const error = new Error('busy');
      error.response = { status: 429, headers: {}, data: { error: { code: 'ADAPTIVE_BUSY', message: '요청이 많아요.', retryAfterSeconds: 4 } } };
      throw error;
    }
    return roadmapResponse(body);
  };

  const renderer = await renderArchive();
  await openNavigatorTab(renderer);
  await flushEffects(DEBOUNCE_MS);

  const alert = renderer.root.find((node) => node.type === 'div' && node.props.role === 'alert');
  assert.match(textOf(alert), /잠시 후 다시 시도해 주세요/);
  assert.match(textOf(alert), /\(4초 뒤 다시 시도\)/);

  await press(findButtonByText(renderer, '다시 시도'));
  await flushEffects(DEBOUNCE_MS);
  assert.equal(navigatorCalls.length, 2);
  assert.equal(renderer.root.findAll((node) => node.type === 'div' && node.props.role === 'alert').length, 0);
  assert.equal(heroTitle(renderer), '합성곱 연산 학습 코칭 (30분)');
});

test('반영 중 데이터가 바뀌어 409 가 오면 시트를 닫고 새 추천을 다시 불러온다', async () => {
  applyHandler = async () => {
    const error = new Error('stale');
    error.response = { status: 409, data: { error: { code: 'ADAPTIVE_STALE', message: '추천 이후 데이터가 바뀌었어요.' } } };
    throw error;
  };

  const renderer = await renderArchive();
  await openNavigatorTab(renderer);
  await flushEffects(DEBOUNCE_MS);

  await press(findButtonByText(renderer, '일정에 반영'));
  await press(findButtonByText(renderer, '2건 반영'));
  await flushEffects();

  assert.deepEqual(applyCalls[0].body.changeIds, ROADMAP_CHANGES.map((change) => change.id));
  assert.equal(applySheet(renderer), null);
  const warn = notice(renderer);
  assert.ok(warn.props.className.includes('is-warn'));
  assert.match(textOf(warn), /새 추천을 불러왔어요\./);
  assert.equal(findButtonByText(renderer, '주간 일정 보기'), null);

  await flushEffects(DEBOUNCE_MS);
  assert.equal(navigatorCalls.length, 2, '409 뒤 새 추천을 다시 계산한다');
});

test('현재 단계를 마치면 다음 단계 코칭으로 넘어갈 수 있다', async () => {
  navigatorHandler = async (plannerId, body) => {
    if (body.currentStepId == null) {
      return roadmapResponse(body, {
        currentStepId: 12,
        suggestedStepId: 13,
        result: { status: 'CURRENT_STEP_COMPLETED', source: 'RULE_BASED', recommendation: null, alternatives: [], warnings: [] },
        changes: [],
        proposalToken: null,
      });
    }
    return roadmapResponse(body);
  };

  const renderer = await renderArchive();
  await openNavigatorTab(renderer);
  await flushEffects(DEBOUNCE_MS);

  await press(findButtonByText(renderer, '1주차 3일 단계로 코칭 받기'));
  await flushEffects(DEBOUNCE_MS);
  assert.deepEqual(navigatorCalls[1].body, { availableMinutes: 30, useLlm: true, currentStepId: 13 });
  assert.equal(heroTitle(renderer), '합성곱 연산 학습 코칭 (30분)');
});

test('학습 시작은 집중 타이머를 띄우고, 완료 처리는 자동으로 하지 않는다', async () => {
  const renderer = await renderArchive();
  await openNavigatorTab(renderer);
  await flushEffects(DEBOUNCE_MS);

  await press(findButtonByText(renderer, '30분 학습 시작'));
  const timer = renderer.root.find((node) => node.type === 'div' && node.props.role === 'timer');
  assert.match(textOf(timer), /학습 중/);
  assert.match(textOf(timer), /지금: 핵심 개념 · 3x3 커널 손계산 \(10분\)/);
  const stored = JSON.parse(sessionStorage.getItem('sb.aln.focus.7'));
  assert.equal(stored.itemId, 13);
  assert.equal(stored.minutes, 30);
  assert.equal(findButtonByText(renderer, '학습 진행 중').props.disabled, true);

  await press(findButtonByText(renderer, '일시정지'));
  assert.match(textOf(renderer.root.find((node) => node.props.role === 'timer')), /일시정지/);

  await press(findButtonByText(renderer, '종료'));
  assert.equal(renderer.root.findAll((node) => node.props.role === 'timer').length, 0);
  assert.equal(sessionStorage.getItem('sb.aln.focus.7'), null);
  assert.equal(applyCalls.length, 0);
});

test('원본 플래너가 없는 보관 사본은 내비게이터를 호출하지 않는다', async () => {
  material = { materialId: 503, title: '삭제된 플래너 사본', materialType: 'PLANNER', plannerId: null };

  const renderer = await renderArchive();
  await openNavigatorTab(renderer);
  await flushEffects(DEBOUNCE_MS);

  assert.match(textOf(navigatorSection(renderer)), /원본 플래너가 없는 보관 항목이에요/);
  assert.equal(navigatorCalls.length, 0);
});
