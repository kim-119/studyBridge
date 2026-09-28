import test from 'node:test';
import assert from 'node:assert/strict';
import {
  flushEffects,
  importMobileModule,
  loadRenderer,
  press,
  registerComponentLoader,
  renderElement as renderHarnessElement,
  textOf,
} from './support/componentHarness.mjs';

registerComponentLoader({
  moduleOverrides: {
    'screens/groupstudy/useVideoSession.js': '__tests__/support/groupRuntimeFakes/useVideoSession.js',
    'screens/groupstudy/useGroupRoom.js': '__tests__/support/groupRuntimeFakes/useGroupRoom.js',
    'screens/groupstudy/VideoPreJoin.jsx': '__tests__/support/groupRuntimeFakes/VideoPreJoin.jsx',
  },
});

const GROUP_ID = '7';
const LEADER_ID = 1;
const MEMBER_ID = 2;
const ENTERED_AT = Date.UTC(2026, 8, 28, 9, 0, 0);

const { React, act } = await loadRenderer();
const { MemoryRouter, Route, Routes } = await import('react-router-dom');
const { default: axios } = await import('axios');
const api = await importMobileModule('../services/api.js');
const { backgroundTasks } = await importMobileModule('data/backgroundTasks.js');
const { groupQuizTaskKey } = await importMobileModule('screens/groupstudy/quizGenerationModel.js');
const { groupMaterialUploadTaskKey } = await importMobileModule('screens/groupstudy/materialUploadModel.js');
const { default: VideoSessionScreen } = await importMobileModule('screens/groupstudy/VideoSessionScreen.jsx');
const { default: GroupDetailScreen } = await importMobileModule('screens/groupstudy/GroupDetailScreen.jsx');

const mountedRenderers = [];
const realDateNow = Date.now;
const realAxiosPost = axios.post;

async function renderElement(element) {
  const renderer = await renderHarnessElement(element);
  mountedRenderers.push(renderer);
  return renderer;
}

async function unmountAll() {
  while (mountedRenderers.length > 0) {
    const renderer = mountedRenderers.pop();
    await act(async () => renderer.unmount());
  }
}

function setClock(timestamp) {
  Date.now = () => timestamp;
}

function signInAs(userId) {
  localStorage.setItem('userId', String(userId));
  localStorage.setItem('token', 'test-token');
  localStorage.setItem('user', JSON.stringify({ userId, displayName: userId === LEADER_ID ? '방장' : '멤버' }));
}

function createServer({ materials = [], quizzes = [] } = {}) {
  const server = {
    materials: [...materials],
    quizzes: [...quizzes],
    calls: { generate: [], deleteQuiz: [], upload: [] },
  };

  Object.assign(api.groupService, {
    getGroupDetail: async () => ({ id: Number(GROUP_ID), title: '알고리즘 스터디', leaderId: LEADER_ID, capacity: 4, currentCount: 2 }),
    getMembers: async () => [
      { userId: LEADER_ID, displayName: '방장' },
      { userId: MEMBER_ID, displayName: '멤버' },
    ],
    getApplications: async () => [],
    getGroupMaterialDownloadUrl: () => new Promise(() => {}),
    getGroupMaterials: async () => [...server.materials],
    getGroupQuizzes: async () => [...server.quizzes],
    generateMaterialQuiz: async (groupId, materialId, options) => {
      server.calls.generate.push({ groupId, materialId, options });
      return new Promise(() => {});
    },
    deleteGroupQuiz: async (groupId, quizId) => {
      server.calls.deleteQuiz.push({ groupId, quizId });
      server.quizzes = server.quizzes.filter((quiz) => String(quiz.id) !== String(quizId));
    },
  });
  api.timerService.syncTimer = async () => ({});

  return server;
}

function pdfMaterial(id, title) {
  return { id, title, originalFileName: `${title}.pdf`, contentType: 'application/pdf', uploaderName: '방장' };
}

