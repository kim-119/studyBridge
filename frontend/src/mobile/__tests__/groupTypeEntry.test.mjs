import test from 'node:test';
import assert from 'node:assert/strict';
import {
  flushEffects,
  importMobileModule,
  loadRenderer,
  press,
  registerComponentLoader,
  renderElement,
  textOf,
} from './support/componentHarness.mjs';

registerComponentLoader({
  moduleOverrides: {
    'screens/groupstudy/useVideoSession.js': '__tests__/support/groupRuntimeFakes/useVideoSession.js',
    'screens/groupstudy/useGroupRoom.js': '__tests__/support/groupRuntimeFakes/useGroupRoom.js',
    'screens/groupstudy/VideoPreJoin.jsx': '__tests__/support/groupRuntimeFakes/VideoPreJoin.jsx',
  },
});

const { React, act } = await loadRenderer();
const { MemoryRouter, Route, Routes } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { videoSessionCalls } = await importMobileModule('__tests__/support/groupRuntimeFakes/useVideoSession.js');
const { default: VideoSessionScreen } = await importMobileModule('screens/groupstudy/VideoSessionScreen.jsx');

const GROUP_ID = '51';
const MY_ID = 2;
const mountedRenderers = [];

function signIn() {
  localStorage.setItem('userId', String(MY_ID));
  localStorage.setItem('token', 'test-token');
  localStorage.setItem('user', JSON.stringify({ userId: MY_ID, displayName: '김도형' }));
}

function stubServer(group) {
  Object.assign(api.groupService, {
    getGroupDetail: async () => group,
    getMembers: async () => [{ userId: 1, displayName: '고병준' }, { userId: MY_ID, displayName: '김도형' }],
    getApplications: async () => [],
    getGroupMaterials: async () => [],
    getGroupQuizzes: async () => [],
  });
  api.timerService.syncTimer = async () => ({});
}

async function openRoom(group) {
  signIn();
  stubServer(group);
  videoSessionCalls.join.length = 0;

  const renderer = await renderElement(
    React.createElement(
      MemoryRouter,
      { initialEntries: [`/groupstudy/${GROUP_ID}/video`] },
      React.createElement(
        Routes,
        null,
        React.createElement(Route, { path: '/groupstudy/:groupId/video', element: React.createElement(VideoSessionScreen) })
      )
    )
  );
  mountedRenderers.push(renderer);
  await flushEffects();
  await flushEffects();
  return renderer;
}

function buttonsLabelled(renderer, label) {
  return renderer.root.findAll((instance) => instance.type === 'button' && textOf(instance.children).trim() === label);
}

test.afterEach(async () => {
  while (mountedRenderers.length > 0) {
    const renderer = mountedRenderers.pop();
    await act(async () => renderer.unmount());
  }
});

const GENERAL_GROUP = { id: Number(GROUP_ID), title: '재무관리', leaderId: 1, capacity: 10, currentCount: 10, studyType: 'GENERAL' };
const CAM_GROUP = { ...GENERAL_GROUP, title: '아침 캠스터디', studyType: 'CAM' };

test('일반 스터디는 입장 준비 화면 없이 카메라·마이크를 끈 채로 바로 입장한다', async () => {
  const renderer = await openRoom(GENERAL_GROUP);

  assert.equal(buttonsLabelled(renderer, '입장하기').length, 0);
  assert.deepEqual(videoSessionCalls.join, [{ cameraOn: false, micOn: false }]);
});

test('일반 스터디 방에는 비디오 버튼과 카메라 전환 메뉴가 없고 마이크는 유지된다', async () => {
  const renderer = await openRoom(GENERAL_GROUP);

  assert.equal(buttonsLabelled(renderer, '비디오').length, 0);
  assert.equal(buttonsLabelled(renderer, '마이크').length, 1);
  assert.equal(buttonsLabelled(renderer, '참여자').length, 1);
  assert.equal(buttonsLabelled(renderer, '채팅/AI').length, 1);
  assert.equal(buttonsLabelled(renderer, '자료/퀴즈').length, 1);

  const menuButton = renderer.root.find(
    (instance) => instance.type === 'button' && instance.props['aria-label'] === '메뉴 열기'
  );
  await press(menuButton);
  assert.doesNotMatch(textOf(renderer.toJSON()), /카메라 전환/);
  assert.match(textOf(renderer.toJSON()), /스피커폰/);
});

test('스터디 방식을 아직 모르면 어느 흐름으로도 입장하지 않는다', async () => {
  signIn();
  stubServer(GENERAL_GROUP);
  api.groupService.getGroupDetail = () => new Promise(() => {});
  videoSessionCalls.join.length = 0;

  const renderer = await renderElement(
    React.createElement(
      MemoryRouter,
      { initialEntries: [`/groupstudy/${GROUP_ID}/video`] },
      React.createElement(
        Routes,
        null,
        React.createElement(Route, { path: '/groupstudy/:groupId/video', element: React.createElement(VideoSessionScreen) })
      )
    )
  );
  mountedRenderers.push(renderer);
  await flushEffects();

  assert.equal(buttonsLabelled(renderer, '입장하기').length, 0);
  assert.equal(videoSessionCalls.join.length, 0);
});

test('캠스터디는 입장 준비 화면을 거쳐 비디오 버튼이 있는 방으로 들어간다', async () => {
  const renderer = await openRoom(CAM_GROUP);

  assert.equal(videoSessionCalls.join.length, 0);
  await press(buttonsLabelled(renderer, '입장하기')[0]);
  await flushEffects();

  assert.equal(videoSessionCalls.join.length, 1);
  assert.equal(buttonsLabelled(renderer, '비디오').length, 1);
});
