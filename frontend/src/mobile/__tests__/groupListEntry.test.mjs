import test from 'node:test';
import assert from 'node:assert/strict';
import {
  findButtonByText,
  flushEffects,
  importMobileModule,
  loadRenderer,
  registerComponentLoader,
  renderElement,
} from './support/componentHarness.mjs';

registerComponentLoader();

const { React } = await loadRenderer();
const { MemoryRouter, Route, Routes } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { default: GroupStudyScreen } = await importMobileModule('screens/groupstudy/GroupStudyScreen.jsx');

const MY_ID = 2;

const GROUPS = [
  { id: 31, title: '재무관리', isPublic: true, leaderId: 1, currentCount: 10, capacity: 10, status: 'RECRUITING', studyType: 'GENERAL' },
  { id: 32, title: '만석 남의 방', isPublic: true, leaderId: 5, currentCount: 10, capacity: 10, status: 'ACTIVE', studyType: 'CAM' },
  { id: 33, title: '여유 있는 방', isPublic: true, leaderId: 5, currentCount: 3, capacity: 10, status: 'RECRUITING', studyType: 'CAM' },
];

function signIn() {
  localStorage.setItem('userId', String(MY_ID));
  localStorage.setItem('token', 'test-token');
  localStorage.setItem('user', JSON.stringify({ userId: MY_ID, displayName: '김도형' }));
}

function cardButton(renderer, title, label) {
  const card = renderer.root.find(
    (instance) => instance.type === 'li' && instance.props.className?.includes('mobile-group-card') &&
      instance.findAll((child) => child.type === 'h2' && child.children.includes(title)).length > 0
  );
  return card.find((instance) => instance.type === 'button' && instance.children.includes(label));
}

async function renderList(membersByGroup) {
  signIn();
  const requestedMemberGroups = [];
  Object.assign(api.groupService, {
    getGroups: async () => GROUPS,
    getMembers: async (groupId) => {
      requestedMemberGroups.push(String(groupId));
      return membersByGroup[String(groupId)] || [];
    },
  });

  const renderer = await renderElement(
    React.createElement(
      MemoryRouter,
      { initialEntries: ['/groupstudy'] },
      React.createElement(
        Routes,
        null,
        React.createElement(Route, { path: '/groupstudy', element: React.createElement(GroupStudyScreen) }),
        React.createElement(Route, { path: '/groupstudy/:groupId/video', element: React.createElement('p', null, 'ROOM') }),
        React.createElement(Route, { path: '/groupstudy/:groupId', element: React.createElement('p', null, 'DETAIL') })
      )
    )
  );
  await flushEffects();
  await flushEffects();
  return { renderer, requestedMemberGroups };
}

test('만석인 방이라도 가입 회원은 목록에서 스터디룸 입장 버튼을 누를 수 있다', async () => {
  const { renderer } = await renderList({ 31: [{ userId: 1 }, { userId: MY_ID }], 32: [{ userId: 5 }] });

  const enter = cardButton(renderer, '재무관리', '스터디룸 입장');
  assert.equal(enter.props.disabled, false);

  const full = cardButton(renderer, '만석 남의 방', '정원 마감');
  assert.equal(full.props.disabled, true);
});

test('가입 여부 확인은 만석 카드에만 요청한다', async () => {
  const { requestedMemberGroups } = await renderList({});
  assert.deepEqual([...requestedMemberGroups].sort(), ['31', '32']);
});

test('가입 여부를 확인하지 못하면 막지 않고 상세 보기로 둔다', async () => {
  signIn();
  Object.assign(api.groupService, {
    getGroups: async () => GROUPS,
    getMembers: async () => {
      throw new Error('network');
    },
  });
  const renderer = await renderElement(
    React.createElement(MemoryRouter, null, React.createElement(GroupStudyScreen))
  );
  await flushEffects();
  await flushEffects();

  const detail = cardButton(renderer, '재무관리', '상세 보기');
  assert.equal(detail.props.disabled, false);
});

test('스터디룸 입장은 상세를 거치지 않고 스터디룸으로 이동한다', async () => {
  const { renderer } = await renderList({ 31: [{ userId: MY_ID }] });
  const { act } = await loadRenderer();

  await act(async () => cardButton(renderer, '재무관리', '스터디룸 입장').props.onClick());
  assert.equal(findButtonByText(renderer, '스터디룸 입장'), null);
  assert.ok(renderer.root.findAll((instance) => instance.type === 'p' && instance.children.includes('ROOM')).length === 1);
});