function acceptUploadAt(server, { createdQuiz }) {
  axios.post = async (url, formData, config) => {
    server.calls.upload.push({ url, formData, config });
    const material = { ...pdfMaterial(301, formData.get('title')), originalFileName: formData.get('file').name };
    server.materials = [material, ...server.materials];
    if (createdQuiz) server.quizzes = [createdQuiz, ...server.quizzes];
    return { data: material };
  };
}

function rejectUploadWith(status, message) {
  axios.post = async () => {
    const error = new Error('Request failed');
    error.response = { status, data: { status, message } };
    throw error;
  };
}

async function enterStudyRoom(userId = LEADER_ID) {
  signInAs(userId);
  setClock(ENTERED_AT);

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
  await flushEffects();
  await press(findButton(renderer, '입장하기'));
  await flushEffects();
  return renderer;
}

function findButton(renderer, label) {
  const matches = renderer.root.findAll(
    (instance) => instance.type === 'button' && textOf(instance.children).trim() === label
  );
  assert.ok(matches.length > 0, `버튼 "${label}"을 찾지 못했습니다`);
  return matches[0];
}

function findCloseButton(scope) {
  const root = scope.root || scope;
  return root.find((instance) => instance.type === 'button' && instance.props['aria-label'] === '닫기');
}

function findButtons(renderer, label) {
  return renderer.root.findAll((instance) => instance.type === 'button' && textOf(instance.children).trim() === label);
}

function timerOf(renderer) {
  const timers = renderer.root.findAll((instance) => instance.type === 'time');
  assert.equal(timers.length, 1, '스터디룸 타이머는 하나만 렌더링되어야 합니다');
  return timers[0];
}

async function repaintAt(timestamp) {
  setClock(timestamp);
  await act(async () => {
    document.dispatchEvent({ type: 'visibilitychange' });
  });
}

function uploadInputOf(renderer) {
  return renderer.root.find((instance) => instance.type === 'input' && instance.props.type === 'file');
}

async function selectFile(renderer, file) {
  const target = { files: [file], value: file.name };
  await act(async () => {
    uploadInputOf(renderer).props.onChange({ target, currentTarget: target });
  });
  await flushEffects();
  return target;
}

async function openResources(renderer) {
  await press(findButton(renderer, '자료/퀴즈'));
  await flushEffects();
}

function resetTask(key) {
  backgroundTasks.reset(key);
}

test.afterEach(async () => {
  await unmountAll();
  Date.now = realDateNow;
  axios.post = realAxiosPost;
  resetTask(groupMaterialUploadTaskKey(GROUP_ID));
  resetTask(groupQuizTaskKey(GROUP_ID));
  localStorage.clear();
});

test('T1 스터디룸 입장이 끝나면 타이머가 자동으로 시작된다', async () => {
  createServer();
  const renderer = await enterStudyRoom();

  assert.equal(timerOf(renderer).props['data-room-timer'], '00:00:00');

  await repaintAt(ENTERED_AT + 4 * 60_000 + 21_000);
  assert.equal(timerOf(renderer).props['data-room-timer'], '00:04:21');
});

test('T2 타이머는 방 제목 옆 헤더에 참여 인원과 함께 표시된다', async () => {
  createServer();
  const renderer = await enterStudyRoom();
  const header = renderer.root.find((instance) => instance.type === 'header' && instance.props.className === 'mobile-room-header');
  const titleRow = header.find((instance) => instance.props.className === 'mobile-room-header__title-row');

  assert.equal(textOf(titleRow.findByType('h1').children), '알고리즘 스터디');
  assert.equal(titleRow.findAll((instance) => instance.type === 'time').length, 1);
  assert.match(textOf(header.children), /2명 참여 중/);
});

