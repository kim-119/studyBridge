import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
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

const { React, act } = await loadRenderer();
const { MemoryRouter, Route, Routes } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { default: PlannerScreen } = await importMobileModule('screens/planner/PlannerScreen.jsx');

const NEW_PLANNER_MARKER = 'new-planner-form';

function roadmapPlanner(id) {
  return { id, title: `운영체제 ${id}일차`, plannerType: 'ROADMAP', plannerDate: '2026-10-01' };
}

let serverPlanners;
let bulkDeleteCalls;
let bulkDeleteResult;
let mountedRenderers = [];

function stubPlannerApi() {
  serverPlanners = [roadmapPlanner(1), roadmapPlanner(2), roadmapPlanner(3)];
  bulkDeleteCalls = [];
  bulkDeleteResult = null;
  api.plannerService.getPlanners = async () => serverPlanners.map((planner) => ({ ...planner }));
  api.plannerService.bulkDeleteSelectedPlanners = async (plannerIds) => {
    bulkDeleteCalls.push([...plannerIds]);
    return bulkDeleteResult(plannerIds);
  };
}

beforeEach(() => {
  window.sessionStorage.clear();
  stubPlannerApi();
});

afterEach(async () => {
  const leftovers = mountedRenderers;
  mountedRenderers = [];
  for (const renderer of leftovers) {
    await act(async () => renderer.unmount());
  }
});

async function renderPlanner() {
  const element = React.createElement(
    MemoryRouter,
    { initialEntries: ['/planner'] },
    React.createElement(
      Routes,
      null,
      React.createElement(Route, { path: '/planner', element: React.createElement(PlannerScreen) }),
      React.createElement(Route, { path: '/planner/new', element: NEW_PLANNER_MARKER })
    )
  );
  const renderer = await renderElement(element);
  mountedRenderers.push(renderer);
  await flushEffects();
  return renderer;
}

function findFab(renderer) {
  return renderer.root.findAll(
    (instance) => instance.type === 'button' && String(instance.props.className).includes('mobile-fab')
  )[0];
}

function plannerCheckboxes(renderer) {
  return renderer.root.findAll((instance) => instance.type === 'button' && instance.props.role === 'checkbox');
}

function checkboxFor(renderer, title) {
  return plannerCheckboxes(renderer).find((checkbox) => textOf(checkbox.children).includes(title));
}

function checkedTitles(renderer) {
  return plannerCheckboxes(renderer)
    .filter((checkbox) => checkbox.props['aria-checked'] === true)
    .map((checkbox) => textOf(checkbox.children));
}

async function openFabMenu(renderer) {
  await press(findFab(renderer));
}

async function enterBulkDelete(renderer) {
  await openFabMenu(renderer);
  await press(findButtonByText(renderer, '일괄 삭제'));
}

async function selectPlanners(renderer, titles) {
  for (const title of titles) await press(checkboxFor(renderer, title));
}

function confirmPromptButton(renderer, label) {
  const prompt = renderer.root.find((instance) => instance.props.className === 'mobile-confirm');
  return prompt.find((instance) => instance.type === 'button' && textOf(instance.children) === label);
}

async function pressConfirmDelete(renderer) {
  await press(confirmPromptButton(renderer, '삭제'));
  await flushEffects();
}

test('T42 플래너 화면에 오른쪽 아래 + FAB가 렌더링된다', async () => {
  const renderer = await renderPlanner();
  const fab = findFab(renderer);

  assert.ok(fab, 'FAB must be rendered on /planner');
  assert.equal(fab.props['aria-label'], '플래너 메뉴');
  assert.match(textOf(renderer.toJSON()), /운영체제 1일차/);
});

test('T43 FAB를 누르면 새 Planner 생성과 일괄 삭제 메뉴가 열리고 새 Planner 생성은 /planner/new로 이동한다', async () => {
  const renderer = await renderPlanner();
  assert.equal(findButtonByText(renderer, '일괄 삭제'), null);

  await openFabMenu(renderer);
  assert.ok(findButtonByText(renderer, '새 Planner 생성'));
  assert.ok(findButtonByText(renderer, '일괄 삭제'));

  await press(findButtonByText(renderer, '새 Planner 생성'));
  assert.equal(textOf(renderer.toJSON()), NEW_PLANNER_MARKER);
});

