import test from 'node:test';
import assert from 'node:assert/strict';
import {
  findButtonByText,
  flushEffects,
  importMobileModule,
  loadRenderer,
  press,
  registerComponentLoader,
  renderElement,
  textOf,
} from './support/componentHarness.mjs';

registerComponentLoader();

const { React, act } = await loadRenderer();
const { MemoryRouter, Route, Routes } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { default: GroupDetailScreen } = await importMobileModule('screens/groupstudy/GroupDetailScreen.jsx');

const MY_ID = 2;

const BASE_GROUP = {
  id: 41,
  title: '재무관리',
  description: '재무관리 기말 대비',
  isPublic: true,
  leaderId: 1,
  leaderName: '고병준',
  currentCount: 3,
  capacity: 10,
  status: 'RECRUITING',
  startDate: '2026-06-02',
  endDate: '2026-09-02',
  studyType: 'GENERAL',
  targetStudyMinutes: 300,
  joinQuestionEnabled: false,
  nicknameRuleEnabled: false,
};

function signIn() {
  localStorage.setItem('userId', String(MY_ID));
  localStorage.setItem('token', 'test-token');
  localStorage.setItem('user', JSON.stringify({ userId: MY_ID, displayName: '김도형' }));
}

async function renderDetail(group, { members = [{ userId: 1 }], applyGroup } = {}) {
  signIn();
  const applyCalls = [];
  Object.assign(api.groupService, {
    getGroupDetail: async () => group,
    getMembers: async () => members,
    getApplications: async () => [],
    applyGroup: async (...args) => {
      applyCalls.push(args);
      if (applyGroup) return applyGroup(...args);
      return {};
    },
  });

  const renderer = await renderElement(
    React.createElement(
      MemoryRouter,
      { initialEntries: [`/groupstudy/${group.id}`] },
      React.createElement(
        Routes,
        null,
        React.createElement(Route, { path: '/groupstudy/:groupId', element: React.createElement(GroupDetailScreen) })
      )
    )
  );
  await flushEffects();
  await flushEffects();
  return { renderer, applyCalls };
}

function inputLabelled(renderer, label) {
  const field = renderer.root.find(
    (instance) => instance.props?.className === 'mobile-field' && textOf(instance.children).includes(label)
  );
  return field.find((instance) => instance.type === 'input' || instance.type === 'textarea');
}

async function type(input, value) {
  await act(async () => input.props.onChange({ target: { value } }));
}

test('상세 화면은 서버 값 그대로 스터디 방식, 하루 목표, 운영 기간을 보여준다', async () => {
  const { renderer } = await renderDetail(BASE_GROUP);
  const text = textOf(renderer.toJSON());

  assert.match(text, /일반 스터디/);
  assert.match(text, /5시간/);
  assert.match(text, /2026-06-02 ~ 2026-09-02/);
  assert.match(text, /모집 중/);
});

test('정원이 찬 방은 모집 상태와 별도로 정원 마감을 표시하고 비회원 가입을 막는다', async () => {
  const { renderer } = await renderDetail({ ...BASE_GROUP, currentCount: 10 });
  const text = textOf(renderer.toJSON());

  assert.match(text, /모집 중/);
  assert.match(text, /정원 마감/);
  assert.equal(findButtonByText(renderer, '정원이 마감되었습니다').props.disabled, true);
});

test('정원이 찬 방이라도 가입 회원은 스터디룸에 입장할 수 있다', async () => {
  const { renderer } = await renderDetail({ ...BASE_GROUP, currentCount: 10 }, { members: [{ userId: 1 }, { userId: MY_ID }] });
  assert.equal(findButtonByText(renderer, '스터디룸 입장').props.disabled, false);
});

test('비공개방 비회원에게는 신청 버튼 대신 초대 링크 안내를 보여준다', async () => {
  const { renderer, applyCalls } = await renderDetail({ ...BASE_GROUP, isPublic: false });

  assert.match(textOf(renderer.toJSON()), /방장의 초대 링크로만 참여할 수 있습니다/);
  assert.equal(findButtonByText(renderer, '참가 신청'), null);
  assert.equal(applyCalls.length, 0);
});

test('가입 질문과 닉네임 규칙이 켜진 공개방은 답변과 닉네임을 함께 보낸다', async () => {
  const group = {
    ...BASE_GROUP,
    joinQuestionEnabled: true,
    joinQuestion: '이번 학기 목표는?',
    nicknameRuleEnabled: true,
    nicknameRule: '학교/학년/이름',
  };
  const { renderer, applyCalls } = await renderDetail(group);

  assert.match(textOf(renderer.toJSON()), /이번 학기 목표는\?/);
  assert.match(textOf(renderer.toJSON()), /학교\/학년\/이름/);

  await type(inputLabelled(renderer, '가입 질문 답변'), 'A+ 받기');
  await type(inputLabelled(renderer, '그룹 닉네임'), '영진/3/김도형');
  await press(findButtonByText(renderer, '바로 참여하기'));

  assert.deepEqual(applyCalls, [[41, { introduction: '공개 스터디 바로 참가', joinAnswer: 'A+ 받기', nickname: '영진/3/김도형' }]]);
});

test('필수 답변이 비어 있으면 서버로 보내지 않고 입력값을 유지한 채 안내한다', async () => {
  const group = { ...BASE_GROUP, joinQuestionEnabled: true, joinQuestion: '목표는?', nicknameRuleEnabled: true, nicknameRule: '이름' };
  const { renderer, applyCalls } = await renderDetail(group);

  await type(inputLabelled(renderer, '그룹 닉네임'), '도형');
  await press(findButtonByText(renderer, '바로 참여하기'));

  assert.equal(applyCalls.length, 0);
  assert.match(textOf(renderer.toJSON()), /가입 질문에 대한 답변을 입력해주세요/);
  assert.equal(inputLabelled(renderer, '그룹 닉네임').props.value, '도형');
});

test('서버가 가입을 거절하면 메시지를 보여주고 입력값을 보존한다', async () => {
  const group = { ...BASE_GROUP, nicknameRuleEnabled: true, nicknameRule: '이름' };
  const { renderer } = await renderDetail(group, {
    applyGroup: async () => {
      const error = new Error('Request failed');
      error.response = { status: 409, data: { message: '스터디 정원이 마감되었습니다.' } };
      throw error;
    },
  });

  await type(inputLabelled(renderer, '그룹 닉네임'), '도형');
  await press(findButtonByText(renderer, '바로 참여하기'));

  assert.match(textOf(renderer.toJSON()), /스터디 정원이 마감되었습니다/);
  assert.equal(inputLabelled(renderer, '그룹 닉네임').props.value, '도형');
});
