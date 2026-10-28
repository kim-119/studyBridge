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
const { MemoryRouter, Route, Routes, useLocation, useParams } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { default: PlannerDetailScreen } = await importMobileModule('screens/planner/PlannerDetailScreen.jsx');
const { archiveActionLabel, archivedMaterialIdOf } = await importMobileModule('screens/planner/plannerAdapter.js');

const PLANNER_ID = '7';
let calls;
let archiveResult;
let mountedRenderers = [];

function ArchiveDestination() {
  const { materialId } = useParams();
  const location = useLocation();
  return React.createElement('p', { 'data-archive-material': materialId }, location.state?.notice || '');
}

function stubApi({ materialId = null } = {}) {
  calls = { archive: 0, pdf: 0 };
  archiveResult = async () => ({ id: Number(PLANNER_ID), materialId: 501 });
  localStorage.setItem('userId', '2');
  localStorage.setItem('token', 'test-token');
  api.plannerService.getPlanner = async () => ({
    id: Number(PLANNER_ID),
    title: '운영체제 1일차',
    plannerDate: '2026-10-28',
    materialId,
    timeTableJson: '[]',
  });
  api.plannerService.archive = async (id) => {
    calls.archive += 1;
    assert.equal(String(id), PLANNER_ID);
    return archiveResult();
  };
  api.plannerService.generatePdf = async () => {
    calls.pdf += 1;
    return { downloadUrl: 'https://example.invalid/planner.pdf' };
  };
  api.todoService.getTodos = async () => [];
}

async function renderDetail() {
  const renderer = await renderElement(
    React.createElement(
      MemoryRouter,
      { initialEntries: [`/planner/${PLANNER_ID}`] },
      React.createElement(
        Routes,
        null,
        React.createElement(Route, { path: '/planner/:plannerId', element: React.createElement(PlannerDetailScreen) }),
        React.createElement(Route, { path: '/archive/:materialId', element: React.createElement(ArchiveDestination) })
      )
    )
  );
  mountedRenderers.push(renderer);
  await flushEffects();
  return renderer;
}

function destination(renderer) {
  return renderer.root.findAll((node) => node.type === 'p' && node.props['data-archive-material'] !== undefined)[0];
}

beforeEach(() => stubApi());

afterEach(async () => {
  const leftovers = mountedRenderers;
  mountedRenderers = [];
  for (const renderer of leftovers) await act(async () => renderer.unmount());
});

test('보관 응답의 materialId 만 이동 대상으로 인정한다', () => {
  assert.equal(archivedMaterialIdOf({ materialId: 501 }), 501);
  assert.equal(archivedMaterialIdOf({ materialId: '501' }), 501);
  assert.throws(() => archivedMaterialIdOf({ id: 7 }));
  assert.throws(() => archivedMaterialIdOf({ materialId: 0 }));
  assert.throws(() => archivedMaterialIdOf(null));
});

test('이미 보관한 플래너는 갱신으로 표시한다(서버가 같은 항목을 갱신)', () => {
  assert.equal(archiveActionLabel({ materialId: null }), '자료보관함에 저장');
  assert.equal(archiveActionLabel({ materialId: 501 }), '자료보관함 갱신');
});

test('저장 성공 시 서버 materialId 의 자료보관함 상세로 이동하고 성공 안내를 넘긴다', async () => {
  const renderer = await renderDetail();
  await press(findButtonByText(renderer, '자료보관함에 저장'));
  await flushEffects();

  assert.equal(calls.archive, 1);
  const target = destination(renderer);
  assert.equal(target.props['data-archive-material'], '501');
  assert.match(textOf(target.children), /자료보관함에 저장했습니다/);
});

test('저장 중에는 다시 눌러도 요청을 한 번만 보낸다', async () => {
  let release;
  archiveResult = () => new Promise((resolve) => (release = () => resolve({ materialId: 501 })));
  const renderer = await renderDetail();
  const button = findButtonByText(renderer, '자료보관함에 저장');

  await act(async () => {
    button.props.onClick({});
    button.props.onClick({});
  });
  assert.equal(calls.archive, 1);
  const spinning = renderer.root.findAll(
    (node) => node.type === 'button' && node.props.disabled && node.findAll((child) => child.props?.className === 'mobile-button__spinner').length > 0
  );
  assert.equal(spinning.length, 1, '저장 버튼은 진행 중 비활성화된다');

  await act(async () => release());
  await flushEffects();
  assert.equal(destination(renderer).props['data-archive-material'], '501');
});

test('남의 플래너(403)·삭제된 플래너(404)·응답 이상은 실패 안내를 보여주고 이동하지 않는다', async () => {
  const cases = [
    [{ response: { status: 403, data: {} } }, /내 플래너만 자료보관함에 저장할 수 있습니다/],
    [{ response: { status: 404, data: {} } }, /플래너를 찾을 수 없습니다/],
    [null, /자료보관함 항목 정보를 받지 못했습니다/],
  ];

  for (const [error, message] of cases) {
    archiveResult = async () => {
      if (error) throw error;
      return { id: 7 };
    };
    const renderer = await renderDetail();
    await press(findButtonByText(renderer, '자료보관함에 저장'));
    await flushEffects();

    assert.equal(destination(renderer), undefined);
    assert.match(textOf(renderer.toJSON()), message);
  }
});

test('이미 보관한 플래너는 갱신 버튼으로 같은 보관 API 를 다시 호출하고, 기존 PDF 버튼은 그대로 동작한다', async () => {
  stubApi({ materialId: 501 });
  const renderer = await renderDetail();

  await press(findButtonByText(renderer, 'PDF'));
  assert.equal(calls.pdf, 1);
  assert.equal(calls.archive, 0, 'PDF 는 보관을 건드리지 않는다');

  await press(findButtonByText(renderer, '자료보관함 갱신'));
  await flushEffects();
  assert.equal(calls.archive, 1);
  assert.equal(destination(renderer).props['data-archive-material'], '501');
});