test('T44 일괄 삭제 모드에서 체크박스를 토글하면 N개 선택이 갱신된다', async () => {
  const renderer = await renderPlanner();
  await enterBulkDelete(renderer);

  assert.equal(plannerCheckboxes(renderer).length, 3);
  assert.equal(findFab(renderer), undefined, 'FAB hides while selecting');
  assert.match(textOf(renderer.toJSON()), /0개 선택/);

  await selectPlanners(renderer, ['운영체제 1일차', '운영체제 3일차']);
  assert.match(textOf(renderer.toJSON()), /2개 선택/);
  assert.deepEqual(checkedTitles(renderer).length, 2);

  await press(checkboxFor(renderer, '운영체제 1일차'));
  assert.match(textOf(renderer.toJSON()), /1개 선택/);
  assert.equal(checkboxFor(renderer, '운영체제 1일차').props['aria-checked'], false);
  assert.equal(checkboxFor(renderer, '운영체제 3일차').props['aria-checked'], true);
});

test('T45 삭제는 확인을 거쳐야 하고 취소하면 API를 호출하지 않는다', async () => {
  bulkDeleteResult = async () => ({ success: true, deletedCount: 1 });
  const renderer = await renderPlanner();
  await enterBulkDelete(renderer);
  await selectPlanners(renderer, ['운영체제 2일차']);

  await press(findButtonByText(renderer, '삭제'));
  assert.equal(bulkDeleteCalls.length, 0, 'first tap only asks for confirmation');
  assert.ok(findAllByText(renderer, '되돌릴 수 없습니다').length > 0);

  await press(confirmPromptButton(renderer, '취소'));
  assert.equal(bulkDeleteCalls.length, 0);
  assert.ok(findButtonByText(renderer, '삭제'), 'delete trigger returns after cancel');
  assert.match(textOf(renderer.toJSON()), /1개 선택/);
  assert.match(textOf(renderer.toJSON()), /운영체제 2일차/);
});

test('T46 삭제 성공 시 행이 즉시 사라지고 선택이 초기화된다', async () => {
  let releaseDelete;
  bulkDeleteResult = (plannerIds) =>
    new Promise((resolve) => {
      releaseDelete = () => resolve({ success: true, deletedCount: plannerIds.length, message: '2개의 플래너를 삭제했습니다.' });
    });
  const renderer = await renderPlanner();
  await enterBulkDelete(renderer);
  await selectPlanners(renderer, ['운영체제 1일차', '운영체제 3일차']);

  await press(findButtonByText(renderer, '삭제'));
  await pressConfirmDelete(renderer);
  assert.deepEqual(bulkDeleteCalls, [[1, 3]]);

  api.plannerService.getPlanners = () => new Promise(() => {});
  await act(async () => releaseDelete());
  await flushEffects();

  const screenText = textOf(renderer.toJSON());
  assert.doesNotMatch(screenText, /운영체제 1일차/);
  assert.doesNotMatch(screenText, /운영체제 3일차/);
  assert.match(screenText, /운영체제 2일차/);
  assert.match(screenText, /2개의 플래너를 삭제했습니다/);
  assert.equal(plannerCheckboxes(renderer).length, 0, 'selection mode ends');
  assert.ok(findFab(renderer), 'FAB returns after delete');
});

test('T46 삭제 실패 시 목록과 선택을 유지하고 오류를 보여준다', async () => {
  bulkDeleteResult = async () => {
    const error = new Error('Request failed');
    error.response = { status: 400, data: { success: false, message: '본인 소유가 아니거나 존재하지 않는 플래너가 포함되어 있습니다.' } };
    throw error;
  };
  const renderer = await renderPlanner();
  await enterBulkDelete(renderer);
  await selectPlanners(renderer, ['운영체제 1일차', '운영체제 2일차']);

  await press(findButtonByText(renderer, '삭제'));
  await pressConfirmDelete(renderer);

  const screenText = textOf(renderer.toJSON());
  assert.equal(bulkDeleteCalls.length, 1);
  assert.match(screenText, /본인 소유가 아니거나 존재하지 않는 플래너가 포함되어 있습니다/);
  assert.match(screenText, /운영체제 1일차/);
  assert.match(screenText, /운영체제 2일차/);
  assert.match(screenText, /운영체제 3일차/);
  assert.match(screenText, /2개 선택/);
  assert.equal(checkedTitles(renderer).length, 2);
});
