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
const { default: GroupCreateScreen } = await importMobileModule('screens/groupstudy/GroupCreateScreen.jsx');

async function renderCreate(createGroup) {
  localStorage.setItem('userId', '2');
  localStorage.setItem('token', 'test-token');
  const calls = [];
  api.groupService.createGroup = async (payload) => {
    calls.push(payload);
    return createGroup(payload);
  };

  const renderer = await renderElement(
    React.createElement(
      MemoryRouter,
      { initialEntries: ['/groupstudy/new'] },
      React.createElement(
        Routes,
        null,
        React.createElement(Route, { path: '/groupstudy/new', element: React.createElement(GroupCreateScreen) }),
        React.createElement(Route, { path: '/groupstudy/:groupId', element: React.createElement('p', null, 'CREATED') })
      )
    )
  );
  await flushEffects();
  return { renderer, calls };
}

function fieldInput(renderer, label) {
  const field = renderer.root.find(
    (instance) => instance.props?.className === 'mobile-field' && textOf(instance.children).startsWith(label)
  );
  return field.find((instance) => instance.type === 'input' || instance.type === 'textarea');
}

async function type(input, value) {
  await act(async () => input.props.onChange({ target: { value } }));
}

function toggleLabelled(renderer, label) {
  return renderer.root.find(
    (instance) => instance.type === 'input' && instance.props.type === 'checkbox' && instance.props['aria-label'] === label
  );
}

async function fillRequired(renderer) {
  await type(fieldInput(renderer, '스터디 이름'), '재무관리');
  await type(fieldInput(renderer, '스터디 소개'), '기말 대비');
}

async function submit(renderer) {
  const form = renderer.root.find((instance) => instance.type === 'form');
  await act(async () => form.props.onSubmit({ preventDefault() {} }));
  await flushEffects();
}

test('기본값은 서버 기본값과 같은 일반 스터디, 하루 4시간, 질문·닉네임 규칙 꺼짐이다', async () => {
  const { renderer, calls } = await renderCreate(async () => ({ id: 70 }));
  await fillRequired(renderer);
  await submit(renderer);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].studyType, 'GENERAL');
  assert.equal(calls[0].targetStudyMinutes, 240);
  assert.equal(calls[0].joinQuestionEnabled, false);
  assert.equal(calls[0].nicknameRuleEnabled, false);
  assert.equal('joinQuestion' in calls[0], false);
});

test('캠 스터디, 하루 목표, 가입 질문, 닉네임 규칙을 골라 서버 필드로 보낸다', async () => {
  const { renderer, calls } = await renderCreate(async () => ({ id: 71 }));
  await fillRequired(renderer);

  await press(findButtonByText(renderer, '캠 스터디'));
  await press(findButtonByText(renderer, '6시간'));
  await act(async () => toggleLabelled(renderer, '가입 질문 사용').props.onChange({ target: { checked: true } }));
  await type(fieldInput(renderer, '가입 질문'), '이번 학기 목표는?');
  await act(async () => toggleLabelled(renderer, '그룹 닉네임 규칙 사용').props.onChange({ target: { checked: true } }));
  await type(fieldInput(renderer, '닉네임 규칙 안내'), '학교/학년/이름');
  await submit(renderer);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].studyType, 'CAM');
  assert.equal(calls[0].targetStudyMinutes, 360);
  assert.equal(calls[0].joinQuestion, '이번 학기 목표는?');
  assert.equal(calls[0].nicknameRule, '학교/학년/이름');
  assert.ok(renderer.root.findAll((instance) => instance.type === 'p' && instance.children.includes('CREATED')).length === 1);
});

test('가입 질문을 켜고 비워 두면 서버로 보내지 않고 안내한다', async () => {
  const { renderer, calls } = await renderCreate(async () => ({ id: 72 }));
  await fillRequired(renderer);
  await act(async () => toggleLabelled(renderer, '가입 질문 사용').props.onChange({ target: { checked: true } }));
  await submit(renderer);

  assert.equal(calls.length, 0);
  assert.match(textOf(renderer.toJSON()), /가입 질문을 사용하려면 질문 내용을 입력해주세요/);
});

test('서버 저장이 실패하면 화면을 유지하고 입력값을 보존한다', async () => {
  const { renderer } = await renderCreate(async () => {
    const error = new Error('Request failed');
    error.response = { status: 400, data: { message: '하루 목표 공부시간이 올바르지 않습니다.' } };
    throw error;
  });
  await fillRequired(renderer);
  await press(findButtonByText(renderer, '캠 스터디'));
  await submit(renderer);

  assert.match(textOf(renderer.toJSON()), /하루 목표 공부시간이 올바르지 않습니다/);
  assert.equal(fieldInput(renderer, '스터디 이름').props.value, '재무관리');
  assert.match(findButtonByText(renderer, '캠 스터디').props.className, /is-active/);
});

test('비공개 안내는 서버 정책대로 초대 링크 전용임을 알린다', async () => {
  const { renderer } = await renderCreate(async () => ({ id: 73 }));
  await press(findButtonByText(renderer, '비공개 스터디'));
  assert.match(textOf(renderer.toJSON()), /초대 링크로만 참여/);
});