test('T3 그룹 상세 화면에는 스터디 진행 시간 카드와 타이머 시작 버튼이 없다', async () => {
  createServer();
  signInAs(LEADER_ID);
  const renderer = await renderElement(
    React.createElement(
      MemoryRouter,
      { initialEntries: [`/groupstudy/${GROUP_ID}`] },
      React.createElement(
        Routes,
        null,
        React.createElement(Route, { path: '/groupstudy/:groupId', element: React.createElement(GroupDetailScreen) })
      )
    )
  );
  await flushEffects();
  const screenText = textOf(renderer.toJSON());

  assert.match(screenText, /스터디룸 입장/);
  assert.doesNotMatch(screenText, /스터디 진행 시간|타이머 시작|00:00:00/);
  assert.equal(renderer.root.findAll((instance) => instance.type === 'time').length, 0);
});

test('T4 참여자·채팅/AI·자료/퀴즈·카메라·마이크를 오가도 타이머가 초기화되지 않는다', async () => {
  createServer();
  const renderer = await enterStudyRoom();

  await repaintAt(ENTERED_AT + 65_000);
  for (const label of ['참여자', '채팅/AI', '자료/퀴즈', '비디오', '마이크']) {
    await press(findButton(renderer, label));
    await flushEffects();
    assert.equal(timerOf(renderer).props['data-room-timer'], '00:01:05', `${label} 이후 타이머가 유지되어야 합니다`);
  }

  await repaintAt(ENTERED_AT + 3_725_000);
  assert.equal(timerOf(renderer).props['data-room-timer'], '01:02:05');
});

test('T5 학습자료 업로드는 PDF만 고르는 파일 선택기를 연다', async () => {
  createServer();
  const renderer = await enterStudyRoom(MEMBER_ID);
  await openResources(renderer);

  const input = uploadInputOf(renderer);
  assert.equal(input.props.accept, 'application/pdf');
  assert.match(textOf(renderer.toJSON()), /PDF 자료 올리기/);
});

test('T6 업로드 성공 시 그룹 자료 API로 FormData를 보낸다', async () => {
  const server = createServer();
  acceptUploadAt(server, { createdQuiz: null });
  const renderer = await enterStudyRoom(MEMBER_ID);
  await openResources(renderer);

  const target = await selectFile(renderer, new File(['%PDF-1.4'], '강의 자료 1장.pdf', { type: 'application/pdf' }));

  assert.equal(server.calls.upload.length, 1);
  const [{ url, formData, config }] = server.calls.upload;
  assert.equal(url, `https://studybridge.test/api/groups/${GROUP_ID}/materials/upload-quiz`);
  assert.ok(formData instanceof FormData);
  assert.equal(formData.get('title'), '강의 자료 1장');
  assert.equal(formData.get('file').name, '강의 자료 1장.pdf');
  assert.equal(formData.get('questionCount'), '5');
  assert.equal(formData.get('timeLimitSeconds'), '15');
  assert.equal(config.headers.Authorization, 'Bearer test-token');
  assert.equal(target.value, '');
});

test('T7 업로드가 끝나면 새로고침 없이 자료·퀴즈 목록이 갱신되고 PDF를 열 수 있다', async () => {
  const server = createServer({ materials: [pdfMaterial(11, '기존 자료')] });
  acceptUploadAt(server, { createdQuiz: { id: 55, title: '강의 자료 1장 퀴즈', questionCount: 5 } });
  const renderer = await enterStudyRoom(MEMBER_ID);
  await openResources(renderer);

  await selectFile(renderer, new File(['%PDF-1.4'], '강의 자료 1장.pdf', { type: 'application/pdf' }));

  const materialIds = renderer.root
    .findAll((instance) => instance.type === 'li' && instance.props['data-material-id'] != null)
    .map((item) => item.props['data-material-id']);
  assert.deepEqual(materialIds, [301, 11]);
  assert.match(textOf(renderer.toJSON()), /"강의 자료 1장" 자료를 올리고 퀴즈를 만들었습니다/);

  await press(findButton(renderer, '자료 열기'));
  await flushEffects();
  const viewer = renderer.root.find((instance) => instance.props.className === 'mobile-room-viewer');
  assert.equal(viewer.props['aria-label'], '강의 자료 1장');

  await press(findCloseButton(viewer));
  await flushEffects();
  await press(findButton(renderer, '퀴즈'));
  await flushEffects();
  assert.equal(renderer.root.findAll((instance) => instance.type === 'li' && instance.props['data-quiz-id'] === 55).length, 1);
});

test('T7-1 업로드 실패 시 서버 메시지를 그대로 보여주고 PDF가 아니면 요청하지 않는다', async () => {
  const server = createServer();
  rejectUploadWith(403, '해당 그룹스터디방의 정식 멤버만 자료를 업로드할 수 있습니다.');
  const renderer = await enterStudyRoom(MEMBER_ID);
  await openResources(renderer);

  await selectFile(renderer, new File(['text'], '메모.txt', { type: 'text/plain' }));
  assert.match(textOf(renderer.toJSON()), /PDF 파일만 업로드할 수 있습니다/);
  assert.equal(server.calls.upload.length, 0);

  await selectFile(renderer, new File(['%PDF-1.4'], '자료.pdf', { type: 'application/pdf' }));
  assert.match(textOf(renderer.toJSON()), /자료를 올리지 못했습니다\. 해당 그룹스터디방의 정식 멤버만 자료를 업로드할 수 있습니다\./);
});

test('T8 방장은 퀴즈를 확인 후 삭제하면 목록에서 바로 사라지고 일반 멤버에게는 삭제 UI가 없다', async () => {
  const quizzes = [
    { id: 55, title: '1장 퀴즈', questionCount: 5 },
    { id: 56, title: '2장 퀴즈', questionCount: 3 },
  ];

  const memberServer = createServer({ quizzes });
  const memberRoom = await enterStudyRoom(MEMBER_ID);
  await openResources(memberRoom);
  await press(findButton(memberRoom, '퀴즈'));
  await flushEffects();
  assert.equal(findButtons(memberRoom, '삭제').length, 0);
  assert.equal(memberServer.calls.deleteQuiz.length, 0);
  await unmountAll();

  const leaderServer = createServer({ quizzes });
  const leaderRoom = await enterStudyRoom(LEADER_ID);
  await openResources(leaderRoom);
  await press(findButton(leaderRoom, '퀴즈'));
  await flushEffects();
  assert.equal(findButtons(leaderRoom, '삭제').length, 2);

  await press(findButtons(leaderRoom, '삭제')[0]);
  await flushEffects();
  assert.equal(leaderServer.calls.deleteQuiz.length, 0);
  assert.match(textOf(leaderRoom.toJSON()), /이 퀴즈를 삭제할까요/);

  const confirmButton = findButtons(leaderRoom, '삭제').find((button) => button.props.className.includes('danger'));
  await press(confirmButton);
  await flushEffects();

  assert.deepEqual(leaderServer.calls.deleteQuiz, [{ groupId: GROUP_ID, quizId: 55 }]);
  const quizIds = leaderRoom.root
    .findAll((instance) => instance.type === 'li' && instance.props['data-quiz-id'] != null)
    .map((item) => item.props['data-quiz-id']);
  assert.deepEqual(quizIds, [56]);
});

test('T9 그룹 퀴즈 생성은 공유 작업 저장소에서 한 번만 요청되고 패널을 닫았다 열어도 생성 중 상태가 유지된다', async () => {
  const server = createServer({ materials: [pdfMaterial(11, '기존 자료')] });
  const renderer = await enterStudyRoom(MEMBER_ID);
  await openResources(renderer);

  const generateButton = findButton(renderer, '이 자료로 퀴즈 만들기');
  await press(generateButton);
  await press(generateButton);
  await flushEffects();

  assert.equal(server.calls.generate.length, 1);
  assert.equal(backgroundTasks.get(groupQuizTaskKey(GROUP_ID)).status, 'generating');

  await press(findCloseButton(renderer));
  await flushEffects();
  await openResources(renderer);
  assert.match(textOf(renderer.toJSON()), /퀴즈를 생성하고 있습니다/);
  assert.equal(server.calls.generate.length, 1);
});
